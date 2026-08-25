"""SEC hard-half conformance (SEC-002/007/009) over the served surface.

Confused-deputy resistance and admin-plane isolation are chp-core auth/mandate
semantics the server preserves: the verified caller is bound as subject and a
mandate's delegate is checked against it (a caller can't wield another
principal's authority), and the client wire exposes no admin mutation.
chp-core-only.
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
    # Named+scoped keys so the handler binds a verified caller identity.
    monkeypatch.setenv("CHP_HOST_API_KEYS", "team-a:key-a:demo.*,team-b:key-b:demo.*")
    host = LocalCapabilityHost("sec-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="e"),
                  lambda _c, p: {"echo": p.get("text")})
    s = Server(ServerConfig(port=0, profile="local", store=str(tmp_path / "s.sqlite")))
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


def test_sec_002_caller_cannot_wield_another_principals_mandate(rig):
    server, key = rig
    now = datetime.now(timezone.utc)
    iso = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # A mandate delegated to team-b, presented by the verified caller team-a.
    mandate = signing.build_mandate(
        "principal", key, delegate_id="team-b", scope=["demo.echo"],
        valid_from=iso(now - timedelta(minutes=5)), valid_until=iso(now + timedelta(hours=1)),
        created_at=iso(now))
    status, out = _post(server, "/invoke",
                        {"capability_id": "demo.echo", "payload": {"text": "x"},
                         "mandate": mandate}, key="key-a")
    # Authority substitution is refused — the mandate's delegate binding does not
    # match the verified caller, so admission denies it (confused-deputy resisted).
    assert status == 200 and out["outcome"] == "denied"
    assert out["denial"]["code"] == "mandate_invalid"


def test_sec_007_admin_endpoints_not_on_client_wire(rig):
    server, _ = rig
    # The served wire has no attach/detach/introduce mutation — administrative
    # operations are config/process-plane only, never client-reachable.
    for path in ("/attachments", "/introduce", "/attach", "/admin/reload"):
        status, out = _post(server, path, {}, key="key-a")
        assert status == 404
        assert out["error"]["code"] in ("not_found", "unknown_route")


def test_sec_009_expired_authority_not_extended(rig):
    server, key = rig
    now = datetime.now(timezone.utc)
    iso = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    expired = signing.build_mandate(
        "principal", key, delegate_id="team-a", scope=["demo.echo"],
        valid_from=iso(now - timedelta(hours=2)), valid_until=iso(now - timedelta(minutes=30)),
        created_at=iso(now - timedelta(hours=2)))
    status, out = _post(server, "/invoke",
                        {"capability_id": "demo.echo", "payload": {"text": "x"},
                         "mandate": expired}, key="key-a")
    # An expired mandate confers no authority — time cannot extend it.
    assert out["outcome"] == "denied" and out["denial"]["code"] == "mandate_invalid"
