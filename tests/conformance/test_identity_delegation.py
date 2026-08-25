"""Identity + delegation conformance (ID-003/004/006/007) over the served surface.

Delegation via chp-core mandates narrows authority, never widens it, and the
server redacts secret material from its diagnostics and discovery. chp-core-only.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from chp_core import CapabilityDescriptor, LocalCapabilityHost, SQLiteEvidenceStore, signing
from chp_server import Server, ServerConfig


class GovernedHostPort:
    roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
    source = "local"

    def __init__(self, host):
        self.host = host

    def health(self):
        return "ready"


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv("CHP_HOST_API_KEYS", "steward:key-s:demo.*")
    host = LocalCapabilityHost("id-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    for cid in ("demo.echo", "demo.other"):
        host.register(CapabilityDescriptor(id=cid, version="1.0.0", description=cid),
                      lambda _c, p: {"echo": p.get("text")})
    s = Server(ServerConfig(port=0, profile="local", store=str(tmp_path / "s.sqlite"),
                            tls_keyfile="/secret/path/to/host.key"))  # a secret-ish field
    s.attach(GovernedHostPort(host))
    s.start()
    yield s, signing.generate_keypair(tmp_path / "k")
    s.stop()


def _post(server, path, body, key=None):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-CHP-Key"] = key
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}",
                                 data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _get(server, path, key=None):
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}",
                                 headers={"X-CHP-Key": key} if key else {})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_id_003_004_delegation_bounded_and_never_amplifies(rig):
    server, key = rig
    now = datetime.now(timezone.utc)
    iso = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # A mandate delegated to the verified caller, scoped to demo.echo ONLY.
    mandate = signing.build_mandate(
        "principal-root", key, delegate_id="steward", scope=["demo.echo"],
        valid_from=iso(now - timedelta(minutes=5)), valid_until=iso(now + timedelta(hours=1)),
        created_at=iso(now))
    # In-scope: the bounded delegation succeeds (ID-003, subject bound to the mandate).
    _, ok = _post(server, "/invoke",
                  {"capability_id": "demo.echo", "payload": {"text": "x"}, "mandate": mandate},
                  key="key-s")
    assert ok["outcome"] == "success"
    # Out-of-scope: the SAME mandate cannot reach demo.other — delegation narrows,
    # it does NOT amplify authority (ID-004).
    _, denied = _post(server, "/invoke",
                      {"capability_id": "demo.other", "payload": {"text": "x"},
                       "mandate": mandate}, key="key-s")
    assert denied["outcome"] == "denied" and denied["denial"]["code"] == "policy_blocked"


def test_id_006_007_secrets_redacted_in_diagnostics_and_discovery(rig):
    server, _ = rig
    describe = _get(server, "/server", key="key-s")
    # ID-007: server diagnostics redact secret/credential material.
    assert describe["config"]["tls_keyfile"] == "<redacted>"
    # ID-006: no raw secret value appears anywhere in the describe or the host
    # discovery surface — secrets are referenced, never embedded.
    assert "/secret/path/to/host.key" not in json.dumps(describe)
    host_desc = _get(server, "/host", key="key-s")
    assert "/secret/path/to/host.key" not in json.dumps(host_desc)
