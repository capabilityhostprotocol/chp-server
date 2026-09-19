"""HA duplicate-effect prevention + split-brain fail-closed (HA-004, HA-005).

Concurrent ownership does NOT cause duplicate consequential effects: with two
instances of one logical Host sharing an ownership-lease store, the lease admits
exactly one ACTIVE instance and part 2's admission gate refuses the standby, so a
consequential capability executes on exactly one instance. A non-active instance
FAILS CLOSED for consequential execution (HA-005). chp-core-only.

Scope: the shared-store deployment model (one lease store = one ownership truth).
The fencing-epoch primitive (chp_server.ha.fence_ok) is the additional defense for a
partitioned/multi-store deployment; a consequential effect that already ran in a
briefly-deposed owner's handler is cooperative-cancellation territory (EFF-007), not
concurrent-ownership duplication.
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


def _make(tmp_path, shared_store, name, effects):
    host = LocalCapabilityHost("logical-host",
                               store=SQLiteEvidenceStore(str(tmp_path / f"{name}-h.sqlite")))

    def actuate(_c, p):
        effects.append(name)                       # the shared external consequential effect
        return {"actuated": True, "total": len(effects)}

    host.register(CapabilityDescriptor(id="demo.actuate", version="1.0.0", description="a"), actuate)
    s = Server(ServerConfig(port=0, profile="host", store=shared_store, host_id="logical-host",
                            ha_enabled=True, ha_lease_ttl_s=30))
    s.attach(GovernedHostPort(host))
    return s


def _actuate(server):
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}/invoke",
                                 data=json.dumps({"capability_id": "demo.actuate",
                                                  "payload": {}}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_ha_004_consequential_effect_runs_once_across_instances(tmp_path):
    shared = str(tmp_path / "lease.sqlite")
    effects: list[str] = []
    a = _make(tmp_path, shared, "a", effects)
    a.start()
    try:
        b = _make(tmp_path, shared, "b", effects)
        b.start()
        try:
            assert a.role() == "active" and b.role() == "standby"
            # The active instance performs the effect.
            assert _actuate(a)["outcome"] == "success"
            # The standby is asked to do the SAME consequential work and refuses — the
            # effect is NOT duplicated by the second owner.
            with pytest.raises(urllib.error.HTTPError) as e:
                _actuate(b)
            assert json.loads(e.value.read())["error"]["code"] == "server_not_active"
            # Exactly one consequential effect occurred, on the active instance only.
            assert effects == ["a"]
        finally:
            b.stop()
    finally:
        a.stop()


def test_ha_005_non_active_instance_fails_closed_for_consequential(tmp_path):
    # Split-brain / uncertain ownership fails CLOSED: an instance that is not the
    # confirmed active owner refuses consequential execution rather than proceeding.
    shared = str(tmp_path / "lease.sqlite")
    effects: list[str] = []
    a = _make(tmp_path, shared, "a", effects)
    a.start()
    try:
        b = _make(tmp_path, shared, "b", effects)
        b.start()
        try:
            assert b.role() == "standby"            # b never confirmed ownership
            with pytest.raises(urllib.error.HTTPError) as e:
                _actuate(b)
            assert e.value.code == 503
            assert json.loads(e.value.read())["error"]["code"] == "server_not_active"
            assert effects == []                    # b performed NO effect (fail closed)
        finally:
            b.stop()
    finally:
        a.stop()
