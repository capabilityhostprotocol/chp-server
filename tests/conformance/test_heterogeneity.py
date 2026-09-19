"""Heterogeneous-capability conformance (HET-001..005).

The governed pipeline is executor-kind agnostic: software, human, and physical/
machine capabilities are admitted, evidenced, and made idempotent through the SAME
gates — the server makes no software-only assumption. A reference pressure suite
must span all three kinds. chp-core-only.

- software: a normal computation.
- human: long-running work that returns an INDETERMINATE outcome (the reviewer has
  not responded) and is queryable later without a continuously-connected client.
- physical: a consequential effect that must preserve admission, idempotency
  (same invocation_id never re-actuates), and evidence.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from chp_core import (CapabilityDescriptor, IndeterminateExecution, LocalCapabilityHost,
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
    host = LocalCapabilityHost("het-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    actuations: list[str] = []  # the physical side-effect ledger

    host.register(CapabilityDescriptor(id="software.compute", version="1.0.0", description="s"),
                  lambda _c, p: {"sum": p.get("a", 0) + p.get("b", 0)})

    def human_review(_c, p):
        raise IndeterminateExecution("awaiting human reviewer")  # long-running human work

    host.register(CapabilityDescriptor(id="human.review", version="1.0.0", description="h"),
                  human_review)

    def physical_actuate(_c, p):
        actuations.append(p.get("target"))  # the consequential physical effect
        return {"actuated": p.get("target"), "count": len(actuations)}

    host.register(CapabilityDescriptor(id="physical.actuate", version="1.0.0", description="p"),
                  physical_actuate)

    s = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.start()
    yield s, actuations
    s.stop()


def _invoke(server, cap, payload=None, invocation_id=None):
    body = {"capability_id": cap, "payload": payload or {}}
    if invocation_id:
        body["invocation_id"] = invocation_id
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}/invoke",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _get(server, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}{path}") as r:
        return json.loads(r.read())


def test_het_001_005_pressure_spans_software_human_physical(rig):
    server, _ = rig
    # HET-001/005: all three capability KINDS are admitted through the one pipeline.
    soft = _invoke(server, "software.compute", {"a": 2, "b": 3})
    assert soft["outcome"] == "success" and soft["data"]["sum"] == 5
    human = _invoke(server, "human.review", {"doc": "x"})
    assert human["outcome"] == "indeterminate"          # long-running human work
    phys = _invoke(server, "physical.actuate", {"target": "valve-1"})
    assert phys["outcome"] == "success" and phys["data"]["actuated"] == "valve-1"
    # Every kind produced evidence through the same governed path.
    for r in (soft, human, phys):
        assert r["evidence_ids"]


def test_het_003_physical_effect_preserves_admission_idempotency_evidence(rig):
    server, actuations = rig
    first = _invoke(server, "physical.actuate", {"target": "valve-9"}, invocation_id="phys-1")
    assert first["outcome"] == "success"
    assert actuations == ["valve-9"]                    # the effect happened exactly once
    # Same invocation_id: idempotent replay — the physical effect is NOT repeated and
    # the recorded result is returned (no double actuation, admission preserved).
    again = _invoke(server, "physical.actuate", {"target": "valve-9"}, invocation_id="phys-1")
    assert actuations == ["valve-9"]                    # STILL once
    assert again["data"] == first["data"]
    # Evidence is queryable via the canonical replay surface.
    corr = first["correlation"]["correlation_id"]
    assert _get(server, f"/replay/{corr}")


def test_het_002_long_running_human_work_needs_no_continuous_client(rig):
    server, _ = rig
    out = _invoke(server, "human.review", {"doc": "y"}, invocation_id="human-1")
    assert out["outcome"] == "indeterminate" and out["success"] is False
    corr = out["correlation"]["correlation_id"]
    # The caller can disconnect; the pending human work is readable from evidence
    # afterwards — no continuously-connected client is required to represent it.
    assert _get(server, f"/replay/{corr}")


def test_het_004_discovery_does_not_assume_probeable_availability(rig):
    server, _ = rig
    # The human/physical capabilities are DISCOVERABLE even though their providers
    # (a human reviewer, a physical actuator) cannot be liveness-probed — discovery
    # is a catalog of what the host governs, not a probe of provider reachability.
    caps = {c["id"] for c in _get(server, "/host")["capabilities"]}
    assert {"software.compute", "human.review", "physical.actuate"} <= caps
