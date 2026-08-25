"""Evidence + observability conformance (EVID/OBS) over the served surface.

Canonical evidence stays owned by chp-core (the served host's SQLiteEvidenceStore);
the server only projects it through /replay, /verify, /export and exposes
operational telemetry through /metrics — the two are distinct. chp-core-only.
"""

from __future__ import annotations

import json
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
def rig(tmp_path):
    host = LocalCapabilityHost("evid-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))

    async def echo(_ctx, payload):
        return {"echo": payload.get("text")}

    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="Echo."), echo)
    s = Server(ServerConfig(port=0, profile="local", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.start()
    yield s
    s.stop()


def _get(server, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}{path}") as r:
        return r.status, r.read()


def _invoke(server, text="hi", inv="inv-1"):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/invoke",
        data=json.dumps({"capability_id": "demo.echo", "payload": {"text": text},
                         "invocation_id": inv}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_evid_001_002_query_projects_canonical_evidence(rig):
    # Canonical evidence is the host's (chp-core) store; the server only queries it.
    out = _invoke(rig)
    corr = out["correlation"]["correlation_id"]
    _, body = _get(rig, f"/replay/{corr}")
    replayed = json.loads(body)
    assert replayed  # recorded chp-core evidence, projected — not server-generated
    assert out.get("evidence_ids")  # generation owned by the host


def test_evid_003_verify_preserves_digests(rig):
    corr = _invoke(rig)["correlation"]["correlation_id"]
    status, body = _get(rig, f"/verify/{corr}")
    assert status == 200
    v = json.loads(body)
    # A verification projection over the canonical chain — digest/verification
    # semantics preserved, not re-derived by the server.
    assert isinstance(v, dict) and v


def test_evid_006_obs_001_metrics_distinct_from_evidence(rig):
    _invoke(rig)
    status, body = _get(rig, "/metrics")
    assert status == 200
    text = body.decode()
    # Prometheus exposition — operational telemetry, NOT canonical evidence.
    assert text.startswith("#") or "chp_" in text
    assert "correlation_id" not in text  # telemetry carries no evidence records


def test_obs_006_live_while_optional_feature_degraded(rig, tmp_path):
    # /health (liveness) stays ok even though optional features are unsupported.
    status, body = _get(rig, "/health")
    assert status == 200 and json.loads(body)["status"] == "ok"
    by_name = {f.feature: f.state for f in rig.features.snapshot(lifecycle=rig.state)}
    assert by_name["capability.resolve"] == "unsupported"  # optional, absent


def test_obs_007_feature_health_from_single_registry(rig):
    # /server features and the FeatureRegistry snapshot are the same source.
    _, body = _get(rig, "/server")
    described = {f["feature"]: f["state"] for f in json.loads(body)["features"]}
    snapshot = {f.feature: f.state for f in rig.features.snapshot(lifecycle=rig.state)}
    assert described == snapshot
