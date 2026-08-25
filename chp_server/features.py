"""FeatureRegistry — computed feature truth (docs 41/51).

One manifest drives Server.Describe, negotiation, readiness, and conformance.
Feature state is derived from attachment presence + health + lifecycle, never
from installed-package identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ports import AttachmentRegistry

# Externally meaningful feature states (doc 41 §2).
UNSUPPORTED = "unsupported"
INSTALLED = "installed"
INITIALIZING = "initializing"
READY = "ready"
DEGRADED = "degraded"
DRAINING = "draining"
UNAVAILABLE = "unavailable"

# Semantic features (doc 68) -> port roles whose readiness implies them.
# Implementation details (zenoh/postgres/platform) are never feature names.
FEATURE_ROLES: dict[str, tuple[str, ...]] = {
    "capability.discovery": ("HostPort",),
    "capability.resolve": ("ResolutionPort",),
    "invocation.submit": ("HostPort", "AdmissionPort", "ExecutionPort"),
    "invocation.local": ("HostPort", "AdmissionPort", "ExecutionPort"),
    "invocation.observe": ("HostPort", "EvidencePort"),
    "invocation.streaming": ("HostPort", "AdmissionPort", "ExecutionPort"),
    "evidence.query": ("EvidencePort",),
    "evidence.verify": ("EvidencePort",),
    "artifact.transfer": ("ArtifactPort",),
    "federation": ("FederationPort",),
    "mcp.import": ("McpPort",),
    "mcp.export": ("McpPort",),
}

FEATURES = tuple(FEATURE_ROLES)


@dataclass
class FeatureDescriptor:
    feature: str
    state: str
    source: str | None = None  # local | remote | platform | adapter
    detail: str | None = None
    roles: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict:
        d = {"feature": self.feature, "state": self.state}
        if self.source:
            d["source"] = self.source
        if self.detail:
            d["detail"] = self.detail
        return d


class FeatureRegistry:
    """Derives feature truth from an AttachmentRegistry + server lifecycle."""

    def __init__(self, attachments: "AttachmentRegistry") -> None:
        self._attachments = attachments

    def descriptor(self, feature: str, *, lifecycle: str) -> FeatureDescriptor:
        roles = FEATURE_ROLES[feature]
        role_states = {r: self._attachments.role_state(r) for r in roles}
        if any(s == UNSUPPORTED for s in role_states.values()):
            return FeatureDescriptor(feature, UNSUPPORTED, roles=roles)
        source = self._attachments.role_source(roles[0])
        # The weakest required role bounds the feature (doc 41 §4).
        order = (UNAVAILABLE, INSTALLED, INITIALIZING, DEGRADED, READY)
        state = min(role_states.values(), key=order.index)
        if lifecycle == "draining" and state == READY:
            state = DRAINING
        return FeatureDescriptor(feature, state, source=source, roles=roles)

    def snapshot(self, *, lifecycle: str) -> list[FeatureDescriptor]:
        return [self.descriptor(f, lifecycle=lifecycle) for f in FEATURES]

    def negotiate(self, required: list[str], optional: list[str] | None = None,
                  *, lifecycle: str = "ready") -> dict:
        """Intersection or structured incompatibility BEFORE work (doc 41 §5)."""
        unknown = [f for f in required if f not in FEATURE_ROLES]
        missing = [f for f in required if f in FEATURE_ROLES
                   and self.descriptor(f, lifecycle=lifecycle).state != READY]
        if unknown or missing:
            return {
                "compatible": False,
                "code": "feature_unsupported",
                "unknown_features": unknown,
                "unavailable_features": missing,
            }
        granted_optional = [f for f in (optional or []) if f in FEATURE_ROLES
                            and self.descriptor(f, lifecycle=lifecycle).state == READY]
        return {"compatible": True, "required": required, "optional": granted_optional}
