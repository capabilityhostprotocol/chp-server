"""CHP Safety profile conformance (CP2 / Gate G2).

The safety-dev and safety-prod profiles must FAIL CLOSED: a missing or unready
required safety role (containment / witness / secret) makes the profile unclaimable.
Availability never expands permission. ContainmentPort and WitnessPort must be
canonical port roles so a safety provider can register them.
"""

from __future__ import annotations

from chp_server import PROFILES, validate_profile
from chp_server.ports import PORT_ROLES

_LOCAL = ["HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort"]


def test_containment_and_witness_are_canonical_roles():
    assert "ContainmentPort" in PORT_ROLES
    assert "WitnessPort" in PORT_ROLES


def test_safety_profiles_registered():
    assert "safety-dev" in PROFILES
    assert "safety-prod" in PROFILES


def test_safety_dev_fails_closed_without_containment():
    # Local roles ready but no containment → profile not claimable.
    missing = validate_profile("safety-dev", _LOCAL)
    assert missing == ["ContainmentPort"]
    # With containment ready → claimable.
    assert validate_profile("safety-dev", _LOCAL + ["ContainmentPort"]) == []


def test_safety_prod_requires_containment_witness_secret():
    # safety-prod demands containment + independent witness + secret broker.
    missing = validate_profile("safety-prod", _LOCAL)
    assert set(missing) == {"ContainmentPort", "WitnessPort", "SecretPort"}
    # Losing only the witness still fails closed (witness independence is required).
    partial = validate_profile("safety-prod", _LOCAL + ["ContainmentPort", "SecretPort"])
    assert partial == ["WitnessPort"]
    # Full safety stack ready → claimable.
    assert validate_profile(
        "safety-prod", _LOCAL + ["ContainmentPort", "WitnessPort", "SecretPort"]
    ) == []


def test_safety_prod_is_strict_superset_of_safety_dev():
    dev = set(PROFILES["safety-dev"]["required_roles"])
    prod = set(PROFILES["safety-prod"]["required_roles"])
    assert dev < prod
