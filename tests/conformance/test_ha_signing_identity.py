"""One Host signing identity across HA instances (EVID-008).

HA instances of one logical Host preserve the ONE authoritative evidence-signing
identity (the Host key), while each keeps its own diagnostic instance identity
(HA-006). A verifier checks the Host identity; it never needs to trust an individual
instance id. chp-core-only.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from chp_core import CapabilityDescriptor, LocalCapabilityHost, SQLiteEvidenceStore
from chp_core.signing import generate_keypair, signing_available
from chp_server import Server, ServerConfig


class GovernedHostPort:
    roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
    source = "local"

    def __init__(self, host):
        self.host = host

    def health(self):
        return "ready"


@pytest.fixture()
def shared_host_key(tmp_path, monkeypatch):
    if not signing_available():
        pytest.skip("cryptography backend not available")
    key_dir = tmp_path / "hostkey"
    key_dir.mkdir()
    monkeypatch.setenv("CHP_KEY_DIR", str(key_dir))     # both instances resolve here
    return generate_keypair(str(key_dir)).key_id        # the one Host signing identity


def _make(tmp_path, name):
    host = LocalCapabilityHost("logical-host",
                               store=SQLiteEvidenceStore(str(tmp_path / f"{name}-h.sqlite")))
    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="e"),
                  lambda _c, p: {"ok": True})
    s = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / f"{name}-s.sqlite"),
                            host_id="logical-host"))
    s.attach(GovernedHostPort(host))
    return s


def _get(server, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}{path}") as r:
        return json.loads(r.read())


def test_evid_008_instances_share_one_signing_identity_distinct_instance_ids(shared_host_key,
                                                                             tmp_path):
    a = _make(tmp_path, "a")
    b = _make(tmp_path, "b")
    a.start()
    b.start()
    try:
        ida = _get(a, "/.well-known/chp-identity")
        idb = _get(b, "/.well-known/chp-identity")
        # ONE authoritative signing identity across both instances of the Host.
        assert ida["assurance"] == "signed" and idb["assurance"] == "signed"
        assert ida["key_id"] == idb["key_id"] == shared_host_key
        assert ida["public_key"] == idb["public_key"]
        # The self-attestation binds that key to the one host_id, on both instances.
        assert ida.get("host_identity") == idb.get("host_identity")

        # ...yet each instance keeps its OWN diagnostic instance identity (HA-006):
        # the signing identity is the Host's, never the instance's.
        inst_a = _get(a, "/server")["instance"]["id"]
        inst_b = _get(b, "/server")["instance"]["id"]
        assert inst_a != inst_b
        assert inst_a not in (ida["key_id"],) and inst_b not in (idb["key_id"],)
    finally:
        a.stop()
        b.stop()
