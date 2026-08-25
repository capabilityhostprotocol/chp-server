"""ExistingHostPort + Server.serving() — serve a pre-built governed host.

The host-vs-server seam: an embedder builds and owns its governed host; the
Server projects it (/server, /ready, feature truth, drain) without rebuilding
or mutating it. chp-core-only.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from chp_core import CapabilityDescriptor, LocalCapabilityHost, SQLiteEvidenceStore
from chp_server import ExistingHostPort, Server, ServerConfig


def _prebuilt_host(tmp_path):
    host = LocalCapabilityHost("embedder-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    host.register(CapabilityDescriptor(id="node.ping", version="1.0.0", description="Ping."),
                  lambda _c, p: {"pong": p.get("text")})
    return host


def _get(server, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}{path}") as r:
        return json.loads(r.read())


def test_serving_projects_the_prebuilt_host(tmp_path):
    host = _prebuilt_host(tmp_path)
    server = Server.serving(host, profile="host", port=0)
    server.start()
    try:
        # The server serves the embedder's host verbatim — same host_id, same caps.
        assert _get(server, "/health")["host_id"] == "embedder-host"
        assert _get(server, "/server")["config"]["host_id"] == "embedder-host"
        caps = [c["id"] for c in _get(server, "/host")["capabilities"]]
        assert caps == ["node.ping"]
        # ...and it adds the server surface the bare host lacks.
        assert server.ready()["ready"] is True and server.ready()["profile"] == "host"
        by = {f.feature: f.state for f in server.features.snapshot(lifecycle=server.state)}
        assert by["invocation.local"] == "ready"
        # A governed invocation runs through the SAME host (identity preserved).
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/invoke",
            data=json.dumps({"capability_id": "node.ping", "payload": {"text": "hi"}}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            out = json.loads(r.read())
        assert out["outcome"] == "success" and out["data"]["pong"] == "hi"
    finally:
        server.stop()


def test_stop_does_not_close_the_embedders_host(tmp_path):
    host = _prebuilt_host(tmp_path)
    server = Server.serving(host, port=0)
    server.start()
    server.stop()
    # The host is the embedder's — still usable after the server stops.
    import asyncio
    from chp_core import InvocationEnvelope
    r = asyncio.run(host.ainvoke_envelope(InvocationEnvelope(
        capability_id="node.ping", payload={"text": "still-alive"})))
    assert r.outcome == "success"


def test_serving_builds_no_cwd_store(tmp_path, monkeypatch):
    # Regression (rad:f061723): an embedded node agent runs from a read-only CWD.
    # serving() must never build the fallback _backing_host's store there — the
    # real host owns the evidence. Caught live by the m1-a canary (OSError EROFS).
    import os
    workdir = tmp_path / "ro-cwd"; workdir.mkdir()
    monkeypatch.chdir(workdir)
    host = _prebuilt_host(tmp_path)
    server = Server.serving(host, profile="edge", port=0)
    server.start()
    try:
        assert server.ready()["ready"] is True
        assert not (workdir / ".chp").exists()  # no store written to CWD
    finally:
        server.stop()


def test_existing_host_port_rejects_non_host():
    with pytest.raises(ValueError):
        ExistingHostPort(None)
    port = ExistingHostPort(object())
    with pytest.raises(ValueError):
        port.validate()  # not a governed CHP host
