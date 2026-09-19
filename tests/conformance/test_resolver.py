"""Directory-backed capability resolution (resolver tier part 1) + DISC-004.

A DirectoryResolutionPort resolves a capability to WHERE it is served (endpoints)
from supply advertisements, honoring each advertisement's lease/freshness so a stale
one is never resolved (DISC-004). Attaching it lights up the capability.resolve
feature on describe. chp-core-only.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from chp_core import CapabilityDescriptor, LocalCapabilityHost, SQLiteEvidenceStore
from chp_server import DirectoryResolutionPort, Server, ServerConfig


class GovernedHostPort:
    roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
    source = "local"

    def __init__(self, host):
        self.host = host

    def health(self):
        return "ready"


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_resolve_returns_endpoints_for_a_capability():
    port = DirectoryResolutionPort([
        {"capability_id": "demo.echo", "endpoint": "https://a.example/invoke", "host_id": "host-a"},
        {"capability_id": "demo.echo", "endpoint": "https://b.example/invoke", "host_id": "host-b"},
        {"capability_id": "other.thing", "endpoint": "https://c.example/invoke", "host_id": "host-c"},
    ])
    hits = port.resolve({"capability_id": "demo.echo"})
    assert {h["endpoint"] for h in hits} == {"https://a.example/invoke", "https://b.example/invoke"}
    assert all(h["host_id"] in ("host-a", "host-b") for h in hits)
    # A namespace requirement filters by id prefix.
    assert [h["capability_id"] for h in port.resolve({"namespace": "other."})] == ["other.thing"]


def test_disc_004_lease_freshness_preserved_stale_never_resolved():
    clk = Clock(1000.0)
    port = DirectoryResolutionPort([
        {"capability_id": "demo.echo", "endpoint": "https://fresh/invoke", "expires_at": 2000.0},
        {"capability_id": "demo.echo", "endpoint": "https://stale/invoke", "expires_at": 900.0},
        {"capability_id": "demo.echo", "endpoint": "https://static/invoke"},  # no lease
    ], clock=clk)
    hits = port.resolve({"capability_id": "demo.echo"})
    got = {h["endpoint"]: h["freshness"] for h in hits}
    # The lease-expired advertisement (900 < now 1000) is NOT resolved; fresh + static are.
    assert "https://stale/invoke" not in got
    assert got["https://fresh/invoke"] == "leased"
    assert got["https://static/invoke"] == "static"


def test_capability_resolve_feature_ready_when_attached(tmp_path):
    host = LocalCapabilityHost("h", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="e"),
                  lambda _c, p: {"ok": True})
    s = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.attach(DirectoryResolutionPort([{"capability_id": "demo.echo",
                                       "endpoint": "https://a/invoke"}]))
    s.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{s.port}/server") as r:
            states = {f["feature"]: f["state"] for f in json.loads(r.read())["features"]}
        assert states["capability.resolve"] == "ready"   # a ResolutionPort is attached + ready
    finally:
        s.stop()


def _served(tmp_path, resolver=True):
    host = LocalCapabilityHost("h", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="e"),
                  lambda _c, p: {"ok": True})
    s = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    if resolver:
        s.attach(DirectoryResolutionPort([
            {"capability_id": "demo.echo", "endpoint": "https://a/invoke", "host_id": "host-a"}]))
    s.start()
    return s


def test_wire_resolve_returns_endpoints(tmp_path):
    s = _served(tmp_path, resolver=True)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{s.port}/resolve?capability_id=demo.echo") as r:
            body = json.loads(r.read())
        assert body["count"] == 1
        assert body["resolved"][0]["endpoint"] == "https://a/invoke"
        assert body["resolved"][0]["host_id"] == "host-a"
    finally:
        s.stop()


def test_wire_resolve_is_truthfully_unsupported_without_a_resolver(tmp_path):
    s = _served(tmp_path, resolver=False)
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"http://127.0.0.1:{s.port}/resolve?capability_id=demo.echo")
        assert e.value.code == 501
        assert json.loads(e.value.read())["error"]["code"] == "feature_unsupported"
    finally:
        s.stop()


# --- resolver part 3: the advertisement feed (supply side of DISC-004) --------

def _supply(host_id, cap_ids):
    """The LocalStandalonePorts.supply() shape."""
    return {"host_id": host_id, "freshness": "live",
            "capabilities": [{"id": c, "version": "1.0.0"} for c in cap_ids]}


def test_advertise_supply_publishes_leased_endpoints():
    clk = Clock(1000.0)
    port = DirectoryResolutionPort([], clock=clk)
    n = port.advertise_supply(_supply("host-a", ["greet.hello", "math.add"]),
                              endpoint="https://a/invoke", ttl_s=30)
    assert n == 2
    hits = {h["capability_id"]: h for h in port.resolve({})}   # empty req = all
    assert set(hits) == {"greet.hello", "math.add"}
    assert hits["greet.hello"]["freshness"] == "leased"
    assert hits["greet.hello"]["expires_at"] == 1030.0
    assert hits["greet.hello"]["host_id"] == "host-a"
    assert hits["greet.hello"]["endpoint"] == "https://a/invoke"


def test_heartbeat_refreshes_lease_without_duplicating():
    clk = Clock(1000.0)
    port = DirectoryResolutionPort([], clock=clk)
    port.advertise_supply(_supply("host-a", ["greet.hello"]), endpoint="https://a/invoke", ttl_s=30)
    clk.t = 1020.0                                             # 10s before expiry
    port.advertise_supply(_supply("host-a", ["greet.hello"]), endpoint="https://a/invoke", ttl_s=30)
    hits = port.resolve({"capability_id": "greet.hello"})
    assert len(hits) == 1                                     # upsert: no duplicate
    assert hits[0]["expires_at"] == 1050.0                    # lease refreshed to now+ttl


def test_departed_host_expires_disc004_supply_side():
    clk = Clock(1000.0)
    port = DirectoryResolutionPort([], clock=clk)
    port.advertise_supply(_supply("host-a", ["greet.hello"]), endpoint="https://a/invoke", ttl_s=30)
    assert port.resolve({"capability_id": "greet.hello"})     # resolvable while leased
    clk.t = 1031.0                                            # past lease, no heartbeat
    assert port.resolve({"capability_id": "greet.hello"}) == []   # dropped: not resolvable
    # and the expired entry is pruned on the next advertiser heartbeat (memory hygiene)
    port.advertise_supply(_supply("host-b", ["other.thing"]), endpoint="https://b/invoke", ttl_s=30)
    assert all(e["capability_id"] != "greet.hello" for e in port._dir)


def test_two_hosts_same_capability_both_resolvable():
    clk = Clock(1000.0)
    port = DirectoryResolutionPort([], clock=clk)
    port.advertise_supply(_supply("host-a", ["greet.hello"]), endpoint="https://a/invoke", ttl_s=30)
    port.advertise_supply(_supply("host-b", ["greet.hello"]), endpoint="https://b/invoke", ttl_s=30)
    hits = port.resolve({"capability_id": "greet.hello"})
    assert {h["host_id"] for h in hits} == {"host-a", "host-b"}   # distinct hosts kept


# --- resolver part 3.5: wire POST /advertise, trust-gated -------------------

def _advertise_server(tmp_path, trusted_key_id):
    from chp_server import SourceTrustPolicy
    host = LocalCapabilityHost("h", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    host.register(CapabilityDescriptor(id="demo.echo", version="1.0.0", description="e"),
                  lambda _c, p: {"ok": True})
    s = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.attach(DirectoryResolutionPort([], trust_policy=SourceTrustPolicy(trusted_key_ids={trusted_key_id})))
    s.start()
    return s


def _post(port, path, obj):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req)


def test_wire_advertise_trusted_then_resolvable(tmp_path):
    from chp_core.signing import generate_keypair, signing_available
    if not signing_available():
        pytest.skip("signing backend unavailable")
    from chp_server import advertisement_batch
    from chp_server.introduction import sign_introduction_batch
    issuer = generate_keypair(str(tmp_path / "issuer"))
    s = _advertise_server(tmp_path, issuer.key_id)
    try:
        signed = sign_introduction_batch(
            advertisement_batch("edge-1", "https://e1/invoke", ["demo.echo"],
                                ttl_s=60, generation="g1"), issuer)
        with _post(s.port, "/advertise", signed) as r:
            body = json.loads(r.read())
        assert body["accepted"] is True and body["advertised"] == 1
        # a remote host's supply is now resolvable over the wire
        with urllib.request.urlopen(f"http://127.0.0.1:{s.port}/resolve?capability_id=demo.echo") as r:
            res = json.loads(r.read())
        assert res["count"] == 1
        assert res["resolved"][0]["endpoint"] == "https://e1/invoke"
        assert res["resolved"][0]["host_id"] == "edge-1"
    finally:
        s.stop()


def test_wire_advertise_untrusted_key_forbidden(tmp_path):
    from chp_core.signing import generate_keypair, signing_available
    if not signing_available():
        pytest.skip("signing backend unavailable")
    from chp_server import advertisement_batch
    from chp_server.introduction import sign_introduction_batch
    trusted = generate_keypair(str(tmp_path / "trusted"))
    evil = generate_keypair(str(tmp_path / "evil"))
    s = _advertise_server(tmp_path, trusted.key_id)
    try:
        signed = sign_introduction_batch(
            advertisement_batch("evil-1", "https://evil/invoke", ["demo.echo"],
                                ttl_s=60, generation="g1"), evil)
        with pytest.raises(urllib.error.HTTPError) as e:
            _post(s.port, "/advertise", signed)
        assert e.value.code == 403
        assert json.loads(e.value.read())["error"]["code"] == "advertiser_not_trusted"
        # an untrusted advertiser polluted nothing
        with urllib.request.urlopen(f"http://127.0.0.1:{s.port}/resolve?capability_id=demo.echo") as r:
            assert json.loads(r.read())["count"] == 0
    finally:
        s.stop()


# --- resolver part 4: reachability (direct address vs relay URL) ------------

def test_reachability_defaults_direct_and_surfaces_relay():
    clk = Clock(1000.0)
    port = DirectoryResolutionPort([], clock=clk)
    port.advertise_supply(_supply("host-a", ["greet.hello"]), endpoint="https://a/invoke", ttl_s=30)
    port.advertise_supply(_supply("nat-1", ["greet.hello"]), endpoint="https://relay/nat-1/invoke",
                          ttl_s=30, reachability="relay")   # host behind NAT -> relay URL
    by_host = {h["host_id"]: h["reachability"]
               for h in port.resolve({"capability_id": "greet.hello"})}
    assert by_host == {"host-a": "direct", "nat-1": "relay"}


def test_signed_relay_advertisement_surfaces_reachability(tmp_path):
    from chp_core.signing import generate_keypair, signing_available
    if not signing_available():
        pytest.skip("signing backend unavailable")
    from chp_server import SourceTrustPolicy, advertisement_batch
    from chp_server.introduction import sign_introduction_batch
    issuer = generate_keypair(str(tmp_path / "issuer"))
    port = DirectoryResolutionPort([], trust_policy=SourceTrustPolicy(trusted_key_ids={issuer.key_id}))
    batch = advertisement_batch("nat-1", "https://relay/nat-1/invoke", ["demo.echo"],
                                ttl_s=60, generation="g1", reachability="relay")
    res = port.accept_signed_advertisement(sign_introduction_batch(batch, issuer))
    assert res["accepted"]
    hits = port.resolve({"capability_id": "demo.echo"})
    assert hits[0]["reachability"] == "relay"          # relay hint survives the signed batch
    assert hits[0]["endpoint"] == "https://relay/nat-1/invoke"
