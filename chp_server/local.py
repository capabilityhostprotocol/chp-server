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


class ExistingHostPort:
    """Serve a pre-built governed host (doc 00 host-vs-server separation).

    Wraps a caller-supplied ``LocalCapabilityHost`` — already built and populated
    by the embedder (its capabilities, evidence store, host key, host_id) — so the
    Server projects it (/server, /ready, feature truth, drain) without rebuilding
    or mutating it. One governed object fulfills Host+Admission+Execution+Evidence
    (DEC-SRV-004). Attached programmatically (it wraps a live object; not an
    entry-point/config-instantiable provider).
    """

    roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
    source = "local"

    def __init__(self, host) -> None:
        if host is None:
            raise ValueError("ExistingHostPort requires a governed host to serve")
        self.host = host

    def validate(self) -> None:
        if not hasattr(self.host, "ainvoke_envelope"):
            raise ValueError("ExistingHostPort.host is not a governed CHP host")

    def health(self) -> str:
        return "ready"

    def stop(self) -> None:
        # The host is owned by the embedder, not the port — never close it here.
        pass


class LocalArtifactPort:
    """Artifact data plane for the served host: attaches a content-addressed
    chp_core.ArtifactStore so /artifacts transfer lights up (artifact.transfer
    feature truth). Refs in the control plane, bytes in the data plane."""

    roles = ("ArtifactPort",)
    source = "local"
    requires = ("HostPort",)

    def __init__(self, root: str | None = None) -> None:
        self._root = root
        self._attachments = None
        self.store = None

    def bind(self, attachments) -> None:
        self._attachments = attachments

    def validate(self) -> None:
        pass

    def start(self) -> None:
        from chp_core.artifacts import ArtifactStore
        host_port = self._attachments.for_role("HostPort") if self._attachments else None
        host = getattr(host_port, "host", None)
        if host is None:
            raise RuntimeError("artifact plane requires a started HostPort attachment")
        self.store = ArtifactStore(self._root) if self._root else ArtifactStore()
        host.artifacts = self.store

    def health(self) -> str:
        return "ready" if self.store is not None else "unavailable"

    def stop(self) -> None:
        self.store = None


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
