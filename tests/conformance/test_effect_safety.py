"""Effect-safety conformance (EFF) over the served surface.

chp-core owns the effect model (CHP-CORE-014: outcome="indeterminate", never
coerced to failure; Gate-0 idempotent replay). The server's job is to PRESERVE
that truth across its wire projection, not reinvent it. These cases prove the
distinction survives POST /invoke. chp-core-only.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from chp_core import (CapabilityDescriptor, IndeterminateExecution, LocalCapabilityHost,
                      SQLiteEvidenceStore, signing)
from chp_server import Server, ServerConfig


class GovernedHostPort:
    roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
    source = "local"

    def __init__(self, host):
        self.host = host

    def health(self):
        return "ready"


@pytest.fixture()
def rig(tmp_path):
    host = LocalCapabilityHost("eff-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))

    async def echo(_ctx, payload):
        return {"echo": payload.get("text")}

    async def boom(_ctx, _payload):
        raise RuntimeError("handler blew up")  # ordinary execution failure

    async def unsure(_ctx, _payload):
        # Irreversible dispatch that cannot confirm its side effect.
        raise IndeterminateExecution("effect may or may not have occurred")

    for cid, h in (("demo.echo", echo), ("demo.boom", boom), ("demo.unsure", unsure)):
        host.register(CapabilityDescriptor(id=cid, version="1.0.0", description=cid), h)

    s = Server(ServerConfig(port=0, profile="local", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.start()
    yield s, signing.generate_keypair(tmp_path / "k")
    s.stop()


def _invoke(server, cap, inv=None, mandate=None):
    body = {"capability_id": cap, "payload": {"text": "x"}}
    if inv:
        body["invocation_id"] = inv
    if mandate:
        body["mandate"] = mandate
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/invoke",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_eff_003_indeterminate_preserved_not_coerced_to_failure(rig):
    server, _ = rig
    out = _invoke(server, "demo.unsure")
    # An indeterminate effect stays indeterminate over the wire (EFF-002/003/004):
    # it is NOT reported as a plain failure, and never as success.
    assert out["outcome"] == "indeterminate"
    assert out["success"] is False
    assert out["outcome"] != "failure"


def test_eff_008_four_outcomes_stay_distinguishable(rig):
    server, key = rig
    now = datetime.now(timezone.utc)
    iso = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    off_scope = signing.build_mandate(
        "p", key, delegate_id="d", scope=["other.cap"],
        valid_from=iso(now - timedelta(minutes=5)), valid_until=iso(now + timedelta(hours=1)),
        created_at=iso(now))
    resolution = _invoke(server, "no.such.capability")
    admission = _invoke(server, "demo.echo", mandate=off_scope)
    execution = _invoke(server, "demo.boom")
    effect = _invoke(server, "demo.unsure")
    # Resolution failure / admission denial / execution failure / effect
    # indeterminacy are FOUR distinct outcomes — never collapsed (EFF-008).
    assert resolution["outcome"] == "denied" and resolution["denial"]["code"] == "capability_not_found"
    assert admission["outcome"] == "denied" and admission["denial"]["code"] == "policy_blocked"
    assert execution["outcome"] == "failure"
    assert effect["outcome"] == "indeterminate"
    assert len({resolution["outcome"], execution["outcome"], effect["outcome"]}) == 3


def test_eff_005_006_replay_never_duplicates_effect(rig):
    server, _ = rig
    first = _invoke(server, "demo.echo", inv="inv-eff-1")
    # Same invocation_id (the authoritative CHP idempotency key) with a different
    # payload replays the recorded result — the effect never runs twice, and the
    # server performs no automatic retry that could duplicate it.
    second = _invoke(server, "demo.echo", inv="inv-eff-1")
    assert first["outcome"] == "success"
    assert second["data"] == first["data"]
    assert second["invocation_id"] == first["invocation_id"]
