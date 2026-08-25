"""Ports SPI + AttachmentRegistry (docs 35/42).

Attachments perform domain semantics owned by authoritative CHP packages; the
server owns only their lifecycle and routing. One attachment may fulfill several
roles (DEC-SRV-004: LocalCapabilityHost is Host+Admission+Execution+Evidence in
one governed object — the 12-gate pipeline is never split).
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any, Protocol, runtime_checkable

from . import features as F

# Canonical attachment roles (doc 35 §2 + the MCP bridge role).
PORT_ROLES = (
    "HostPort",
    "CapabilityCatalogPort",
    "SupplyPort",
    "ResolutionPort",
    "AdmissionPort",
    "ExecutionPort",
    "EvidencePort",
    "ArtifactPort",
    "FederationPort",
    "SecretPort",
    "McpPort",
)

ENTRY_POINT_GROUP = "chp_server.ports"


@runtime_checkable
class Attachment(Protocol):
    """Minimum attachment surface. Domain behavior stays in the provider package."""

    roles: tuple[str, ...]          # subset of PORT_ROLES
    source: str                     # local | remote | platform | adapter

    def validate(self) -> None: ...  # raise on bad configuration
    def start(self) -> None: ...
    def health(self) -> str: ...     # "ready" | "degraded" | "unavailable"
    def stop(self) -> None: ...


class AttachmentRegistry:
    """Owns attachment discovery + lifecycle; feature truth reads from here."""

    def __init__(self) -> None:
        self._attachments: list[Any] = []
        self._started: list[Any] = []

    # -- assembly -----------------------------------------------------------
    def attach(self, attachment: Any) -> None:
        unknown = [r for r in getattr(attachment, "roles", ()) if r not in PORT_ROLES]
        if unknown:
            raise ValueError(f"unknown port roles {unknown}; valid: {PORT_ROLES}")
        self._attachments.append(attachment)

    def load_entry_points(self, config: dict[str, Any] | None = None) -> list[str]:
        """Discover providers via the chp_server.ports entry-point group.

        Only names listed in *config* (attachments section) are loaded — installed
        code is not enabled authority (doc 12 §12). Returns loaded names.
        """
        wanted = set((config or {}).keys())
        loaded: list[str] = []
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            if ep.name not in wanted:
                continue
            factory = ep.load()
            self.attach(factory(**(config or {}).get(ep.name, {}) or {}))
            loaded.append(ep.name)
        return loaded

    # -- lifecycle ----------------------------------------------------------
    def validate_all(self) -> None:
        for a in self._attachments:
            if hasattr(a, "validate"):
                a.validate()

    def start_all(self) -> None:
        # Dependency-ordered start (docs 42 §§4-5, ATT-003): an attachment may
        # declare `requires = (<role>, ...)`; it starts only after some OTHER
        # attachment fulfills those roles. Unsatisfiable/cyclic requirements are
        # a startup error, not a hang.
        pending = list(self._attachments)
        while pending:
            provided = {r for a in self._started for r in getattr(a, "roles", ())}
            runnable = [a for a in pending
                        if all(r in provided for r in getattr(a, "requires", ()))]
            if not runnable:
                missing = {a: [r for r in getattr(a, "requires", ())
                               if r not in provided] for a in pending}
                names = {type(a).__name__: m for a, m in missing.items()}
                raise RuntimeError(
                    f"attachment dependencies unsatisfiable (cycle or missing role): {names}")
            for a in runnable:
                if hasattr(a, "bind"):
                    a.bind(self)
                if hasattr(a, "start"):
                    a.start()
                self._started.append(a)
                pending.remove(a)

    def stop_all(self) -> None:
        for a in reversed(self._started):
            if hasattr(a, "stop"):
                try:
                    a.stop()
                except Exception:  # failure isolation (doc 42 §7)
                    pass
        self._started.clear()

    # -- truth --------------------------------------------------------------
    def for_role(self, role: str) -> Any | None:
        for a in self._attachments:
            if role in getattr(a, "roles", ()):
                return a
        return None

    def role_state(self, role: str) -> str:
        a = self.for_role(role)
        if a is None:
            return F.UNSUPPORTED
        if a not in self._started:
            return F.INSTALLED
        try:
            return a.health() if hasattr(a, "health") else F.READY
        except Exception:
            return F.UNAVAILABLE

    def role_source(self, role: str) -> str | None:
        a = self.for_role(role)
        return getattr(a, "source", "local") if a is not None else None

    def ready_roles(self) -> list[str]:
        return [r for r in PORT_ROLES if self.role_state(r) == F.READY]

    def installed(self) -> list[dict]:
        return [
            {"roles": list(getattr(a, "roles", ())),
             "source": getattr(a, "source", "local"),
             "provider": type(a).__module__ + "." + type(a).__qualname__,
             "state": self.role_state(getattr(a, "roles", ("?",))[0])}
            for a in self._attachments
        ]
