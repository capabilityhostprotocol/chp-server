"""Edge-profile conformance (doc 12 §7): offline operation + restart
reconciliation. chp-core-only — runs in the clean venv (which is itself an
offline environment: --no-index installs, no Platform, no network services).
"""

from __future__ import annotations

import json
import urllib.request

from chp_core import CapabilityDescriptor, LocalCapabilityHost, SQLiteEvidenceStore
from chp_server import Server, ServerConfig


class GovernedHostPort:
    roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
    source = "local"

    def __init__(self, host):
        self.host = host

    def health(self):
        return "ready"


def _host(store_path):
    host = LocalCapabilityHost("edge-host", store=SQLiteEvidenceStore(str(store_path)))

    async def echo(_ctx, payload):
        return {"echo": payload.get("text")}

    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0",
                                       description="Echo."), echo)
    return host


def _invoke(server, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/invoke",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_edge_profile_ready_offline_and_reconciles_across_restart(tmp_path):
    host_store = tmp_path / "edge-host.sqlite"

    # First server generation: edge profile ready with zero external services.
    s1 = Server(ServerConfig(port=0, profile="edge", store=str(tmp_path / "s1.sqlite")))
    s1.attach(GovernedHostPort(_host(host_store)))
    s1.start()
    try:
        assert s1.ready() == {"ready": True, "state": "ready", "profile": "edge",
                              "missing_required_roles": []}
        first = _invoke(s1, {"capability_id": "demo.echo", "payload": {"text": "before"},
                             "invocation_id": "inv-edge-1"})
        assert first["outcome"] == "success"
        corr = first["correlation"]["correlation_id"]
    finally:
        s1.stop()

    # Restart: a NEW server process generation over the SAME durable evidence
    # store. Reconciliation truth: recorded results replay identically, evidence
    # is still queryable, and no work is fabricated or lost.
    s2 = Server(ServerConfig(port=0, profile="edge", store=str(tmp_path / "s2.sqlite")))
    s2.attach(GovernedHostPort(_host(host_store)))
    s2.start()
    try:
        replayed = _invoke(s2, {"capability_id": "demo.echo", "payload": {"text": "AFTER"},
                                "invocation_id": "inv-edge-1"})
        # Gate-0 replay across restart: the recorded result, not a re-execution.
        assert replayed["outcome"] == "success"
        assert replayed["data"] == first["data"] and replayed["data"]["echo"] == "before"
        with urllib.request.urlopen(f"http://127.0.0.1:{s2.port}/replay/{corr}") as r:
            assert json.loads(r.read())  # pre-restart evidence remains queryable
        # And new work proceeds normally after reconciliation.
        fresh = _invoke(s2, {"capability_id": "demo.echo", "payload": {"text": "new"},
                             "invocation_id": "inv-edge-2"})
        assert fresh["outcome"] == "success" and fresh["data"]["echo"] == "new"
    finally:
        s2.stop()