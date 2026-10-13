"""Offline proof of the Vercel serverless host shim: drive the REAL chp-core handler
through the in-memory socket for the full sync surface and verify the evidence chain.

No network, no Vercel — just proves the shim reuses chp-core governance verbatim.
Run: PYTHONPATH=deploy/vercel:packages/chp-server:packages/python pytest this_file
"""
import json
import os
import tempfile

import pytest


@pytest.fixture()
def host(tmp_path, monkeypatch):
    monkeypatch.setenv("CHP_EVIDENCE_PATH", str(tmp_path / "ev.sqlite"))
    monkeypatch.delenv("CHP_HOST_API_KEYS", raising=False)
    monkeypatch.delenv("CHP_HOST_API_KEY", raising=False)
    monkeypatch.delenv("CHP_HOST_TOKEN_KEYS", raising=False)
    from chp_vercel_host import build_host
    return build_host("chp-vercel-test")


def _json(body: bytes):
    return json.loads(body.decode() or "{}")


def test_health_is_public_200(host):
    from chp_vercel_host import dispatch
    status, _, body = dispatch(host, "GET", "/health", {}, b"")
    assert status == 200


def test_host_discovery_lists_baked_caps(host):
    from chp_vercel_host import dispatch
    status, _, body = dispatch(host, "GET", "/host", {}, b"")
    assert status == 200
    ids = {c["id"] for c in _json(body).get("capabilities", [])}
    assert {"demo.echo", "math.add"} <= ids


def test_invoke_then_replay_chain_verifies(host):
    from chp_vercel_host import dispatch
    payload = json.dumps({"capability_id": "demo.echo",
                          "payload": {"message": "hello-vercel"}}).encode()
    status, _, body = dispatch(host, "POST", "/invoke",
                               {"Content-Type": "application/json"}, payload)
    assert status == 200, body
    result = _json(body)
    assert result.get("outcome") == "success", result
    # the baked cap's deterministic output is present
    assert result.get("data") == {"echo": "hello-vercel"}, result
    correlation = result.get("correlation") or {}
    corr = correlation.get("correlation_id") if isinstance(correlation, dict) else correlation
    assert corr, f"no correlation id in {result}"

    # GET /replay/<corr> returns the governed evidence chain over the wire
    status, _, rbody = dispatch(host, "GET", f"/replay/{corr}", {}, b"")
    assert status == 200, rbody
    replay = _json(rbody)
    events = replay.get("events") or []
    assert events, f"no events in replay {replay}"

    # and the append-only SHA256 chain verifies at the store
    assert host.store.verify_chain(corr).valid is True


def test_math_add_deterministic(host):
    from chp_vercel_host import dispatch
    payload = json.dumps({"capability_id": "math.add", "payload": {"a": 2, "b": 3}}).encode()
    status, _, body = dispatch(host, "POST", "/invoke",
                               {"Content-Type": "application/json"}, payload)
    assert status == 200, body
    result = _json(body)
    assert result.get("outcome") == "success", result
    assert result.get("data") == {"sum": 5}, result


def test_unauthorized_when_keys_configured(host, monkeypatch):
    # With an API key configured, an unkeyed /host is 401 — proving the shim runs the
    # real chp-core auth path (not a bypass).
    monkeypatch.setenv("CHP_HOST_API_KEYS", "steward:s3cret")
    from chp_vercel_host import dispatch
    status, _, _ = dispatch(host, "GET", "/host", {}, b"")
    assert status == 401
    status_ok, _, _ = dispatch(host, "GET", "/host", {"X-CHP-Key": "s3cret"}, b"")
    assert status_ok == 200
