"""Generation-safety / snapshot immutability (BOOT-007, ATT-009, INTRO-038, ADMIN-002).

Reconfiguration, source refresh, and capability withdrawal MUST NOT mutate the
semantic snapshot of already-admitted work. The chp-core guarantee is Gate-0
idempotent replay over an append-only store: an admitted invocation's recorded
result is immutable, so any later state change leaves it untouched. Proven over
the served surface. chp-core-only.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from chp_core import CapabilityDescriptor, LocalCapabilityHost, SQLiteEvidenceStore
from chp_server import IntroductionCoordinator, Server, ServerConfig


class GovernedHostPort:
    roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
    source = "local"

    def __init__(self, host):
        self.host = host

    def health(self):
        return "ready"


@pytest.fixture()
def rig(tmp_path):
    host = LocalCapabilityHost("gen-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))

    async def echo(_ctx, payload):
        return {"echo": payload.get("text"), "generation": "v1"}

    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="Echo."), echo)
    s = Server(ServerConfig(port=0, profile="local", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.start()
    yield s, host
    s.stop()


def _invoke(server, text, inv):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/invoke",
        data=json.dumps({"capability_id": "demo.echo", "payload": {"text": text},
                         "invocation_id": inv}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_reconfiguration_does_not_mutate_admitted_snapshot(rig):
    server, host = rig
    admitted = _invoke(server, "original", "inv-gen-1")
    assert admitted["outcome"] == "success" and admitted["data"]["generation"] == "v1"

    # Reconfigure: re-register the SAME capability id with DIFFERENT semantics
    # (a new generation of the handler) — i.e. a hot reload of an attachment.
    async def echo_v2(_ctx, payload):
        return {"echo": payload.get("text"), "generation": "v2"}

    import warnings
    with warnings.catch_warnings():  # register() overwrites a duplicate uri, warns
        warnings.simplefilter("ignore")
        host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="Echo v2."),
                      echo_v2)

    # The previously-admitted invocation still replays its ORIGINAL result — the
    # reload did not silently change the semantics of admitted work (BOOT-007/
    # ATT-009/INTRO-038/ADMIN-002).
    replayed = _invoke(server, "IGNORED", "inv-gen-1")
    assert replayed["data"] == admitted["data"]
    assert replayed["data"]["generation"] == "v1"  # NOT v2 — snapshot immutable
    # New work sees the new generation, so the reload did take effect for fresh work.
    fresh = _invoke(server, "new", "inv-gen-2")
    assert fresh["data"]["generation"] == "v2"


def test_withdrawal_does_not_rewrite_admitted_snapshot(rig):
    server, host = rig
    admitted = _invoke(server, "before-withdrawal", "inv-gen-3")
    assert admitted["outcome"] == "success"

    # Withdraw the capability entirely (retirement via the introduction plane).
    coord = IntroductionCoordinator(host)
    assert host.unregister("demo.echo") == 1  # supply withdrawn

    # New work is denied (capability gone)...
    fresh = _invoke(server, "after", "inv-gen-4")
    assert fresh["outcome"] == "denied" and fresh["denial"]["code"] == "capability_not_found"
    # ...but the already-admitted invocation's recorded snapshot is untouched.
    replayed = _invoke(server, "IGNORED", "inv-gen-3")
    assert replayed["outcome"] == "success" and replayed["data"] == admitted["data"]
