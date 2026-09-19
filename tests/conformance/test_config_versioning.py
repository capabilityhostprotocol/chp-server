"""Config-generation + versioning conformance (BOOT-001/005, API-005, CONF-011).

Server.Describe is the one projection of these truths: a config generation is
identifiable, the package/distribution version is a compatibility axis distinct
from the protocol version, and boot is deterministic for equivalent config.
chp-core-only.
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


def _host(tmp_path, name="cfg-host"):
    h = LocalCapabilityHost(name, store=SQLiteEvidenceStore(str(tmp_path / f"{name}.sqlite")))
    h.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="e"),
               lambda _c, p: {"echo": p.get("text")})
    return h


def _describe(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/server") as r:
        return json.loads(r.read())


@pytest.fixture()
def server(tmp_path):
    s = Server(ServerConfig(port=0, profile="host", host_id="cfg-srv",
                            store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(_host(tmp_path)))
    s.start()
    yield s
    s.stop()


def test_boot_005_config_generation_is_identifiable(server):
    # BOOT-005: a configuration generation MUST be identifiable — surfaced as an
    # integer generation counter on Server.Describe (bumped on reconfiguration).
    d = _describe(server)
    assert "config_generation" in d
    assert isinstance(d["config_generation"], int) and d["config_generation"] >= 1


def test_api_005_package_version_distinct_from_protocol(server):
    # API-005: programmatic package/API compatibility is versioned INDEPENDENTLY of
    # protocol compatibility — describe surfaces both as distinct axes.
    d = _describe(server)
    assert d["distribution_version"] and d["protocol_version"]
    assert d["distribution_version"] != d["protocol_version"]        # different axes
    assert d["protocol_version"] in d["supported_versions"]          # protocol-compat axis


def test_conf_011_three_compatibility_axes_identified_separately(server):
    # CONF-011: a release MUST identify protocol, package-API, and extension
    # compatibility SEPARATELY. Describe carries all three as distinct fields.
    d = _describe(server)
    assert d["protocol_version"]                    # protocol compatibility
    assert d["distribution_version"]                # package/API compatibility
    assert d["core_version"]                        # the reused-core (extension base) compatibility
    # they are not collapsed into one identifier
    assert len({d["protocol_version"], d["distribution_version"]}) == 2


def test_boot_001_boot_is_deterministic_for_equivalent_config(tmp_path):
    # BOOT-001: boot MUST be deterministic for equivalent configuration + dependency
    # state. Two independent boots of the same config produce the same describe —
    # except the per-instance identity (instance id + start time), which is
    # deliberately unique.
    def boot():
        s = Server(ServerConfig(port=0, profile="host", host_id="det-srv",
                                store=str(tmp_path / "det.sqlite")))
        s.attach(GovernedHostPort(_host(tmp_path, "det")))
        s.start()
        try:
            d = _describe(s)
        finally:
            s.stop()
        d.pop("instance")            # per-instance identity is non-deterministic by design
        return d

    assert boot() == boot()          # everything else is deterministic


def test_feat_011_feature_not_ready_after_attachment_unhealthy(tmp_path):
    # FEAT-011: a feature MUST NOT remain advertised as ready once its required
    # attachment crosses a defined unhealthy threshold. Feature truth is computed
    # from LIVE attachment health, so a healthy->degraded transition is reflected.
    class ToggleHostPort(GovernedHostPort):
        def __init__(self, host):
            super().__init__(host)
            self._state = "ready"

        def health(self):
            return self._state

    port = ToggleHostPort(_host(tmp_path, "feat"))
    s = Server(ServerConfig(port=0, profile="host", host_id="feat-srv",
                            store=str(tmp_path / "feat-s.sqlite")))
    s.attach(port)
    s.start()
    try:
        ready = {f.feature: f.state for f in s.features.snapshot(lifecycle=s.state)}
        assert ready["capability.discovery"] == "ready"          # healthy attachment
        port._state = "degraded"                                 # crosses the unhealthy threshold
        after = {f.feature: f.state for f in s.features.snapshot(lifecycle=s.state)}
        assert after["capability.discovery"] != "ready"          # MUST NOT stay advertised ready
    finally:
        s.stop()


def test_boot_008_configuration_activation_is_atomic(tmp_path):
    # BOOT-008: configuration activation is all-or-nothing. An invalid field aborts
    # the WHOLE assembly (from_sources raises before returning any config, so no
    # partial config is ever applied), and a valid config activates as one generation.
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"port": 9001, "nonsense": 1}))  # one bad field
    with pytest.raises(ValueError):
        ServerConfig.from_sources(config_file=str(bad))        # nothing applied
    with pytest.raises(ValueError):
        ServerConfig.from_sources(profile="does-not-exist")    # post-init validation aborts
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"port": 9002, "profile": "host"}))
    cfg = ServerConfig.from_sources(config_file=str(good))      # whole config or nothing
    assert cfg.port == 9002 and cfg.profile == "host"
    assert Server(cfg).config_generation == 1                  # one atomic activation
