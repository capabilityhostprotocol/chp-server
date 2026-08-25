"""Per-profile conformance manifest completeness (CONF-005).

Every claimable profile MUST have an explicit conformance manifest entry naming
the scenario module(s) that gate a claim to it. This test is the machine check
that the manifest stays complete as profiles are added.
"""

from __future__ import annotations

from pathlib import Path

from chp_server import CONFORMANCE_MANIFEST, PROFILES

_PKG = Path(__file__).resolve().parents[2]  # .../packages/chp-server


def test_every_profile_has_a_manifest_entry():
    assert set(CONFORMANCE_MANIFEST) == set(PROFILES)
    assert all(CONFORMANCE_MANIFEST[p] for p in PROFILES)  # non-empty scenario list


def test_manifest_scenario_refs_are_well_formed():
    # Every scenario ref names a python test module under a tests/ tree. Where the
    # source tree is co-located (in-repo run, not the clean-venv copy), chp_server
    # -local scenario files must additionally resolve to a real file.
    in_source_tree = (_PKG / "chp_server").is_dir()
    for profile, scenarios in CONFORMANCE_MANIFEST.items():
        for ref in scenarios:
            path = ref.split("::", 1)[0]
            assert path.endswith(".py") and "/tests/" in path, f"{profile}: malformed {ref}"
            if in_source_tree and path.startswith("chp_server/"):
                assert (_PKG / path[len("chp_server/"):]).exists(), f"{profile}: missing {path}"
