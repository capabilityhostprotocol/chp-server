"""Base-server lifecycle, endpoints, feature truth, fail-closed profiles."""

from __future__ import annotations

import json
import urllib.request

import pytest

from chp_server import Server, ServerConfig, ServerStatus


@pytest.fixture()
def server(tmp_path):
    s = Server(ServerConfig(port=0, store=str(tmp_path / "evidence.sqlite")))
    s.start()
    yield s
    s.stop()


def _get(server, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}{path}") as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:  # 4xx/5xx still carry a JSON body
        return e.code, json.loads(e.read())


def test_lifecycle_and_liveness(server):
    assert server.state == ServerStatus.READY
    status, body = _get(server, "/health")
    assert status == 200 and body["status"] == "ok"


def test_ready_endpoint_truth(server):
    status, body = _get(server, "/ready")
    assert status == 200 and body["ready"] is True
    server.drain()
    status, body = _get(server, "/ready")
    assert status == 503 and body["state"] == "draining"


def test_server_describe(server):
    status, body = _get(server, "/server")
    assert status == 200
    assert body["server"] == "chp-server"
    assert body["profile"] == "protocol-only"
    assert body["protocol_version"] in body["supported_versions"]
    # PKG-010: truthful advertisement — nothing attached, nothing claimed.
    assert body["features"] and all(f["state"] == "unsupported" for f in body["features"])
    assert body["attachments"] == []


def test_negotiate_unsupported_before_work(server):
    # PKG-004/005: a required unavailable feature fails explicitly, no work done.
    out = server.negotiate(["invocation.local"])
    assert out == {"compatible": False, "code": "feature_unsupported",
                   "unknown_features": [], "unavailable_features": ["invocation.local"]}
    assert server.negotiate(["capability.resolve"])["compatible"] is False
    assert server.negotiate([])["compatible"] is True


def test_profile_fails_closed(tmp_path):
    s = Server(ServerConfig(port=0, profile="local", store=str(tmp_path / "e.sqlite")))
    with pytest.raises(RuntimeError, match="fail-closed"):
        s.start()
    assert s.state == ServerStatus.STOPPED


def test_attachment_flips_feature_truth(tmp_path):
    class FakeHost:
        roles = ("HostPort",)
        source = "local"
        def health(self):
            return "ready"

    s = Server(ServerConfig(port=0, store=str(tmp_path / "e.sqlite")))
    s.attach(FakeHost())
    s.start()
    try:
        by_name = {f.feature: f.state for f in s.features.snapshot(lifecycle=s.state)}
        assert by_name["capability.discovery"] == "ready"
        # invocation.local still needs Admission+Execution roles — stays unsupported.
        assert by_name["invocation.local"] == "unsupported"
    finally:
        s.stop()


def test_hostport_attachment_host_is_served(tmp_path):
    from chp_core.host import LocalCapabilityHost
    from chp_core.store import SQLiteEvidenceStore

    class GovernedHostPort:
        roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
        source = "local"
        def __init__(self, host):
            self.host = host
        def health(self):
            return "ready"

    attached_host = LocalCapabilityHost(
        "attached-host", store=SQLiteEvidenceStore(str(tmp_path / "a.sqlite")))
    s = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / "e.sqlite")))
    s.attach(GovernedHostPort(attached_host))
    s.start()
    try:
        # The wire surface serves the ATTACHED governed host, not the bare one,
        # and the host profile is claimable with its required role ready.
        _, body = _get(s, "/health")
        assert body["host_id"] == "attached-host"
        _, ready = _get(s, "/ready")
        assert ready["ready"] is True and ready["profile"] == "host"
    finally:
        s.stop()


def test_clean_shutdown(tmp_path):
    # PKG-008: clean lifecycle transition, no fabricated state.
    s = Server(ServerConfig(port=0, store=str(tmp_path / "e.sqlite")))
    s.start()
    s.stop()
    assert s.state == ServerStatus.STOPPED
    with pytest.raises(Exception):
        _get(s, "/health")
