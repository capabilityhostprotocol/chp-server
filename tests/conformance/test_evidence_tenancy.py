"""Evidence-query authorization respects the tenant/visibility boundary (EVID-007).

A caller may replay only evidence within its own boundary — the correlations whose
recorded principal (invocation subject/actor) is itself. Another tenant's evidence is
not disclosed (404, least-disclosure). With no authenticated caller (single-tenant /
open) replay is unscoped, today's behavior. chp-core-only.
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


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("CHP_HOST_API_KEYS", "alice:key-a,bob:key-b")
    host = LocalCapabilityHost("t-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="e"),
                  lambda _c, p: {"ok": True})
    s = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.start()
    yield s
    s.stop()


def _invoke(server, key, subject_id):
    body = {"capability_id": "demo.echo", "payload": {},
            "subject": {"id": subject_id, "type": "user"}}
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}/invoke",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "X-CHP-Key": key})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _replay(server, key, corr):
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}/replay/{corr}",
                                 headers={"X-CHP-Key": key})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_evid_007_caller_sees_only_its_own_evidence(server):
    corr_a = _invoke(server, "key-a", "alice")["correlation"]["correlation_id"]
    corr_b = _invoke(server, "key-b", "bob")["correlation"]["correlation_id"]

    # Each caller replays its OWN evidence.
    code, body = _replay(server, "key-a", corr_a)
    assert code == 200 and body["events"]
    code, body = _replay(server, "key-b", corr_b)
    assert code == 200 and body["events"]

    # Cross-tenant replay is refused — the other tenant's evidence is not disclosed.
    code, body = _replay(server, "key-b", corr_a)
    assert code == 404 and body["error"]["code"] == "evidence_not_visible"
    code, body = _replay(server, "key-a", corr_b)
    assert code == 404 and body["error"]["code"] == "evidence_not_visible"
