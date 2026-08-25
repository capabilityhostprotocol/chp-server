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


# Per-profile conformance manifest (doc 52 / CONF-005): each claimable profile
# names the conformance scenario module(s) that gate a claim to it. Some live in
# provider packages (chp-host, chp-platform) because the provider owns the
# attachment; the manifest still records where the scenarios are.
CONFORMANCE_MANIFEST: dict[str, list[str]] = {
    "protocol-only": ["chp_server/tests/conformance/test_pkg_minimal.py"],
    "host": ["chp_server/tests/test_server.py::test_hostport_attachment_host_is_served",
             "chp-host/tests/test_server_port.py::test_entry_point_discovery_and_host_profile"],
    "local": ["chp_server/tests/conformance/test_local_profile.py"],
    "standalone": ["chp_server/tests/conformance/test_standalone_profile.py"],
    "managed": ["chp-platform/tests/test_server_port.py::test_managed_resolution_feature_truth"],
    "edge": ["chp_server/tests/conformance/test_edge_profile.py"],
    "gateway": ["chp-host/tests/test_server_port.py::test_router_gateway_profile"],
    "capability-introduction": ["chp_server/tests/conformance/test_introduction.py"],
    "minimum-useful":
        ["chp_server/tests/conformance/test_introduction.py::"
         "test_intro_013_introduced_capability_still_passes_admission"],
}


def validate_profile(name: str, ready_roles: list[str]) -> list[str]:
    """Return the missing required roles (empty = profile claimable)."""
    if name not in PROFILES:
        raise ValueError(f"unknown profile {name!r}; valid: {sorted(PROFILES)}")
    return [r for r in PROFILES[name]["required_roles"] if r not in ready_roles]
