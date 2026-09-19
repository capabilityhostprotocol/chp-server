"""Canonical-operation conformance (OPS-001, OPS-002).

Canonical CHP operations are defined independently from transport endpoints, and
every projection routes through the SAME canonical operation. Proven by invoking
one capability two ways — over the HTTP wire and in-process through the host —
and showing the results are semantically equivalent and both flow through the one
evidence-recording gate pipeline. chp-core-only.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import urllib.request

import pytest

from chp_core import (CapabilityDescriptor, InvocationEnvelope, LocalCapabilityHost,
                      SQLiteEvidenceStore)
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
    host = LocalCapabilityHost("ops-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="e"),
                  lambda _c, p: {"echo": p.get("text")})
    server = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / "s.sqlite")))
    server.attach(GovernedHostPort(host))
    server.start()
    yield server, host
    server.stop()


def _http_invoke(server, payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/invoke",
        data=json.dumps({"capability_id": "demo.echo", "payload": payload}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _local_invoke(host, payload):
    return asyncio.run(host.ainvoke_envelope(InvocationEnvelope(
        capability_id="demo.echo", payload=payload, invocation_id="loc-1")))


def test_ops_001_002_http_and_in_process_route_through_one_canonical_operation(rig):
    server, host = rig
    payload = {"text": "hi"}
    http = _http_invoke(server, payload)
    loc = _local_invoke(host, payload)

    # OPS-002: the two transport projections yield the SAME canonical outcome and
    # output — the HTTP wire is a projection of the same InvocationResult the
    # in-process host produces, not a parallel code path.
    assert http["outcome"] == loc.outcome == "success"
    assert http["success"] == loc.success is True
    assert http["data"] == loc.data == {"echo": "hi"}
    assert http["capability_id"] == loc.capability_id == "demo.echo"
    assert http["capability_version"] == loc.capability_version == "1.0.0"

    # OPS-001: the canonical operation is defined independently of the endpoint —
    # both routes record evidence through the one gate pipeline (distinct per-
    # invocation identity, same governed operation).
    assert http["evidence_ids"] and loc.evidence_ids
    assert http["correlation"]["correlation_id"] != loc.correlation.correlation_id  # per-invocation

    # The HTTP invocation's evidence is queryable via the canonical replay surface,
    # confirming the wire projection went through the same evidence path.
    corr = http["correlation"]["correlation_id"]
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/replay/{corr}") as r:
        assert json.loads(r.read())
