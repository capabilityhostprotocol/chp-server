"""Capacity/observability conformance (CAP-001/004, OBS-003) over the served surface.

Health (liveness) is distinct from execution capacity (which sheds a rate-limit
429), rate limiting is an observable diagnostic, and structured evidence preserves
correlation identifiers without exposing payload secrets. chp-core-only.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from chp_core import CapabilityDescriptor, LocalCapabilityHost, SQLiteEvidenceStore
from chp_server import Server, ServerConfig


class GovernedHostPort:
    roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
    source = "local"

    def __init__(self, host):
        self.host = host

    def health(self):
        return "ready"


def _host(tmp_path):
    h = LocalCapabilityHost("capobs-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    h.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="e"),
               lambda _c, p: {"echo": p.get("text")})
    return h


def _invoke(server, payload=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/invoke",
        data=json.dumps({"capability_id": "demo.echo", "payload": payload or {}}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _get(server, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}{path}") as r:
        return r.status, json.loads(r.read())


@pytest.fixture()
def rate_limited_server(tmp_path, monkeypatch):
    # One request per (large) window — the second invoke in the window is shed.
    monkeypatch.setenv("CHP_HOST_RATE_LIMIT", "1")
    monkeypatch.setenv("CHP_HOST_RATE_WINDOW_S", "600")
    s = Server(ServerConfig(port=0, profile="local", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(_host(tmp_path)))
    s.start()
    yield s
    s.stop()


def test_cap_001_health_liveness_distinct_from_capacity(rate_limited_server):
    # CAP-001: server health and available execution capacity MUST remain distinct.
    # The execution path exhausts its rate/quota (429), but /health liveness is
    # unaffected — they are different signals, not one collapsed status.
    assert _invoke(rate_limited_server)["outcome"] == "success"     # first consumes the token
    with pytest.raises(urllib.error.HTTPError) as e:
        _invoke(rate_limited_server)                                # capacity exhausted
    assert e.value.code == 429
    status, body = _get(rate_limited_server, "/health")
    assert status == 200 and body["status"] == "ok"                # liveness independent of capacity


def test_cap_004_rate_limit_is_an_observable_diagnostic(rate_limited_server):
    # CAP-004: rate-limit/quota enforcement MUST be observable via explicit diagnostics.
    _invoke(rate_limited_server)                                    # consume the token
    with pytest.raises(urllib.error.HTTPError) as e:
        _invoke(rate_limited_server)
    assert e.value.code == 429                                     # explicit protocol diagnostic
    assert e.value.headers.get("Retry-After") is not None          # actionable back-off signal
    assert json.loads(e.value.read())["error"]["code"]             # structured error code


def test_obs_003_correlation_preserved_without_exposing_secrets(tmp_path):
    # OBS-003: structured evidence MUST preserve correlation identifiers WITHOUT
    # exposing payload secrets. The correlation id round-trips through /replay while
    # the raw secret payload is redacted, not disclosed.
    s = Server(ServerConfig(port=0, profile="local", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(_host(tmp_path)))
    s.start()
    try:
        out = _invoke(s, {"text": "hi", "api_key": "TOPSECRET-XYZ"})
        corr = out["correlation"]["correlation_id"]
        assert corr                                                # correlation id present
        with urllib.request.urlopen(f"http://127.0.0.1:{s.port}/replay/{corr}") as r:
            replay_raw = r.read().decode()
        assert corr in replay_raw                                  # correlation preserved in evidence
        assert "TOPSECRET-XYZ" not in replay_raw                   # secret payload NOT exposed
    finally:
        s.stop()
