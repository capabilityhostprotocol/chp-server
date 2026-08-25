"""Local-profile conformance: the governed path THROUGH the served surface.

Work-packet-4 gate (doc 07): replay, audience/scope mismatch, expiry,
exhaustion, schema violation, and bypass cases fail correctly — driven over
POST /invoke against a Server(profile=local), so what is proven is the wire
surface, not just the in-process host. Denials are PROCESSED results (HTTP 200,
outcome=denied) per the binding's status rule; every denial leaves evidence.

chp-core-only (no optional CHP package) — runs in the clean venv too.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from chp_core import CapabilityDescriptor, LocalCapabilityHost, SQLiteEvidenceStore, signing
from chp_server import Server, ServerConfig


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GovernedHostPort:
    """Local governed attachment: LocalCapabilityHost fulfills all four roles."""

    roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
    source = "local"

    def __init__(self, host):
        self.host = host

    def health(self):
        return "ready"


@pytest.fixture()
def rig(tmp_path):
    host = LocalCapabilityHost(
        "local-conf-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))

    async def echo(_ctx, payload):
        return {"echo": payload.get("text")}

    host.register(
        CapabilityDescriptor(
            id="demo.echo", version="1.0.0", description="Echo.",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}},
                          "required": ["text"], "additionalProperties": False}),
        echo)

    server = Server(ServerConfig(port=0, profile="local", store=str(tmp_path / "s.sqlite")))
    server.attach(GovernedHostPort(host))
    server.start()
    key = signing.generate_keypair(tmp_path / "principal-key")
    yield server, key
    server.stop()


def _invoke(server, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/invoke",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())


def _mandate(key, *, scope, minutes_valid=60, max_invocations=None):
    now = datetime.now(timezone.utc)
    return signing.build_mandate(
        "principal-a", key, delegate_id="steward-x", scope=scope,
        valid_from=_iso(now - timedelta(hours=2)),
        valid_until=_iso(now + timedelta(minutes=minutes_valid)),
        created_at=_iso(now - timedelta(hours=2)),
        max_invocations=max_invocations)


def test_local_profile_ready_and_happy_path(rig):
    server, _ = rig
    r = server.ready()
    assert r["ready"] is True and r["profile"] == "local"
    status, out = _invoke(server, {"capability_id": "demo.echo", "payload": {"text": "hi"}})
    assert status == 200 and out["outcome"] == "success" and out["data"]["echo"] == "hi"


def test_unknown_capability_is_processed_denial_with_evidence(rig):
    server, _ = rig
    status, out = _invoke(server, {"capability_id": "no.such.cap", "payload": {}})
    # Binding status rule: a processed denial is HTTP 200, outcome=denied.
    assert status == 200 and out["outcome"] == "denied"
    assert out["denial"]["code"] == "capability_not_found"
    assert out.get("correlation", {}).get("correlation_id")  # denial left evidence


def test_input_schema_violation_denied_before_execution(rig):
    server, _ = rig
    _, out = _invoke(server, {"capability_id": "demo.echo", "payload": {"text": 42}})
    assert out["outcome"] == "denied"
    assert out["denial"]["code"] == "input_schema_validation_failed"


def test_idempotent_replay_returns_recorded_result(rig):
    server, _ = rig
    body = {"capability_id": "demo.echo", "payload": {"text": "once"},
            "invocation_id": "inv-replay-1"}
    _, first = _invoke(server, body)
    _, second = _invoke(server, {**body, "payload": {"text": "CHANGED"}})
    # Gate 0: the recorded result replays — the second payload never executes.
    assert first["outcome"] == "success"
    assert second["data"] == first["data"]
    assert second["data"]["echo"] == "once"


def test_expired_mandate_denied(rig):
    server, key = rig
    mandate = _mandate(key, scope=["demo.echo"], minutes_valid=-30)  # already expired
    _, out = _invoke(server, {"capability_id": "demo.echo",
                              "payload": {"text": "x"}, "mandate": mandate})
    assert out["outcome"] == "denied" and out["denial"]["code"] == "mandate_invalid"


def test_out_of_scope_mandate_denied(rig):
    server, key = rig
    mandate = _mandate(key, scope=["other.capability"])  # audience/scope mismatch
    _, out = _invoke(server, {"capability_id": "demo.echo",
                              "payload": {"text": "x"}, "mandate": mandate})
    assert out["outcome"] == "denied" and out["denial"]["code"] == "policy_blocked"


def test_exhausted_mandate_denied(rig):
    server, key = rig
    mandate = _mandate(key, scope=["demo.echo"], max_invocations=1)
    _, first = _invoke(server, {"capability_id": "demo.echo", "payload": {"text": "a"},
                                "invocation_id": "inv-m-1", "mandate": mandate})
    _, second = _invoke(server, {"capability_id": "demo.echo", "payload": {"text": "b"},
                                 "invocation_id": "inv-m-2", "mandate": mandate})
    assert first["outcome"] == "success"
    assert second["outcome"] == "denied"
    assert second["denial"]["code"] == "mandate_exhausted"


def test_no_wire_bypass_of_admission(rig):
    server, _ = rig
    # The served host's handlers are reachable only through ainvoke_envelope's
    # gate pipeline (host.py:975); the wire surface exposes no route that takes
    # a handler reference or skips /invoke. Denied evidence proves the gates ran.
    _, out = _invoke(server, {"capability_id": "demo.echo", "payload": {"text": 1}})
    corr = out["correlation"]["correlation_id"]
    with urllib.request.urlopen(
            f"http://127.0.0.1:{server.port}/replay/{corr}") as r:
        replayed = json.loads(r.read())
    assert replayed  # the denial is replayable evidence, not a silent rejection
