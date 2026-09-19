"""Absolute-deadline conformance over the served surface (CAP-005, CAP-006; proposal 0052).

A server rejects work whose absolute deadline has passed (CAP-006) before any effect,
and an absolute deadline propagates to sub-invocations unchanged (CAP-005). chp-core-only.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

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


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


@pytest.fixture()
def server(tmp_path):
    host = LocalCapabilityHost("dl-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="e"),
                  lambda ctx, p: {"saw_deadline": ctx.envelope.deadline})

    async def parent(ctx, p):
        child = await ctx.ainvoke("demo.echo", {})
        return {"child_outcome": child.outcome,
                "child_saw": child.data.get("saw_deadline") if child.data else None}

    host.register(CapabilityDescriptor(id="demo.parent", version="1.0.0", description="p"), parent)
    s = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.start()
    yield s
    s.stop()


def _invoke(server, cap, deadline=None):
    body = {"capability_id": cap, "payload": {}}
    if deadline:
        body["deadline"] = deadline
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}/invoke",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_cap_006_expired_deadline_denied_before_work(server):
    past = _iso(datetime.now(timezone.utc) - timedelta(minutes=5))
    out = _invoke(server, "demo.echo", deadline=past)
    assert out["outcome"] == "denied"
    assert out["denial"]["code"] == "deadline_exceeded"
    assert out["denial"]["retryable"] is False
    assert not out.get("data")                      # no effect ran


def test_cap_006_live_deadline_runs(server):
    future = _iso(datetime.now(timezone.utc) + timedelta(minutes=5))
    out = _invoke(server, "demo.echo", deadline=future)
    assert out["outcome"] == "success" and out["data"]["saw_deadline"] == future


def test_deadline_absent_is_unchanged(server):
    assert _invoke(server, "demo.echo")["outcome"] == "success"


def test_cap_005_deadline_propagates_to_sub_invocation(server):
    # An absolute deadline set on the parent invocation is inherited, unchanged, by the
    # governed sub-invocation — one end-to-end budget across the hop, never re-based.
    future = _iso(datetime.now(timezone.utc) + timedelta(minutes=5))
    out = _invoke(server, "demo.parent", deadline=future)
    assert out["outcome"] == "success"
    assert out["data"]["child_outcome"] == "success"
    assert out["data"]["child_saw"] == future        # child saw the parent's exact deadline


def test_cap_006_malformed_deadline_rejected(server):
    # A malformed deadline is refused at the trust boundary (400), not silently ignored.
    with pytest.raises(urllib.error.HTTPError) as e:
        _invoke(server, "demo.echo", deadline="not-a-timestamp")
    assert e.value.code == 400
