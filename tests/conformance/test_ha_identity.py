"""HA identity + abstention conformance (HA-006/007).

The base server is single-instance: its instance identity is distinguishable
from the Host identity it serves (HA-006), and it truthfully does NOT claim any
HA/multi-instance profile before ownership-safety tests exist (HA-007). Genuine
multi-instance ownership (HA-003/004/005) is deferred by design — DEC-SRV-008.
chp-core-only.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from chp_core import CapabilityDescriptor, LocalCapabilityHost, SQLiteEvidenceStore
from chp_server import PROFILES, Server, ServerConfig


class GovernedHostPort:
    roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
    source = "local"

    def __init__(self, host):
        self.host = host

    def health(self):
        return "ready"


@pytest.fixture()
def rig(tmp_path):
    host = LocalCapabilityHost("served-host-xyz",
                               store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="e"),
                  lambda _c, p: {"echo": p.get("text")})
    s = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.start()
    yield s
    s.stop()


def _get(server, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}{path}") as r:
        return json.loads(r.read())


def test_ha_006_instance_identity_distinct_from_host(rig):
    # The server INSTANCE has its own identity ("srv_..."), distinct from the
    # Host it serves ("served-host-xyz") — a prerequisite for HA diagnostics.
    describe = _get(rig, "/server")
    instance_id = describe["instance"]["id"]
    served_host_id = _get(rig, "/health")["host_id"]
    assert instance_id.startswith("srv")
    assert instance_id != served_host_id
    assert instance_id != describe["config"]["host_id"]


def test_ha_007_base_server_does_not_claim_ha(rig):
    # Truthful abstention: no HA/multi-instance profile is active, and describe
    # carries no active-HA claim, because ownership-safety tests do not yet exist.
    describe = _get(rig, "/server")
    assert describe["profile"] == "host"
    assert "ha_mode" not in describe  # nothing advertises HA
    ha_ish = [p for p in PROFILES if "ha" in p.lower() or "multi" in p.lower()]
    assert ha_ish == []  # no HA profile is even offered
