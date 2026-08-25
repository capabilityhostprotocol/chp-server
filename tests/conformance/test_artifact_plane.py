"""Artifact-plane conformance through the served surface: feature truth, wire
roundtrip, integrity refusal, unsupported-when-absent. chp-core-only."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from chp_core import LocalCapabilityHost, SQLiteEvidenceStore, artifact_id_for
from chp_server import LocalArtifactPort, Server, ServerConfig


class GovernedHostPort:
    roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
    source = "local"

    def __init__(self, host):
        self.host = host

    def health(self):
        return "ready"


@pytest.fixture()
def rig(tmp_path):
    host = LocalCapabilityHost("art-srv", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    s = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.attach(LocalArtifactPort(root=str(tmp_path / "artifacts")))
    s.start()
    yield s
    s.stop()


def test_artifact_transfer_feature_truth(rig, tmp_path):
    by_name = {f.feature: f.state for f in rig.features.snapshot(lifecycle=rig.state)}
    assert by_name["artifact.transfer"] == "ready"
    bare = Server(ServerConfig(port=0, store=str(tmp_path / "b.sqlite")))
    bare.start()
    try:
        states = {f.feature: f.state for f in bare.features.snapshot(lifecycle=bare.state)}
        assert states["artifact.transfer"] == "unsupported"
    finally:
        bare.stop()


def test_wire_roundtrip_and_integrity_through_server(rig):
    base = f"http://127.0.0.1:{rig.port}"
    req = urllib.request.Request(f"{base}/artifacts", data=b"conformance bytes",
                                 headers={"Content-Type": "application/octet-stream"})
    with urllib.request.urlopen(req) as r:
        ref = json.loads(r.read())
    assert ref["artifact_id"] == artifact_id_for(b"conformance bytes")
    with urllib.request.urlopen(f"{base}/artifacts/{ref['artifact_id']}") as r:
        assert r.read() == b"conformance bytes"
    # Tamper on disk -> the server REFUSES with an integrity conflict.
    store = rig.attachments.for_role("ArtifactPort").store
    (store.root / ref["artifact_id"].removeprefix("sha256:")).write_bytes(b"TAMPERED")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(f"{base}/artifacts/{ref['artifact_id']}")
    assert e.value.code == 409


def test_unsupported_without_artifact_port(tmp_path):
    host = LocalCapabilityHost("no-art", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    s = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(
                f"http://127.0.0.1:{s.port}/artifacts/{artifact_id_for(b'x')}")
        assert e.value.code == 404
        assert json.loads(e.value.read())["error"]["code"] == "artifact_plane_unsupported"
    finally:
        s.stop()
