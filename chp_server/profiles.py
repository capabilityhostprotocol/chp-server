"""Deployment profiles as data (doc 12). A profile = required port roles.

Profiles do not create different CHP semantics; the server fails closed when a
required role is absent or unready (doc 12 §10).
"""

from __future__ import annotations

_LOCAL_ROLES = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")

PROFILES: dict[str, dict] = {
    "protocol-only": {"required_roles": ()},
    "host": {"required_roles": ("HostPort",)},
    "local": {"required_roles": _LOCAL_ROLES},
    "standalone": {"required_roles": _LOCAL_ROLES + (
        "CapabilityCatalogPort", "SupplyPort", "ResolutionPort")},
    # managed/edge/gateway compose per deployment; their baseline required sets
    # (doc 12 §§6-8): managed needs at least one remote-backed role declared in
    # config; edge is local-capable; gateway mediates via federation.
    "managed": {"required_roles": _LOCAL_ROLES},
    "edge": {"required_roles": _LOCAL_ROLES},
    "gateway": {"required_roles": ("FederationPort",)},
    # v0.9 (docs 84/85): introduction-capable server; minimum-useful = at least
    # one capability discoverable through a governed source.
    "capability-introduction": {"required_roles": ("HostPort", "CapabilitySourcePort")},
    "minimum-useful": {"required_roles": ("HostPort", "CapabilitySourcePort")},
}


def validate_profile(name: str, ready_roles: list[str]) -> list[str]:
    """Return the missing required roles (empty = profile claimable)."""
    if name not in PROFILES:
        raise ValueError(f"unknown profile {name!r}; valid: {sorted(PROFILES)}")
    return [r for r in PROFILES[name]["required_roles"] if r not in ready_roles]
