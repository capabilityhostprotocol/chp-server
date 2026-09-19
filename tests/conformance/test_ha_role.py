"""HA role-aware serving (HA part 2): active admits work, standby refuses.

Two server instances of one logical Host share an ownership-lease store. The one
that wins the lease is ACTIVE (ready, admits /invoke); the other is STANDBY (not
ready, refuses /invoke with server_not_active). Single-instance is always active.
chp-core-only.
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


def _make(tmp_path, shared_store, name, *, ha=True):
    host = LocalCapabilityHost("logical-host",
                               store=SQLiteEvidenceStore(str(tmp_path / f"{name}-h.sqlite")))
    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="e"),
                  lambda _c, p: {"echo": p.get("t")})
    s = Server(ServerConfig(port=0, profile="host", store=shared_store, host_id="logical-host",
                            ha_enabled=ha, ha_lease_ttl_s=30))
    s.attach(GovernedHostPort(host))
    return s


def _invoke(server):
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}/invoke",
                                 data=json.dumps({"capability_id": "demo.echo",
                                                  "payload": {"t": "x"}}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _ready(server):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/ready") as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_ha_active_and_standby_roles_and_admission(tmp_path):
    shared = str(tmp_path / "lease.sqlite")
    a = _make(tmp_path, shared, "a")
    a.start()
    try:
        # A won the lease: active, ready, admits work.
        assert a.role() == "active"
        code, body = _ready(a)
        assert code == 200 and body["ready"] is True and body["role"] == "active"
        assert _invoke(a)["outcome"] == "success"

        b = _make(tmp_path, shared, "b")
        b.start()
        try:
            # B could not take the live lease: standby, not ready.
            assert b.role() == "standby"
            code, body = _ready(b)
            assert code == 503 and body["ready"] is False and body["role"] == "standby"
            # B refuses consequential work with server_not_active.
            with pytest.raises(urllib.error.HTTPError) as e:
                _invoke(b)
            assert e.value.code == 503
            assert json.loads(e.value.read())["error"]["code"] == "server_not_active"
            # A is unaffected — still active and serving.
            assert _invoke(a)["outcome"] == "success"
        finally:
            b.stop()
    finally:
        a.stop()


def test_single_instance_is_always_active(tmp_path):
    s = _make(tmp_path, str(tmp_path / "solo.sqlite"), "solo", ha=False)
    s.start()
    try:
        assert s.role() == "active"
        code, body = _ready(s)
        assert code == 200 and body["role"] == "active"
        assert _invoke(s)["outcome"] == "success"
    finally:
        s.stop()
