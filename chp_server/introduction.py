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
import re
from importlib.metadata import PackageNotFoundError, version as _dist_version

BATCH_SCHEMA_VERSION = "0.9"
FACT_CLASSES = ("definition", "binding", "supply", "readiness", "semantic_mapping")
# The proposal-0050 claim_type a signed introduction-batch attestation MUST carry, so a
# signature issued for some OTHER purpose can never be replayed as batch authorization.
INTRODUCTION_ASSERTION_CLAIM_TYPE = "capability_introduction_batch"

# A staged fact commits to a CONCRETE capability version (INTRO-015 "version
# rules"), never a range or wildcard: numeric dotted (1 to 3 components) with an
# optional semver pre-release/build tag. Range/x-range/comparator operators
# (^ ~ > < = x *) belong to a resolution SPEC, not to a fact's own identity —
# accepting them here would let an ambiguous version activate as authoritative
# truth.
_CONCRETE_VERSION = re.compile(r"\d+(\.\d+){0,2}(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?")

# "unknown" is the reserved sentinel a source emits when a real distribution
# version cannot be resolved (EntryPointIntroductionPort.snapshot). It is an
# honest non-claim — NOT a false concrete version and NOT a range — so it is a
# permitted declared value; activation carries it through as unversioned.
_VERSION_SENTINELS = ("unknown",)


def is_concrete_version(v: object) -> bool:
    return isinstance(v, str) and _CONCRETE_VERSION.fullmatch(v.strip()) is not None


def is_valid_declared_version(v: object) -> bool:
    """A declared capability version passes the INTRO-015 version rule iff it is
    absent, the explicit ``unknown`` sentinel, or a well-formed concrete version.
    A range/wildcard/garbage string fails — a fact must not claim an ambiguous
    version."""
    return v is None or v in _VERSION_SENTINELS or is_concrete_version(v)


def canonical_digest(payload: dict) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class IntroductionError(ValueError):
    pass


class SourceTrustPolicy:
    """Which sources a coordinator trusts to introduce facts (INTRO-018).

    Introduction is the administration/config plane (doc 77 §6), so a source is an
    operator-configured identity; this policy is the operator's trust decision over
    those source identities, evaluated BEFORE activation — an untrusted source's
    candidates never become active. ``trusted_sources=None`` trusts every source
    (today's behavior). ``source_fact_classes`` optionally narrows what a trusted
    source may introduce (per-source scope, complementing the built-in supply
    allowlist). Cryptographic issuer verification (a source signing its batch, the
    coordinator checking the signature against configured anchors) is the deeper
    follow-up and would be layered on top of this policy gate.
    """

    def __init__(self, trusted_sources=None, source_fact_classes=None,
                 trusted_key_ids=None, require_signed=False) -> None:
        self.trusted_sources = None if trusted_sources is None else frozenset(trusted_sources)
        self._scopes = {k: frozenset(v) for k, v in (source_fact_classes or {}).items()}
        # Cryptographic issuer trust (INTRO-018 deeper layer): a batch must present a
        # signed source attestation (proposal 0050) whose signer key_id is trusted and
        # whose signature commits to this batch. `trusted_key_ids` set (or require_signed)
        # turns this gate ON — trust then keys on a VERIFIED issuer key, not a source_id
        # string. None + require_signed=False keeps the string-source-id model.
        self.trusted_key_ids = None if trusted_key_ids is None else frozenset(trusted_key_ids)
        self.require_signed = bool(require_signed)

    def trusts(self, source_id) -> bool:
        return self.trusted_sources is None or source_id in self.trusted_sources

    def allows_fact_class(self, source_id, fact_class) -> bool:
        allowed = self._scopes.get(source_id)
        return allowed is None or fact_class in allowed

    def requires_signature(self) -> bool:
        return self.require_signed or self.trusted_key_ids is not None

    def trusts_key(self, key_id) -> bool:
        return self.trusted_key_ids is None or key_id in self.trusted_key_ids


def introduction_batch_commitment(batch: dict) -> str:
    """A stable commitment over a batch's introduced content — source_id, generation,
    and each candidate's canonical digest. A signing source puts this in its signed
    attestation's ``value``; the coordinator recomputes it so the signature binds to
    exactly this batch (INTRO-018 cryptographic issuer verification)."""
    members = sorted(
        [c.get("candidate_id"), c.get("canonical_digest") or canonical_digest(c.get("payload") or {})]
        for c in (batch.get("candidates") or []))
    return canonical_digest({"source_id": batch.get("source_id"),
                             "generation": batch.get("generation"), "members": members})


def sign_introduction_batch(batch: dict, issuer_key) -> dict:
    """Attach a source-signed attestation (proposal 0050 assertion) binding the issuer
    key to this batch's commitment. A coordinator under a cryptographic trust policy
    verifies it before activation. ``issuer_key`` is a chp_core.signing.HostKey."""
    from chp_core.signing import sign_assertion
    assertion = {
        "id": f"introbatch:{batch.get('source_id')}:{batch.get('generation')}",
        "claim_type": INTRODUCTION_ASSERTION_CLAIM_TYPE,
        "issuer": batch.get("source_id"),
        "value": introduction_batch_commitment(batch),
    }
    signed = dict(batch)
    signed["source_attestation"] = sign_assertion(issuer_key, assertion)
    return signed


def verify_batch_trust(batch: dict, policy: "SourceTrustPolicy | None") -> list[str]:
    """Source/issuer trust + cryptographic verification for a batch (INTRO-018),
    shared by ``IntroductionCoordinator.stage()`` and the resolver's wire advertisement
    feed (RESOLVER_EDGE_DESIGN.md part 3.5) so the crypto lives in ONE place. Returns a
    list of error strings ([] = trusted). ``None`` policy -> trust all (today's default):

    - the source is trusted to introduce facts, and each candidate's fact_class is within
      the source's declared scope; and
    - when the policy requires a signature, the batch carries a signed source attestation
      whose ed25519 signature verifies, whose ``claim_type`` is a capability_introduction
      batch (no cross-purpose signature), whose signer key is a trusted issuer, and whose
      committed value equals THIS batch's content.
    """
    errors: list[str] = []
    src = batch.get("source_id")
    if policy is not None and src is not None:
        if not policy.trusts(src):
            errors.append(f"source {src!r} is not trusted to introduce facts (source trust policy)")
        else:
            for cand in (batch.get("candidates") or []):
                fc = cand.get("fact_class")
                if not policy.allows_fact_class(src, fc):
                    errors.append(f"source {src!r} is not trusted to introduce fact_class "
                                  f"{fc!r} (source trust scope)")
    if policy is not None and policy.requires_signature():
        att = batch.get("source_attestation")
        if not att:
            errors.append("this batch requires a signed source attestation (issuer trust policy)")
        else:
            from chp_core.signing import verify_assertion_signature
            ver = verify_assertion_signature(att)
            signer = (att.get("signer_identity") or {}).get("host_id")
            if not ver.valid:
                errors.append(f"source attestation signature is invalid ({ver.reason})")
            elif att.get("claim_type") != INTRODUCTION_ASSERTION_CLAIM_TYPE:
                errors.append("source attestation is not a capability_introduction_batch assertion "
                              "(type confusion) — a signature issued for another purpose is refused")
            elif not policy.trusts_key(signer):
                errors.append(f"source issuer key {signer!r} is not a trusted issuer (issuer trust policy)")
            elif att.get("value") != introduction_batch_commitment(batch):
                errors.append("source attestation does not commit to this batch content (integrity)")
    return errors


class IntroductionCoordinator:
    """stage -> validate -> conflict -> atomic activate, per source generation."""

    def __init__(self, host=None, registry_path: str | None = None,
                 trust_policy: "SourceTrustPolicy | None" = None) -> None:
        self._host = host
        self._registry_path = registry_path  # None -> chp_core default resolution
        self._trust_policy = trust_policy     # None -> trust all sources (today's behavior)
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
        # Source/issuer trust + cryptographic issuer verification (INTRO-018),
        # evaluated BEFORE any activation. Shared with the resolver advertisement feed
        # via verify_batch_trust (one implementation of the crypto). No policy -> trust all.
        errors.extend(verify_batch_trust(batch, self._trust_policy))
        if not errors and batch["schema_version"] != BATCH_SCHEMA_VERSION:
            errors.append(f"unsupported schema_version {batch['schema_version']!r}")
        candidates = batch.get("candidates") or []
        # A source declares which candidate fact classes it can introduce
        # (INTRO-008). When declared, the coordinator refuses any candidate whose
        # fact_class the source did not declare — a source must not introduce fact
        # classes outside its declared scope. Absent (legacy batches) is not gated.
        declared_classes = batch.get("declared_fact_classes")
        for cand in candidates:
            cid = cand.get("candidate_id")
            if not cid:
                errors.append("candidate missing candidate_id")
                continue
            if cand.get("fact_class") not in FACT_CLASSES:
                errors.append(f"{cid}: invalid fact_class {cand.get('fact_class')!r}")
            if declared_classes is not None and cand.get("fact_class") not in declared_classes:
                errors.append(
                    f"{cid}: fact_class {cand.get('fact_class')!r} is not among the source "
                    f"declared_fact_classes {list(declared_classes)} (a source must not "
                    "introduce fact classes it did not declare)")
            payload = cand.get("payload")
            if not isinstance(payload, dict) or not payload:
                errors.append(f"{cid}: payload must be a non-empty object")
                continue
            if cand.get("fact_class") == "supply" and "adapter" not in payload:
                errors.append(f"{cid}: supply payload needs an 'adapter' entry-point name")
            # Authoritative version rule (INTRO-015): a declared capability
            # version must be a well-formed CONCRETE version, validated BEFORE
            # activation — a fact never activates against an unparseable or
            # range-shaped version (which would make its identity ambiguous).
            if not is_valid_declared_version(payload.get("version")):
                errors.append(
                    f"{cid}: version {payload.get('version')!r} is not a well-formed concrete "
                    "capability version (version rules)")
            # Authoritative integrity/digest rule (INTRO-016): a declared
            # canonical_digest must be a well-formed sha256 commitment
            # (sha256:<64 hex>). A malformed digest is refused before activation
            # — the coordinator never coalesces/conflict-checks against garbage.
            # (A source legitimately commits a digest over its own identity
            # subset, so we validate the commitment's FORM, not a full-payload
            # recompute that would reject stable subset digests.)
            declared = cand.get("canonical_digest")
            if declared is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", declared):
                errors.append(f"{cid}: canonical_digest is not a well-formed sha256 commitment (integrity)")
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


class RemoteChpIntroductionSource:
    """Remote-CHP source (INTRO-042): a peer host's /host descriptor becomes
    definition CLAIMS — origin-attributed, freshness-bounded, never supply.

    Incorporation stays a local decision: an optional capability allowlist
    filters the claims, ``max_age_s`` drops stale observations via the
    authoritative freshness primitive (chp_core.temporal.assess_freshness),
    and the resulting facts are definition knowledge only — invoking them
    locally still requires real local supply and admission.
    """

    def __init__(self, url: str, *, source_id: str | None = None,
                 api_key: str | None = None, capabilities: list[str] | None = None,
                 max_age_s: int | None = None) -> None:
        self._url = url
        self.source_id = source_id or f"remote-chp:{url}"
        self._api_key = api_key
        self._allowlist = capabilities
        self._max_age_s = max_age_s

    def snapshot(self) -> dict:
        from chp_core.http import RemoteCapabilityHost
        from chp_core.types import utc_now
        desc = RemoteCapabilityHost(self._url, api_key=self._api_key).discover()
        observed_at = utc_now()
        candidates = []
        for cap in desc.get("capabilities", []):
            if self._allowlist is not None and cap["id"] not in self._allowlist:
                continue
            payload = {"id": cap["id"], "version": cap.get("version"),
                       "origin_host": desc.get("id"), "origin_url": self._url,
                       "observed_at": observed_at, "claim": True}
            candidates.append({"candidate_id": f"remote-def:{cap['id']}",
                               "fact_class": "definition", "payload": payload,
                               "canonical_digest": canonical_digest(
                                   {k: payload[k] for k in ("id", "version", "origin_host")})})
        return {"schema_version": BATCH_SCHEMA_VERSION, "source_id": self.source_id,
                "generation": canonical_digest({"caps": [c["canonical_digest"]
                                                          for c in candidates]})[:23],
                "observed_at": observed_at, "complete_snapshot": True,
                "candidates": candidates}

    def fresh_candidates(self, batch: dict) -> list[dict]:
        """Freshness filter: claims older than max_age_s are STALE and excluded
        from incorporation (authoritative assess_freshness, never re-dated)."""
        if self._max_age_s is None:
            return list(batch["candidates"])
        from chp_core.temporal import assess_freshness
        from chp_core.types import utc_now
        now = utc_now()
        return [c for c in batch["candidates"]
                if assess_freshness(c["payload"]["observed_at"], now,
                                    self._max_age_s) == "fresh"]


class EntryPointIntroductionPort:
    """Built-in CapabilitySource: installed ``chp.adapters`` entry points as a
    complete-snapshot batch, filtered by an explicit config allowlist —
    installation is never introduction (doc 77 §6, INTRO negative invariants).
    """

    roles = ("CapabilitySourcePort",)
    source = "local"
    requires = ("HostPort",)
    # The fact classes this source can introduce (INTRO-008): installed entry
    # points are SUPPLY facts only — never definitions, bindings, or mappings.
    # Declared into every batch so the coordinator can refuse out-of-scope facts.
    introduces = ("supply",)

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
                "complete_snapshot": True, "declared_fact_classes": list(self.introduces),
                "candidates": candidates}

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
