"""Standalone-profile conformance (doc 12 §5): discover/resolve/admit/execute
locally, with Platform absent by construction. chp-core-only — runs in the
clean venv where optional CHP packages are verifiably missing.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from chp_core import CapabilityDescriptor, LocalCapabilityHost, SQLiteEvidenceStore, signing
from chp_server import LocalStandalonePorts, Server, ServerConfig


class GovernedHostPort:
    roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
    source = "local"

    def __init__(self, host):
        self.host = host

    def health(self):
        return "ready"


def _governed_host(tmp_path):
    host = LocalCapabilityHost(
        "standalone-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))

    async def echo(_ctx, payload):
        return {"echo": payload.get("text")}

    host.register(
        CapabilityDescriptor(id="demo.echo", version="1.0.0", description="Echo.",
                             category="demo"), echo)
    return host


@pytest.fixture()
def rig(tmp_path):
    server = Server(ServerConfig(port=0, profile="standalone",
                                 store=str(tmp_path / "s.sqlite")))
    # Deliberately attach the dependent ports FIRST: start_all must order by
    # declared role dependencies (ATT-003), not by attach order.
    server.attach(LocalStandalonePorts())
    server.attach(GovernedHostPort(_governed_host(tmp_path)))
    server.start()
    yield server
    server.stop()


def test_standalone_profile_ready_offline(rig):
    r = rig.ready()
    assert r["ready"] is True and r["profile"] == "standalone"
    by_name = {f.feature: f.state for f in rig.features.snapshot(lifecycle=rig.state)}
    assert by_name["capability.discovery"] == "ready"
    assert by_name["capability.resolve"] == "ready"
    assert by_name["invocation.local"] == "ready"
    # Platform stays truthfully out of the picture — no platform-backed source.
    assert all(f.source != "platform" for f in rig.features.snapshot(lifecycle=rig.state))


def test_local_resolution_and_supply(rig):
    ports = rig.attachments.for_role("ResolutionPort")
    hits = ports.resolve({"capability_id": "demo.echo"})
    assert [c["id"] for c in hits] == ["demo.echo"]
    assert ports.resolve({"category": "demo"})[0]["id"] == "demo.echo"
    assert ports.resolve({"capability_id": "no.such"}) == []
    supply = rig.attachments.for_role("SupplyPort").supply()
    assert supply["freshness"] == "live"
    assert {"demo.echo"} == {c["id"] for c in supply["capabilities"]}


def test_resolution_confers_no_execution_authority(rig, tmp_path):
    # Doc 35 §7 / the standing invariant: resolver output is never execution
    # authority. A resolved capability invoked under an out-of-scope mandate
    # STILL denies at the mandate gate.
    ports = rig.attachments.for_role("ResolutionPort")
    assert ports.resolve({"capability_id": "demo.echo"})  # resolution succeeds
    key = signing.generate_keypair(tmp_path / "k")
    now = datetime.now(timezone.utc)
    iso = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    mandate = signing.build_mandate(
        "principal-a", key, delegate_id="d", scope=["other.capability"],
        valid_from=iso(now - timedelta(minutes=5)), valid_until=iso(now + timedelta(hours=1)),
        created_at=iso(now))
    req = urllib.request.Request(
        f"http://127.0.0.1:{rig.port}/invoke",
        data=json.dumps({"capability_id": "demo.echo", "payload": {"text": "x"},
                         "mandate": mandate}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        out = json.loads(r.read())
    assert out["outcome"] == "denied" and out["denial"]["code"] == "policy_blocked"


def test_standalone_fails_closed_without_local_ports(tmp_path):
    s = Server(ServerConfig(port=0, profile="standalone", store=str(tmp_path / "e.sqlite")))
    s.attach(GovernedHostPort(_governed_host(tmp_path)))
    with pytest.raises(RuntimeError, match="fail-closed"):
        s.start()


def test_unsatisfiable_dependency_is_an_explicit_error(tmp_path):
    s = Server(ServerConfig(port=0, store=str(tmp_path / "e.sqlite")))
    s.attach(LocalStandalonePorts())  # requires HostPort; none attached
    with pytest.raises(RuntimeError, match="unsatisfiable"):
        s.start()
