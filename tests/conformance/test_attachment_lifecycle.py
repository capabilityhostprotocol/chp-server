"""Attachment-lifecycle + role-isolation conformance (ATT-002, DISC-008, SEC-010).

The attachment/port layer (docs 35/41/42) is where optional capability providers
plug in. Three properties are proven here over the served surface:

- ATT-002: the lifecycle DEFINES every phase — discovery/load, validation,
  initialization, readiness, degradation, drain, and stop — each observable.
- DISC-008: resolver unavailability (ResolutionPort down) is represented on
  describe SEPARATELY from capability unavailability (HostPort features).
- SEC-010: a compromised optional adapter is bounded to the authority/data of
  its own attachment role — its fault degrades only that role's features and it
  cannot stand in for a role it was never granted.

chp-core-only.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from chp_server import Server, ServerConfig
from chp_server.features import DEGRADED, READY, UNAVAILABLE
from chp_server.ports import AttachmentRegistry


class Attachment:
    """A minimal port attachment with an observable lifecycle."""

    def __init__(self, roles, *, source="local", health="ready", compromised=False):
        self.roles = tuple(roles)
        self.source = source
        self._health = health
        self._compromised = compromised
        self.validated = False
        self.started = False
        self.stopped = False

    def validate(self):
        self.validated = True

    def start(self):
        self.started = True

    def health(self):
        if self._compromised:
            raise RuntimeError("adapter compromised")
        return self._health

    def stop(self):
        self.stopped = True


def _make_server(tmp_path, *attachments, profile="host"):
    s = Server(ServerConfig(port=0, profile=profile, store=str(tmp_path / "s.sqlite")))
    for a in attachments:
        s.attach(a)
    return s


def _describe(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/server") as r:
        return json.loads(r.read())


def _feature_states(describe):
    return {f["feature"]: f["state"] for f in describe["features"]}


# -- ATT-002 ---------------------------------------------------------------

def test_att_002_lifecycle_defines_every_phase(tmp_path):
    # discovery/load: the registry defines the discovery entry point.
    assert callable(getattr(AttachmentRegistry, "load_entry_points", None))

    host = Attachment(("HostPort",))
    server = _make_server(tmp_path, host)
    try:
        server.start()
        # validation + initialization: both ran during start.
        assert host.validated and host.started
        # readiness: the role and the profile report ready.
        assert server.attachments.role_state("HostPort") == READY
        assert server.ready()["ready"] is True

        # degradation: a role that reports degraded is represented as degraded,
        # NOT dropped — the phase is a first-class lifecycle state.
        host._health = "degraded"
        assert server.attachments.role_state("HostPort") == DEGRADED
        assert server.ready()["ready"] is False  # degraded host is not ready

        # drain: an explicit phase distinct from stop.
        server.drain()
        assert server.state == "draining"
        assert server.ready()["ready"] is False
    finally:
        # stop: the terminal phase tears the attachment down.
        server.stop()
    assert host.stopped and server.state == "stopped"


# -- DISC-008 --------------------------------------------------------------

def test_disc_008_resolver_unavailability_is_distinct_from_capability(tmp_path):
    # A healthy host (capability plane) plus a down resolver (resolution plane).
    host = Attachment(("HostPort",))
    resolver = Attachment(("ResolutionPort",), compromised=True)  # resolver unreachable
    server = _make_server(tmp_path, host, resolver)
    server.start()
    try:
        states = _feature_states(_describe(server))
        # The two conditions are represented on DIFFERENT features with DIFFERENT
        # states: the capability plane is up, the resolver is unavailable.
        assert states["capability.discovery"] == READY
        assert states["capability.resolve"] == UNAVAILABLE
        assert states["capability.discovery"] != states["capability.resolve"]
    finally:
        server.stop()


# -- SEC-010 ---------------------------------------------------------------

def test_sec_010_compromised_adapter_bounded_to_its_role(tmp_path):
    # A healthy host plus a compromised evidence adapter (its health throws).
    host = Attachment(("HostPort",))
    evidence = Attachment(("EvidencePort",), compromised=True)
    server = _make_server(tmp_path, host, evidence)
    server.start()
    try:
        states = _feature_states(_describe(server))
        # The blast radius is bounded to the compromised adapter's OWN role:
        # evidence features go unavailable...
        assert states["evidence.query"] == UNAVAILABLE
        assert states["evidence.verify"] == UNAVAILABLE
        # ...while a feature that does NOT depend on that role is unaffected.
        assert states["capability.discovery"] == READY
        # Authority bound: a compromised adapter cannot stand in for a role it
        # was never granted — the HostPort provider is the healthy host, never
        # the evidence adapter.
        assert server.attachments.for_role("HostPort") is host
        assert server.attachments.for_role("EvidencePort") is evidence
        # The server itself survived the compromised adapter (no crash).
        assert server.state == "ready"
    finally:
        server.stop()
