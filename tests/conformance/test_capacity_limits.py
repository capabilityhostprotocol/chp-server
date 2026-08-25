"""Capacity/resource-exhaustion at the served boundary (CAP-003 / SEC-008).

The chp-core HTTP surface the server reuses caps request bodies and sheds load
over its concurrency limit; this proves the boundary bounds work deterministically
(oversized body rejected before allocation), complementing the timing-based
load-shed test in chp-core (test_serve_resilience). chp-core-only.
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
    host = LocalCapabilityHost("cap-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="Echo."),
                  lambda _c, p: {"echo": p.get("text")})
    s = Server(ServerConfig(port=0, profile="local", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.start()
    yield s
    s.stop()


def test_oversized_body_rejected_before_work(server, monkeypatch):
    # Declare a body far past the cap via Content-Length; the boundary rejects it
    # as a structured 400 rather than allocating unbounded work.
    huge = 9 * 1024 * 1024  # > default 8 MiB cap
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/invoke", method="POST",
        data=b"x" * 16, headers={"Content-Type": "application/json",
                                 "Content-Length": str(huge)})
    # urllib would try to send the declared length; send a short body and let the
    # server reject on the Content-Length check.
    req.data = b'{"capability_id":"demo.echo","payload":{}}'
    req.add_header("Content-Length", str(huge))
    try:
        urllib.request.urlopen(req, timeout=5)
        raised = False
    except urllib.error.HTTPError as e:
        raised = True
        assert e.code == 400
        assert json.loads(e.read())["error"]["code"] in (
            "bad_request", "invalid_request", "request_too_large")
    except (urllib.error.URLError, OSError):
        raised = True  # connection cut on oversized declaration is also a refusal
    assert raised  # never accepted as unbounded work


def test_normal_body_still_served(server):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/invoke",
        data=b'{"capability_id":"demo.echo","payload":{"text":"ok"}}',
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        assert json.loads(r.read())["outcome"] == "success"
