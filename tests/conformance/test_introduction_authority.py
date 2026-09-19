"""Introduction-authority conformance (INTRO-039, INTRO-040) over the served surface.

Capability-source introduction is an ADMINISTRATION-plane operation (the
IntroductionCoordinator API, doc 77 §6) — it is NOT a governed capability on the
invocation wire. So ordinary discovery/invocation authority cannot perform, and
does not imply, authority to introduce or mutate server capability state.
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


@pytest.fixture()
def server(tmp_path):
    host = LocalCapabilityHost("intro-authz-host",
                               store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="e"),
                  lambda _c, p: {"echo": p.get("text")})
    s = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.start()
    yield s
    s.stop()


def _catalog(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/host") as r:
        return {c["id"] for c in json.loads(r.read())["capabilities"]}


def _invoke(server, cap_id):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/invoke",
        data=json.dumps({"capability_id": cap_id, "payload": {}}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


# The source-lifecycle operations, none of which may be an invocation-wire capability.
_INTRODUCTION_OPS = ("attach", "detach", "refresh", "quarantine", "activate", "retire", "introduce")


def test_intro_039_040_introduction_is_not_on_the_invocation_wire(server):
    # INTRO-040: ordinary discovery does not surface any capability that introduces or
    # mutates source state — the catalog is only the host's own capabilities.
    catalog = _catalog(server)
    for cid in catalog:
        assert not any(op in cid.lower() for op in _INTRODUCTION_OPS), cid

    # INTRO-039/040: invoking an introduction-shaped id is a PROCESSED capability_not_found
    # denial — it neither mutates source state nor is admitted. Ordinary invocation
    # authority confers no introduction authority; introduction requires the separate
    # administration plane (the IntroductionCoordinator), not the invoke wire.
    out = _invoke(server, "server.sources.activate")
    assert out["outcome"] == "denied"
    assert out["denial"]["code"] == "capability_not_found"
    # ...and the host catalog is unchanged (nothing was introduced).
    assert _catalog(server) == catalog


def test_intro_039_coordinator_is_a_distinct_admin_plane_api(server):
    # INTRO-039: the source-lifecycle operations live on the IntroductionCoordinator
    # (admin/config plane), a distinct object from the served invocation surface — not
    # reachable, and not implied, through capability invocation.
    from chp_server.introduction import IntroductionCoordinator

    for op in ("stage", "activate", "detach"):
        assert callable(getattr(IntroductionCoordinator, op, None)), op
    # The invocation handler exposes no such entry point (they are not capabilities).
    assert "server.sources.activate" not in _catalog(server)
