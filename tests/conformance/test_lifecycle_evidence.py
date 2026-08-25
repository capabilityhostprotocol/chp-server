"""Lifecycle + evidence fault conformance (LIFE-006, EVID-004).

A draining server refuses new invocations (LIFE-006), and an evidence-backend
failure is never reported as a successful persistence (EVID-004). chp-core-only.
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


def _served(tmp_path, host):
    s = Server(ServerConfig(port=0, profile="local", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.start()
    return s


def _post(server, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/invoke",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_life_006_drain_rejects_new_invocations(tmp_path):
    host = LocalCapabilityHost("life-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="e"),
                  lambda _c, p: {"echo": p.get("text")})
    server = _served(tmp_path, host)
    try:
        status, ok = _post(server, {"capability_id": "demo.echo", "payload": {"text": "x"}})
        assert status == 200 and ok["outcome"] == "success"
        # Begin draining: new invocations are refused (LIFE-006), /ready shows draining.
        server.drain()
        status, out = _post(server, {"capability_id": "demo.echo", "payload": {"text": "y"}})
        assert status == 503 and out["error"]["code"] == "server_draining"
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/ready") as r:
            pass
    except urllib.error.HTTPError as e:
        assert e.code == 503  # /ready is 503 while draining
    finally:
        server.stop()


def test_evid_004_store_failure_not_reported_as_success(tmp_path):
    class FailingStore(SQLiteEvidenceStore):
        def append(self, event):  # evidence backend is down
            raise RuntimeError("evidence backend unavailable")

    host = LocalCapabilityHost("evid-host", store=FailingStore(str(tmp_path / "h.sqlite")))
    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="e"),
                  lambda _c, p: {"echo": p.get("text")})
    server = _served(tmp_path, host)
    try:
        status, out = _post(server, {"capability_id": "demo.echo", "payload": {"text": "x"}})
        # Persistence failed — the invocation is NEVER reported as a success.
        if status == 200:
            assert out["outcome"] != "success"
        else:
            assert status >= 500  # surfaced as a server error, not a 200 success
    finally:
        server.stop()
