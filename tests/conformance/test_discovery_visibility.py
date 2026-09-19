"""Discovery-visibility conformance (DISC-002, SEC-004) over the served surface.

Discovery enumeration is constrained by capability visibility policy: a verified
caller sees only the capabilities whose policy admits it. A restricted capability
is HIDDEN from callers outside its allowed_actors — enumeration is not a blanket
listing. chp-core-only.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from chp_core import CapabilityDescriptor, LocalCapabilityHost, SQLiteEvidenceStore
from chp_core.types import PolicyDescriptor
from chp_server import Server, ServerConfig


class GovernedHostPort:
    roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
    source = "local"

    def __init__(self, host):
        self.host = host

    def health(self):
        return "ready"


@pytest.fixture()
def server(tmp_path, monkeypatch):
    # Two named callers; the transport binds each key to its verified caller name.
    monkeypatch.setenv("CHP_HOST_API_KEYS", "alice:key-a,bob:key-b")
    host = LocalCapabilityHost("vis-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    host.register(CapabilityDescriptor(id="demo.open", version="1.0.0", description="open"),
                  lambda _c, p: {"ok": True})
    # Restricted: visible only to alice (policy.allowed_actors).
    host.register(
        CapabilityDescriptor(id="demo.restricted", version="1.0.0", description="restricted",
                             policy=PolicyDescriptor(allowed_actors=["alice"])),
        lambda _c, p: {"ok": True})
    s = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.start()
    yield s
    s.stop()


def _host_caps(server, key):
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}/host",
                                 headers={"X-CHP-Key": key})
    with urllib.request.urlopen(req) as r:
        return {c["id"] for c in json.loads(r.read())["capabilities"]}


def test_disc_002_sec_004_enumeration_constrained_by_visibility(server):
    # alice is in the restricted cap's allowed_actors -> sees both.
    alice = _host_caps(server, "key-a")
    assert "demo.open" in alice and "demo.restricted" in alice
    # bob is NOT -> the restricted capability is HIDDEN from bob's enumeration,
    # while the open one stays visible. Discovery is visibility-policy-controlled.
    bob = _host_caps(server, "key-b")
    assert "demo.open" in bob
    assert "demo.restricted" not in bob
