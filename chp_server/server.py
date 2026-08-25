"""Server — the assembly lifecycle object (docs 39/40).

Owns: boot, attachment lifecycle, feature computation, describe, readiness,
drain, shutdown. Owns NO protocol semantics — the wire surface, admission and
evidence come from chp-core; domain behavior from attachments.

Lifecycle: create -> configure -> attach -> validate -> start ->
ready/degraded -> drain -> stop.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version as _pkg_version

from chp_core.host import LocalCapabilityHost
from chp_core.store import SQLiteEvidenceStore
from chp_core.types import PROTOCOL_VERSION, new_id, utc_now, versions_upto

from .config import ServerConfig
from .features import FeatureRegistry
from .ports import AttachmentRegistry
from .profiles import PROFILES, validate_profile


def _dist_version(name: str) -> str:
    try:
        return _pkg_version(name)
    except PackageNotFoundError:
        return "0.0.0.dev0"


@dataclass(frozen=True)
class ServerInstanceIdentity:
    instance_id: str = field(default_factory=lambda: new_id("srv"))
    started_at: str | None = None


class ServerStatus:
    CREATED = "created"
    VALIDATED = "validated"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    DRAINING = "draining"
    STOPPED = "stopped"


class Server:
    """Programmatic server. `chp serve` is a CLI wrapper over this lifecycle."""

    @classmethod
    def serving(cls, host, *, profile: str = "host", **config_kwargs) -> "Server":
        """Build a Server that serves an ALREADY-built governed host.

        The embedder owns the host (its capabilities, evidence store, host key,
        host_id); the server projects it (/server, /ready, feature truth, drain)
        without rebuilding or mutating it — the host-vs-server seam. `config_kwargs`
        (bind/port/store/tls_*/environment) go to ServerConfig; host_id defaults to
        the host's own id so the trust chain is unambiguous.
        """
        from .local import ExistingHostPort
        config_kwargs.setdefault("host_id", getattr(host, "host_id", "chp-server"))
        server = cls(ServerConfig(profile=profile, **config_kwargs))
        server.attach(ExistingHostPort(host))
        return server

    def __init__(self, config: ServerConfig | None = None) -> None:
        self.config = config or ServerConfig()
        self.identity = ServerInstanceIdentity()
        self.attachments = AttachmentRegistry()
        self.features = FeatureRegistry(self.attachments)
        self.state = ServerStatus.CREATED
        self.config_generation = 1
        self._http = None
        self._thread: threading.Thread | None = None
        # The protocol surface needs a governed host object even with zero
        # capabilities: a bare LocalCapabilityHost executes nothing and denies
        # truthfully through the canonical 12-gate pipeline (nothing is fabricated).
        store = SQLiteEvidenceStore(self.config.store) if self.config.store else SQLiteEvidenceStore()
        self._backing_host = LocalCapabilityHost(
            host_id=self.config.host_id, version=_dist_version("chp-server"), store=store)

    # -- assembly -----------------------------------------------------------
    def attach(self, attachment) -> None:
        if self.state not in (ServerStatus.CREATED, ServerStatus.VALIDATED):
            raise RuntimeError(f"cannot attach in state {self.state}")
        self.attachments.attach(attachment)
        self.state = ServerStatus.CREATED  # re-validate after any attach

    def validate(self) -> None:
        self.attachments.validate_all()
        self.state = ServerStatus.VALIDATED

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        """Start serving in a background thread; blocks only until bound."""
        if self.state == ServerStatus.CREATED:
            self.validate()
        self.state = ServerStatus.STARTING
        self.attachments.load_entry_points(self.config.attachments)
        self.attachments.validate_all()
        self.attachments.start_all()
        # Fail closed: a claimed profile with a missing required role must not start
        # (doc 12 §10 / doc 40 §4).
        missing = validate_profile(self.config.profile, self.attachments.ready_roles())
        if missing:
            self.attachments.stop_all()
            self.state = ServerStatus.STOPPED
            raise RuntimeError(
                f"profile {self.config.profile!r} requires roles {missing} "
                "which are absent or unready (fail-closed)")
        from chp_core.http import create_http_server
        from .http import make_handler
        # A HostPort attachment brings the governed host to serve; without one,
        # the bare zero-capability host keeps the protocol surface truthful.
        host_port = self.attachments.for_role("HostPort")
        serving_host = getattr(host_port, "host", None) or self._backing_host
        self._http = create_http_server(
            serving_host, bind=self.config.bind, port=self.config.port,
            certfile=self.config.tls_certfile, keyfile=self.config.tls_keyfile,
            cafile=self.config.tls_cafile, handler_class=make_handler(self))
        self._thread = threading.Thread(target=self._http.serve_forever, daemon=True)
        self._thread.start()
        object.__setattr__(self.identity, "started_at", utc_now())
        self.state = ServerStatus.READY

    @property
    def port(self) -> int:
        return self._http.server_address[1] if self._http else self.config.port

    def ready(self) -> dict:
        missing = validate_profile(self.config.profile, self.attachments.ready_roles())
        ready = self.state == ServerStatus.READY and not missing
        return {"ready": ready, "state": self.state,
                "profile": self.config.profile, "missing_required_roles": missing}

    def drain(self) -> None:
        self.state = ServerStatus.DRAINING

    def stop(self) -> None:
        self.drain()
        if self._http is not None:
            self._http.shutdown()
            self._http.server_close()
            self._http = None
        self.attachments.stop_all()
        self.state = ServerStatus.STOPPED

    def serve_forever(self) -> None:
        """Blocking convenience for the CLI."""
        if self.state != ServerStatus.READY:
            self.start()
        try:
            self._thread.join()
        except KeyboardInterrupt:
            self.stop()

    # -- introspection ------------------------------------------------------
    def describe(self) -> dict:
        """Server.Describe (docs 38/39 §7) — the one feature-truth projection."""
        return {
            "server": "chp-server",
            "distribution_version": _dist_version("chp-server"),
            "core_version": _dist_version("chp-core"),
            "protocol_version": PROTOCOL_VERSION,
            "supported_versions": list(versions_upto(PROTOCOL_VERSION)),
            "instance": {"id": self.identity.instance_id,
                         "started_at": self.identity.started_at},
            "lifecycle_state": self.state,
            "profile": self.config.profile,
            "profiles_available": sorted(PROFILES),
            "environment": self.config.environment,
            "config_generation": self.config_generation,
            "features": [f.to_dict() for f in
                         self.features.snapshot(lifecycle=self.state)],
            "attachments": self.attachments.installed(),
            "config": self.config.redacted(),
        }

    def negotiate(self, required: list[str], optional: list[str] | None = None) -> dict:
        return self.features.negotiate(required, optional, lifecycle=self.state)
