"""Minimal-server conformance PKG-001..PKG-010 (doc 38).

Designed to run BOTH in-repo and inside the clean venv built by
scripts/chp-server-conformance.sh, where optional CHP packages are deliberately
absent (PKG-001 is the install step of that script itself).
"""

from __future__ import annotations

import importlib.util
import json
import urllib.request

import pytest

from chp_server import Server, ServerConfig, ServerStatus

OPTIONAL_PACKAGES = ("chp_host", "chp_platform", "mcp", "chp_transport_zenoh")


@pytest.fixture()
def server(tmp_path):
    s = Server(ServerConfig(port=0, store=str(tmp_path / "evidence.sqlite")))
    s.start()
    yield s
    s.stop()


def _get(server, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}{path}") as r:
        return r.status, json.loads(r.read())


def test_pkg_002_import_and_start_without_optional_packages(server):
    assert server.state == ServerStatus.READY


def test_pkg_003_describe_reports_truth(server):
    _, body = _get(server, "/server")
    assert body["distribution_version"]
    assert body["core_version"]
    assert body["protocol_version"] in body["supported_versions"]
    assert body["profile"] == "protocol-only"
    assert all(f["state"] == "unsupported" for f in body["features"])


def test_pkg_004_local_execution_required_fails_explicitly(server):
    out = server.negotiate(["invocation.local"])
    assert out["compatible"] is False and out["code"] == "feature_unsupported"


def test_pkg_005_local_resolution_fails_no_hidden_platform_call(server):
    out = server.negotiate(["capability.resolve"])
    assert out["compatible"] is False
    import sys
    assert "chp_platform" not in sys.modules


def test_pkg_006_healthy_without_platform(server):
    status, _ = _get(server, "/health")
    assert status == 200


def test_pkg_007_unrelated_base_operations_healthy(server):
    for path in ("/health", "/ready", "/server"):
        status, _ = _get(server, path)
        assert status == 200


def test_pkg_008_clean_shutdown(tmp_path):
    s = Server(ServerConfig(port=0, store=str(tmp_path / "e.sqlite")))
    s.start()
    s.stop()
    assert s.state == ServerStatus.STOPPED


def test_pkg_009_no_mandatory_optional_dependency():
    from importlib.metadata import requires
    reqs = [r.split(";")[0].strip() for r in (requires("chp-server") or [])]
    chp_reqs = [r for r in reqs if r.lower().startswith("chp")]
    assert chp_reqs and all(r.startswith("chp-core") for r in chp_reqs)


def test_pkg_010_feature_truth_not_overstated(server):
    # In the intended clean environment the optional packages are absent;
    # in-repo they may be installed — either way NOTHING is attached, so
    # every optional feature must read unsupported.
    _, body = _get(server, "/server")
    assert all(f["state"] == "unsupported" for f in body["features"])
    for pkg in OPTIONAL_PACKAGES:
        if importlib.util.find_spec(pkg) is None:
            continue  # absent (clean venv) — the strongest form of the check
