"""Observability-metrics conformance (OBS-002).

The server exposes lifecycle, feature-health, and attachment-health as Prometheus
series on /metrics (chp-core already exposes request latency + evidence integrity).
The series are LIVE — computed from the one FeatureRegistry/AttachmentRegistry — so
they track degradation rather than a boot-time snapshot. chp-core-only.
"""

from __future__ import annotations

import urllib.request

import pytest

from chp_server import Server, ServerConfig


class ToggleHostPort:
    roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
    source = "local"

    def __init__(self):
        self._health = "ready"

    def health(self):
        return self._health


@pytest.fixture()
def server(tmp_path):
    s = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / "s.sqlite")))
    port = ToggleHostPort()
    s.attach(port)
    s.start()
    yield s, port
    s.stop()


def _metrics(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/metrics") as r:
        return r.headers.get("Content-Type", ""), r.read().decode()


def test_obs_002_metrics_expose_lifecycle_feature_and_attachment_health(server):
    srv, port = server
    ctype, body = _metrics(srv)
    assert ctype.startswith("text/plain")
    # Lifecycle + feature health + attachment-role health are all present.
    assert "chp_server_ready 1" in body
    assert 'chp_server_feature_ready{feature="capability.discovery"' in body
    assert 'chp_server_attachment_role_ready{role="HostPort"' in body
    # A ready HostPort reads 1.
    assert 'chp_server_attachment_role_ready{role="HostPort",state="ready"} 1' in body


def test_obs_002_metrics_are_live_and_track_degradation(server):
    srv, port = server
    port._health = "degraded"                      # the attachment degrades at runtime
    _, body = _metrics(srv)
    # The live series reflect the degradation, not a boot-time snapshot.
    assert 'chp_server_attachment_role_ready{role="HostPort",state="degraded"} 0' in body
    assert "chp_server_ready 0" in body            # a degraded required role -> not ready
    # A feature that depends on the degraded role reports not-ready too.
    assert 'chp_server_feature_ready{feature="capability.discovery",state="degraded"} 0' in body
