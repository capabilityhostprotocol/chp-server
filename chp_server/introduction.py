"""Capability introduction — staged, provenance-carrying, generation-atomic (docs 77-85).

The server COORDINATES introduction; it owns no capability semantics
(DEC-INTRO-001). Batches follow contracts/introduction-batch.schema.json
verbatim. Activation integrates only through authoritative chp-core surfaces:

- ``supply`` facts (installed ``chp.adapters`` entry points) activate via
  ``chp_core.adapters.register_adapter`` on the governed host — the host
  registry stays the one catalog; duplicates are skipped there, never
  silently overwritten;
- ``definition`` facts (known capability packages without live supply) land in
  ``chp_core.registry`` — the authoritative known-package manifest
  (INTRO-001: definition accepted, no executable supply implied).

Withdrawal rides the host's withdrawal surface (closed GAP-SRV-004):
``withdraw_supply`` disables live registrations (Gate 3 denies
capability_disabled; definition knowledge survives — INTRO-045), ``retire``
unregisters them (capability_not_found), and neither ever rewrites recorded
execution truth.

Introduction authority is the admin/config plane (doc 77 §6): nothing here is
reachable by protocol clients, and the built-in source only introduces
adapters explicitly allowlisted in server configuration.
"""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import PackageNotFoundError, version as _dist_version

BATCH_SCHEMA_VERSION = "0.9"
FACT_CLASSES = ("definition", "binding", "supply", "readiness", "semantic_mapping")


def canonical_digest(payload: dict) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class IntroductionError(ValueError):
    pass


class IntroductionCoordinator:
    """stage -> validate -> conflict -> atomic activate, per source generation."""

    def __init__(self, host=None, registry_path: str | None = None) -> None:
        self._host = host
        self._registry_path = registry_path  # None -> chp_core default resolution
        # candidate_id -> {fact_class, payload, digest, sources: [source_id], generation}
        self.active: dict[str, dict] = {}
        self.generations: dict[str, str] = {}  # source_id -> active generation
        self.quarantine: list[dict] = []

    # -- staging -------------------------------------------------------------
    def stage(self, batch: dict) -> dict:
        """Validate a complete batch; NO live-state mutation on any failure."""
        errors: list[str] = []
        for key in ("schema_version", "source_id", "generation", "candidates"):
            if key not in batch:
                errors.append(f"missing batch field {key!r}")
        if not errors and batch["schema_version"] != BATCH_SCHEMA_VERSION:
            errors.append(f"unsupported schema_version {batch['schema_version']!r}")
        candidates = batch.get("candidates") or []
        for cand in candidates:
            cid = cand.get("candidate_id")
            if not cid:
                errors.append("candidate missing candidate_id")
                continue
            if cand.get("fact_class") not in FACT_CLASSES:
                errors.append(f"{cid}: invalid fact_class {cand.get('fact_class')!r}")
            payload = cand.get("payload")
            if not isinstance(payload, dict) or not payload:
                errors.append(f"{cid}: payload must be a non-empty object")
                continue
            if cand.get("fact_class") == "supply" and "adapter" not in payload:
                errors.append(f"{cid}: supply payload needs an 'adapter' entry-point name")
        # Deterministic conflict detection (INTRO-005/006): same candidate_id,
        # different digest -> conflict; same digest -> provenance coalesce.
        conflicts = []
        for cand in candidates:
            cid = cand.get("candidate_id")
            existing = self.active.get(cid)
            if existing is None:
                continue
            digest = cand.get("canonical_digest") or canonical_digest(cand.get("payload") or {})
            if digest != existing["digest"]:
                conflicts.append({"candidate_id": cid, "incoming_digest": digest,
                                  "active_digest": existing["digest"],
                                  "source_id": batch.get("source_id")})
        return {"valid": not errors, "errors": errors, "conflicts": conflicts,
                "candidate_count": len(candidates)}

    # -- activation ----------------------------------------------------------
    def activate(self, batch: dict) -> dict:
        """Atomic per source generation: any invalid candidate or conflict
        rejects the WHOLE generation (previous safe generation stays active,
        INTRO-006/007/008); conflicts are quarantined, never last-writer-wins."""
        report = self.stage(batch)
        source_id = batch.get("source_id", "?")
        if not report["valid"] or report["conflicts"]:
            self.quarantine.extend(report["conflicts"])
            return {**report, "activated": [], "generation_active": self.generations.get(source_id)}

        activated: list[str] = []
        for cand in batch["candidates"]:
            cid = cand["candidate_id"]
            digest = cand.get("canonical_digest") or canonical_digest(cand["payload"])
            if cid in self.active:  # same digest (stage guaranteed): coalesce provenance
                if source_id not in self.active[cid]["sources"]:
                    self.active[cid]["sources"].append(source_id)
                continue
            registered_uris: list[str] = []
            if cand["fact_class"] == "supply":
                registered_uris = self._activate_supply(cand)
            elif cand["fact_class"] == "definition":
                self._activate_definition(cand)
            # binding/readiness/semantic_mapping: no authoritative local owner yet
            # (GAP-SRV-001/GAP-INTRO-003..004) — accepted as provenance-carrying
            # facts only, no live-state integration.
            self.active[cid] = {"fact_class": cand["fact_class"], "payload": cand["payload"],
                                "digest": digest, "sources": [source_id],
                                "generation": batch["generation"],
                                "registered_uris": registered_uris}
            activated.append(cid)
        self.generations[source_id] = batch["generation"]
        return {**report, "activated": activated, "generation_active": batch["generation"]}

    def _activate_supply(self, cand: dict) -> list[str]:
        from chp_core.adapters import discover_adapters, register_adapter
        if self._host is None:
            raise IntroductionError("supply activation requires a governed host")
        name = cand["payload"]["adapter"]
        cls = discover_adapters().get(name)
        if cls is None:
            raise IntroductionError(f"adapter {name!r} is not installed")
        # Duplicates skipped upstream, never overwritten; the returned NEW
        # registrations are what this fact owns for later withdrawal.
        registered = register_adapter(self._host, cls())
        return [d.capability_uri for d in registered]

    def _activate_definition(self, cand: dict) -> None:
        # Known-package manifest (chp_core.registry) is the definition-only home;
        # entries here imply NO supply and NO invocability (doc 77 §4).
        from chp_core.registry import RegistryEntry, add_entry, load_registry
        p = cand["payload"]
        existing = {e.id for e in load_registry(self._registry_path)}
        if p["id"] not in existing:
            add_entry(RegistryEntry(id=p["id"], package=p.get("package", p["id"]),
                                    version=p.get("version", "*"), enabled=False,
                                    tags=list(p.get("tags", []))),
                      self._registry_path)

    # -- withdrawal / retirement (INTRO-044/045) -----------------------------
    def withdraw_supply(self, candidate_id: str) -> list[str]:
        """Withdraw a fact's LIVE supply (host.set_enabled False) while keeping
        the fact and any definition knowledge — supply withdrawal is not
        definition deletion (INTRO-045)."""
        fact = self.active[candidate_id]
        for uri in fact.get("registered_uris", []):
            self._host.set_enabled(uri, False)
        fact["withdrawn"] = True
        return list(fact.get("registered_uris", []))

    def retire(self, candidate_id: str) -> list[str]:
        """Retire a fact entirely: unregister live supply and drop the active
        fact. Definition-only registry knowledge and all recorded evidence
        remain — retirement never rewrites execution truth."""
        fact = self.active.pop(candidate_id)
        for uri in fact.get("registered_uris", []):
            self._host.unregister(uri)
        return list(fact.get("registered_uris", []))

    def detach(self, source_id: str) -> dict:
        """Source-scoped detach: future generations stop, and facts owned SOLELY
        by this source have their live supply withdrawn (coalesced facts with
        other valid provenance are untouched — INTRO-037)."""
        withdrawn = [cid for cid, fact in self.active.items()
                     if fact["sources"] == [source_id]]
        disabled: list[str] = []
        for cid in withdrawn:
            fact = self.active.pop(cid)
            for uri in fact.get("registered_uris", []):
                self._host.set_enabled(uri, False)
                disabled.append(uri)
        self.generations.pop(source_id, None)
        return {"withdrawn": withdrawn, "supply_disabled": disabled}


class EntryPointIntroductionPort:
    """Built-in CapabilitySource: installed ``chp.adapters`` entry points as a
    complete-snapshot batch, filtered by an explicit config allowlist —
    installation is never introduction (doc 77 §6, INTRO negative invariants).
    """

    roles = ("CapabilitySourcePort",)
    source = "local"
    requires = ("HostPort",)

    def __init__(self, adapters: list[str] | None = None,
                 source_id: str = "entry-points") -> None:
        self._allowlist = list(adapters or [])
        self.source_id = source_id
        self._attachments = None
        self.coordinator = None
        self.last_report = None

    def bind(self, attachments) -> None:
        self._attachments = attachments

    def validate(self) -> None:
        if not self._allowlist:
            raise ValueError("entry_point_introduction needs an 'adapters' allowlist "
                             "(installed packages are never auto-introduced)")

    def snapshot(self) -> dict:
        from chp_core.adapters import discover_adapters
        installed = discover_adapters()
        candidates = []
        for name in self._allowlist:
            if name not in installed:
                continue  # allowlisted but absent: nothing to claim
            cls = installed[name]
            try:
                pkg_version = _dist_version(f"chp-adapter-{name}")
            except PackageNotFoundError:
                pkg_version = "unknown"
            payload = {"adapter": name, "module": cls.__module__, "version": pkg_version}
            candidates.append({"candidate_id": f"supply:{name}", "fact_class": "supply",
                               "payload": payload,
                               "canonical_digest": canonical_digest(payload)})
        return {"schema_version": BATCH_SCHEMA_VERSION, "source_id": self.source_id,
                "generation": canonical_digest({"members": [c["canonical_digest"]
                                                            for c in candidates]})[:23],
                "complete_snapshot": True, "candidates": candidates}

    def start(self) -> None:
        host_port = self._attachments.for_role("HostPort") if self._attachments else None
        host = getattr(host_port, "host", None)
        if host is None:
            raise RuntimeError("capability introduction requires a started HostPort attachment")
        self.coordinator = IntroductionCoordinator(host)
        self.last_report = self.coordinator.activate(self.snapshot())

    def refresh(self) -> dict:
        self.last_report = self.coordinator.activate(self.snapshot())
        return self.last_report

    def health(self) -> str:
        if self.coordinator is None:
            return "unavailable"
        return "ready" if (self.last_report or {}).get("valid") else "degraded"

    def stop(self) -> None:
        self.coordinator = None
