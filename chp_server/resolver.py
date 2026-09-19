"""Directory-backed capability resolution — resolver tier, part 1.

A ``ResolutionPort`` that answers *where* a capability is served, from a configured
directory of supply advertisements (capability id -> endpoint), honoring each entry's
lease/freshness so a stale advertisement is never resolved (DISC-004). This is the
location-independent addressing brick for "invocable anywhere": given a capability,
find an endpoint to invoke it at.

Resolution confers NO authority (doc 35 §7, RESOLUTION_CONFERS_NO_AUTHORITY): a
resolved endpoint is a location, never a grant — the invocation still passes the full
gate pipeline at the serving host. A public wire /resolve surface and a relay/edge tier
are later parts (see RESOLVER_EDGE_DESIGN.md).
"""

from __future__ import annotations

import time
from typing import Callable

from .introduction import BATCH_SCHEMA_VERSION, verify_batch_trust


def advertisement_batch(host_id: str, endpoint: str, capability_ids, *,
                        ttl_s: float, generation, reachability: str = "direct") -> dict:
    """Build an (unsigned) supply-advertisement batch in the introduction-batch shape, so
    the 0053 signing + trust verification apply unchanged (RESOLVER_EDGE_DESIGN.md 3.5).
    Sign it with ``chp_server.introduction.sign_introduction_batch(batch, host_key)`` before
    ``POST /advertise``. ``endpoint`` + ``ttl_s`` ride in each candidate payload so the
    signature commitment binds them — a batch-level endpoint would sit outside the
    commitment and be forgeable."""
    return {
        "schema_version": BATCH_SCHEMA_VERSION,
        "source_id": host_id,
        "generation": str(generation),
        "declared_fact_classes": ["supply"],
        "candidates": [
            {"candidate_id": f"{host_id}:{cid}", "fact_class": "supply",
             "payload": {"capability_id": cid, "endpoint": endpoint, "ttl_s": ttl_s,
                         "reachability": reachability}}
            for cid in capability_ids
        ],
    }


class DirectoryResolutionPort:
    """Resolve capability requirements to fresh supply advertisements (endpoints)."""

    roles = ("ResolutionPort",)
    source = "local"

    def __init__(self, directory: list[dict] | None = None, *,
                 clock: Callable[[], float] | None = None,
                 trust_policy=None) -> None:
        # Each entry: {capability_id, endpoint, host_id, expires_at?: unix seconds|None}.
        # expires_at None = a static (unleased) advertisement; a number = a lease.
        self._dir: list[dict] = [dict(e) for e in (directory or [])]
        self._now = clock or time.time
        self._ready = True
        # Admission policy for WIRE advertisements (POST /advertise). None -> trust all
        # (the introduction-coordinator default); a directory exposed to remote advertisers
        # should pass a SourceTrustPolicy so only trusted issuers can add supply.
        self._trust_policy = trust_policy

    def validate(self) -> None:
        for e in self._dir:
            if not e.get("capability_id") or not e.get("endpoint"):
                raise ValueError("directory entry needs capability_id + endpoint")

    def start(self) -> None:
        self._ready = True

    def stop(self) -> None:
        self._ready = False

    def health(self) -> str:
        return "ready" if self._ready else "unavailable"

    @staticmethod
    def _key(e: dict) -> tuple:
        # One advertisement per (capability, host, endpoint): a re-advertise from the
        # same host for the same endpoint REFRESHES that entry (the heartbeat), never
        # accumulates duplicates.
        return (e.get("capability_id"), e.get("host_id"), e.get("endpoint"))

    def advertise(self, entry: dict) -> None:
        """Add or REFRESH a supply advertisement (capability -> endpoint), optionally
        leased via ``expires_at``. Upserts on (capability_id, host_id, endpoint) so a
        re-advertise renews the lease instead of duplicating. Authoritative freshness
        stays the advertiser's; the resolver only refuses to hand back an advertisement
        whose lease has passed."""
        if not entry.get("capability_id") or not entry.get("endpoint"):
            raise ValueError("advertisement needs capability_id + endpoint")
        entry = dict(entry)
        key = self._key(entry)
        for i, existing in enumerate(self._dir):
            if self._key(existing) == key:
                self._dir[i] = entry
                return
        self._dir.append(entry)

    def advertise_supply(self, supply: dict, *, endpoint: str, ttl_s: float,
                         reachability: str = "direct", now: float | None = None) -> int:
        """Publish a host's live supply to this directory as leased advertisements —
        the supply side of DISC-004 (RESOLVER_EDGE_DESIGN.md part 3).

        ``supply`` is the ``LocalStandalonePorts.supply()`` shape
        (``{"host_id", "capabilities": [{"id", ...}]}``). Each capability is advertised
        at ``endpoint`` with ``expires_at = now + ttl_s``. Re-calling is the HEARTBEAT:
        it refreshes the leases (upsert). Expired entries are pruned. Stop heartbeating
        and, after ``ttl_s``, the host's entries expire and ``resolve`` drops them — so
        the directory reflects live reachability, never a departed host. Returns the
        number of capabilities advertised."""
        now = self._now() if now is None else now
        host_id = supply.get("host_id")
        expires_at = now + ttl_s
        count = 0
        for cap in supply.get("capabilities", []):
            cid = cap.get("id")
            if not cid:
                continue
            self.advertise({"capability_id": cid, "endpoint": endpoint,
                            "host_id": host_id, "expires_at": expires_at,
                            "reachability": reachability})
            count += 1
        self._prune(now)
        return count

    def _prune(self, now: float) -> None:
        """Drop lease-expired advertisements (memory hygiene; ``resolve`` already omits
        them for correctness)."""
        self._dir = [e for e in self._dir
                     if e.get("expires_at") is None or now < e["expires_at"]]

    def accept_signed_advertisement(self, batch: dict, *, now: float | None = None) -> dict:
        """Verify a signed advertisement batch against this directory's SourceTrustPolicy
        (reusing ``verify_batch_trust`` — the SAME trust+crypto the introduction coordinator
        runs) and, if trusted, publish its capabilities as leased advertisements. Returns
        ``{"accepted": True, "advertised": n, "host_id": ...}`` or
        ``{"accepted": False, "denial": {...}}``.

        This is the wire advertisement feed (RESOLVER_EDGE_DESIGN.md part 3.5). The trust gate
        governs directory ADMISSION only — a resolved endpoint is still invoked under the full
        gate pipeline at the serving host, so a bad advertisement grants nothing. Each
        capability's endpoint/ttl come from its candidate payload (bound by the signature
        commitment)."""
        errors = verify_batch_trust(batch, self._trust_policy)
        if errors:
            return {"accepted": False,
                    "denial": {"code": "advertiser_not_trusted", "message": "; ".join(errors)}}
        now = self._now() if now is None else now
        host_id = batch.get("source_id")
        advertised = 0
        for cand in batch.get("candidates") or []:
            p = cand.get("payload") or {}
            cid, endpoint, ttl = p.get("capability_id"), p.get("endpoint"), p.get("ttl_s")
            if not cid or not endpoint or ttl is None:
                continue
            self.advertise({"capability_id": cid, "endpoint": endpoint,
                            "host_id": host_id, "expires_at": now + ttl,
                            "reachability": p.get("reachability") or "direct"})
            advertised += 1
        self._prune(now)
        return {"accepted": True, "advertised": advertised, "host_id": host_id}

    def resolve(self, requirement: dict, *, caller: str | None = None) -> list[dict]:
        """requirement -> matching, FRESH endpoint advertisements. Locations only —
        never a grant, never execution authority. A lease-expired advertisement is
        omitted (DISC-004): resolution never points at stale supply."""
        now = self._now()
        wanted = requirement.get("capability_id")
        namespace = requirement.get("namespace")
        out: list[dict] = []
        for e in self._dir:
            cid = e.get("capability_id") or ""
            if wanted and cid != wanted:
                continue
            if namespace and not cid.startswith(namespace):
                continue
            exp = e.get("expires_at")
            if exp is not None and now >= exp:
                continue  # lease expired -> stale advertisement, not resolvable
            out.append({
                "capability_id": cid,
                "endpoint": e.get("endpoint"),
                "host_id": e.get("host_id"),
                "freshness": "leased" if exp is not None else "static",
                "expires_at": exp,
                # Whether the endpoint is a directly-routable host address or a relay URL
                # (ingress/gateway/zenoh) for a host behind NAT/an org boundary — the
                # resolver returns the REACHABLE endpoint (RESOLVER_EDGE_DESIGN.md part 4).
                # The relay transport itself is the existing zenoh/ingress adapters.
                "reachability": e.get("reachability") or "direct",
            })
        return out
