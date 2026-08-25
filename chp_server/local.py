"""Built-in standalone ports — thin projections of the attached governed host.

Everything here projects AUTHORITATIVE chp-core state (doc 35 §3): catalog and
resolution are `LocalCapabilityHost.discover()` filtering; supply is live
registration truth (a capability registered+enabled on the running host IS its
local supply — freshness "live" by construction). Richer supply semantics
(bindings across hosts, leases, freshness windows) stay upstream: GAP-SRV-001.

Resolution confers NO authority (doc 35 §7): a resolved capability still passes
the full 12-gate admission on invocation.
"""

from __future__ import annotations


class LocalStandalonePorts:
    """Catalog + supply + resolution for a single-host standalone server."""

    roles = ("CapabilityCatalogPort", "SupplyPort", "ResolutionPort")
    source = "local"
    requires = ("HostPort",)

    def __init__(self) -> None:
        self._host = None
        self._attachments = None

    # AttachmentRegistry calls bind() before start so role dependencies can be
    # looked up without importing concrete providers (doc 42 §4).
    def bind(self, attachments) -> None:
        self._attachments = attachments

    def validate(self) -> None:
        pass  # nothing to configure; the HostPort dependency is checked at start

    def start(self) -> None:
        host_port = self._attachments.for_role("HostPort") if self._attachments else None
        self._host = getattr(host_port, "host", None)
        if self._host is None:
            raise RuntimeError("local standalone ports require a started HostPort attachment")

    def health(self) -> str:
        return "ready" if self._host is not None else "unavailable"

    def stop(self) -> None:
        self._host = None

    # -- port surfaces (authoritative objects at the boundary) ---------------
    def catalog(self, *, caller: str | None = None, **filters) -> dict:
        return self._host.discover(caller=caller, **filters)

    def supply(self) -> dict:
        desc = self._host.discover()
        return {
            "host_id": desc["id"],
            "freshness": "live",  # in-process registration truth, not a cached feed
            "capabilities": [
                {"id": c["id"], "version": c.get("version"), "status": c.get("status")}
                for c in desc.get("capabilities", [])
            ],
        }

    def resolve(self, requirement: dict, *, caller: str | None = None) -> list[dict]:
        """requirement -> matching capability descriptors. Descriptors only —
        never a grant, never execution authority."""
        filters = {k: requirement[k] for k in ("category", "namespace", "tags", "status", "risk")
                   if requirement.get(k) is not None}
        caps = self._host.discover(caller=caller, **filters).get("capabilities", [])
        wanted = requirement.get("capability_id")
        if wanted:
            caps = [c for c in caps if c["id"] == wanted]
        return caps
