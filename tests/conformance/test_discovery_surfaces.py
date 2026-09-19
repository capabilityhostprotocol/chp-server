"""Distinct discovery surfaces conformance (DISC-001).

capabilities.txt, .well-known/chp, and live CHP discovery (/host) are three
DISTINCT surfaces with defined purposes: /host is the authoritative, access-
controlled live-discovery surface; .well-known/chp is a public bootstrap that
POINTS to the surfaces; capabilities.txt is a public, non-authoritative hint.
The public hint respects visibility policy (never leaks a restricted capability).
chp-core-only.
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
    monkeypatch.setenv("CHP_HOST_API_KEYS", "alice:key-a")
    host = LocalCapabilityHost("disc-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    host.register(CapabilityDescriptor(id="demo.open", version="1.0.0", description="open"),
                  lambda _c, p: {"ok": True})
    host.register(
        CapabilityDescriptor(id="demo.restricted", version="1.0.0", description="restricted",
                             policy=PolicyDescriptor(allowed_actors=["alice"])),
        lambda _c, p: {"ok": True})
    s = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.start()
    yield s
    s.stop()


def _get(server, path, key=None):
    headers = {"X-CHP-Key": key} if key else {}
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}", headers=headers)
    r = urllib.request.urlopen(req)
    return r, r.read()


def test_disc_001_well_known_bootstrap_is_a_distinct_pointer_surface(server):
    r, body = _get(server, "/.well-known/chp")
    assert r.headers.get("Content-Type", "").startswith("application/json")
    doc = json.loads(body)
    surfaces = doc["surfaces"]
    # It POINTS to the three distinct surfaces with their trust posture — it is not
    # itself the capability truth.
    assert surfaces["live_discovery"]["path"] == "/host"
    assert surfaces["live_discovery"]["authoritative"] is True
    assert surfaces["capabilities_hint"]["path"] == "/capabilities.txt"
    assert surfaces["capabilities_hint"]["authoritative"] is False
    assert "not an introduction authority" in doc["note"]


def test_disc_001_capabilities_txt_is_a_public_visibility_respecting_hint(server):
    r, body = _get(server, "/capabilities.txt")
    assert r.headers.get("Content-Type", "").startswith("text/plain")
    text = body.decode()
    # Public hint: the open capability is listed; the restricted one is NOT disclosed
    # (visibility policy applies to the public surface — no allowed_actors leak).
    assert "demo.open" in text
    assert "demo.restricted" not in text
    assert "non-authoritative" in text  # its purpose is declared in the surface itself


def test_disc_001_live_discovery_is_the_authoritative_distinct_surface(server):
    # /host is a DIFFERENT surface: authenticated, and to an authorized caller it
    # discloses the restricted capability that the public hint withholds.
    r, body = _get(server, "/host", key="key-a")
    ids = {c["id"] for c in json.loads(body)["capabilities"]}
    assert "demo.open" in ids and "demo.restricted" in ids   # authoritative, access-controlled
    # ...proving the public hint and the live surface are genuinely distinct.
    _, hint = _get(server, "/capabilities.txt")
    assert "demo.restricted" not in hint.decode()
