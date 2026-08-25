"""Capability-introduction conformance (doc 85) — the scenarios our advertised
mechanisms cover: INTRO-001/003/005/006/007/008/011/013 + the negative
invariants "installation is not introduction" and "no last-writer-wins".

chp-core-only; supply activation is driven through a fake chp.adapters entry
point (monkeypatched discover_adapters), so the suite runs in the clean venv.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from chp_core import CapabilityDescriptor, LocalCapabilityHost, SQLiteEvidenceStore
from chp_core.adapters import HostedCapability
from chp_server import EntryPointIntroductionPort, IntroductionCoordinator, Server, ServerConfig
from chp_server.introduction import BATCH_SCHEMA_VERSION, canonical_digest


class FakeAdapter:
    adapter_id = "fake"

    def capabilities(self):
        async def hello(_ctx, payload):
            return {"hello": payload.get("name")}

        yield HostedCapability(
            descriptor=CapabilityDescriptor(id="fake.hello", version="1.0.0",
                                            description="Hello."),
            handler=hello)


@pytest.fixture()
def host(tmp_path):
    return LocalCapabilityHost("intro-host",
                               store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))


def _batch(source_id, candidates, generation="g1"):
    return {"schema_version": BATCH_SCHEMA_VERSION, "source_id": source_id,
            "generation": generation, "candidates": candidates}


def _supply_candidate(adapter="fake"):
    payload = {"adapter": adapter, "module": "tests.fake", "version": "1.0.0"}
    return {"candidate_id": f"supply:{adapter}", "fact_class": "supply",
            "payload": payload, "canonical_digest": canonical_digest(payload)}


def test_intro_001_definition_only_implies_no_supply(host, tmp_path):
    coord = IntroductionCoordinator(host, registry_path=str(tmp_path / "registry.json"))
    payload = {"id": "future.capability", "package": "chp-adapter-future", "version": "1.0"}
    out = coord.activate(_batch("bundle", [{
        "candidate_id": "def:future.capability", "fact_class": "definition",
        "payload": payload, "canonical_digest": canonical_digest(payload)}]))
    assert out["activated"] == ["def:future.capability"]
    # Definition landed in the known-package manifest, DISABLED — and the live
    # host gained no executable capability.
    from chp_core.registry import load_registry
    entry = next(e for e in load_registry(str(tmp_path / "registry.json"))
                 if e.id == "future.capability")
    assert entry.enabled is False
    assert host.discover()["capabilities"] == []


def test_intro_003_malformed_candidate_rejected_without_mutation(host, tmp_path):
    coord = IntroductionCoordinator(host, registry_path=str(tmp_path / "r.json"))
    out = coord.activate(_batch("bad", [
        {"candidate_id": "x", "fact_class": "nonsense", "payload": {"a": 1}}]))
    assert out["valid"] is False and out["activated"] == []
    assert coord.active == {} and host.discover()["capabilities"] == []


def test_intro_005_same_digest_coalesces_provenance(host, monkeypatch):
    import chp_core.adapters as adapters
    monkeypatch.setattr(adapters, "discover_adapters", lambda group=None: {"fake": FakeAdapter})
    coord = IntroductionCoordinator(host)
    cand = _supply_candidate()
    assert coord.activate(_batch("src-a", [cand]))["activated"] == ["supply:fake"]
    out = coord.activate(_batch("src-b", [cand], generation="g2"))
    assert out["valid"] is True and out["conflicts"] == [] and out["activated"] == []
    assert coord.active["supply:fake"]["sources"] == ["src-a", "src-b"]
    # One registration, not two (register_adapter skips duplicates upstream).
    assert [c["id"] for c in host.discover()["capabilities"]] == ["fake.hello"]


def test_intro_006_conflicting_digest_quarantined_never_last_writer_wins(host, monkeypatch):
    import chp_core.adapters as adapters
    monkeypatch.setattr(adapters, "discover_adapters", lambda group=None: {"fake": FakeAdapter})
    coord = IntroductionCoordinator(host)
    coord.activate(_batch("src-a", [_supply_candidate()]))
    changed = _supply_candidate()
    changed["payload"] = {**changed["payload"], "version": "2.0.0"}
    changed["canonical_digest"] = canonical_digest(changed["payload"])
    out = coord.activate(_batch("src-b", [changed], generation="g2"))
    assert out["activated"] == [] and len(out["conflicts"]) == 1
    assert coord.quarantine and coord.quarantine[0]["candidate_id"] == "supply:fake"
    # The ACTIVE fact is untouched: deterministic, not last-writer-wins.
    assert coord.active["supply:fake"]["payload"]["version"] == "1.0.0"


def test_intro_007_008_failed_refresh_keeps_previous_generation(host, monkeypatch):
    import chp_core.adapters as adapters
    monkeypatch.setattr(adapters, "discover_adapters", lambda group=None: {"fake": FakeAdapter})
    coord = IntroductionCoordinator(host)
    coord.activate(_batch("src", [_supply_candidate()], generation="g1"))
    bad = coord.activate(_batch("src", [
        {"candidate_id": "y", "fact_class": "supply", "payload": {}}], generation="g2"))
    assert bad["valid"] is False
    assert coord.generations["src"] == "g1"  # previous safe generation stays active
    good = coord.activate(_batch("src", [_supply_candidate()], generation="g3"))
    assert good["generation_active"] == "g3"  # complete refresh switches atomically


def test_intro_011_detach_withdraws_only_source_owned_facts(host, tmp_path, monkeypatch):
    import chp_core.adapters as adapters
    monkeypatch.setattr(adapters, "discover_adapters", lambda group=None: {"fake": FakeAdapter})
    coord = IntroductionCoordinator(host, registry_path=str(tmp_path / "r.json"))
    coord.activate(_batch("a", [_supply_candidate()]))
    payload = {"id": "cap.two"}
    coord.activate(_batch("b", [{
        "candidate_id": "def:cap.two", "fact_class": "definition",
        "payload": payload, "canonical_digest": canonical_digest(payload)}]))
    out = coord.detach("a")
    assert out["withdrawn"] == ["supply:fake"]
    assert out["supply_disabled"] == ["fake.hello:1.0.0"]  # LIVE supply withdrawn
    assert "def:cap.two" in coord.active  # other sources untouched (source isolation)


def test_intro_044_045_withdraw_supply_vs_retire(host, monkeypatch):
    """Retirement distinguishes supply withdrawal from definition deletion, and
    neither rewrites recorded execution truth (INTRO-046)."""
    import asyncio

    from chp_core import InvocationEnvelope

    import chp_core.adapters as adapters
    monkeypatch.setattr(adapters, "discover_adapters", lambda group=None: {"fake": FakeAdapter})
    coord = IntroductionCoordinator(host)
    coord.activate(_batch("src", [_supply_candidate()]))

    def invoke(inv_id):
        return asyncio.run(host.ainvoke_envelope(InvocationEnvelope(
            capability_id="fake.hello", payload={"name": "x"}, invocation_id=inv_id)))

    first = invoke("inv-keep")
    assert first.outcome == "success"
    # Withdraw supply: Gate 3 skip, definition/fact knowledge stays.
    coord.withdraw_supply("supply:fake")
    assert invoke("inv-2").outcome == "skipped"
    assert coord.active["supply:fake"]["withdrawn"] is True
    # Retire: registration gone, future invocations deny capability_not_found...
    coord.retire("supply:fake")
    denied = invoke("inv-3")
    assert denied.outcome == "denied" and denied.denial.code == "capability_not_found"
    # ...but the recorded invocation still replays (execution truth intact).
    replayed = invoke("inv-keep")
    assert replayed.outcome == "success" and replayed.data == first.data


def test_intro_013_introduced_capability_still_passes_admission(tmp_path, monkeypatch):
    """Through the served surface: an introduced capability is invocable via the
    normal gates, and unknown capabilities still deny — introduction != authority."""
    import chp_core.adapters as adapters
    monkeypatch.setattr(adapters, "discover_adapters", lambda group=None: {"fake": FakeAdapter})

    class GovernedHostPort:
        roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
        source = "local"
        def __init__(self, host):
            self.host = host
        def health(self):
            return "ready"

    host = LocalCapabilityHost("intro-served",
                               store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))
    s = Server(ServerConfig(port=0, profile="minimum-useful", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.attach(EntryPointIntroductionPort(adapters=["fake"]))
    s.start()
    try:
        assert s.ready()["ready"] is True

        def invoke(cap):
            req = urllib.request.Request(
                f"http://127.0.0.1:{s.port}/invoke",
                data=json.dumps({"capability_id": cap, "payload": {"name": "chp"}}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())

        ok = invoke("fake.hello")
        assert ok["outcome"] == "success" and ok["data"]["hello"] == "chp"
        denied = invoke("never.introduced")
        assert denied["outcome"] == "denied"
        assert denied["denial"]["code"] == "capability_not_found"
    finally:
        s.stop()


def test_intro_042_remote_chp_advertisements_are_claims(tmp_path, monkeypatch):
    """A peer server's catalog imports as origin-attributed definition CLAIMS —
    local trust (allowlist) + freshness apply, and nothing becomes local supply."""
    import chp_core.adapters as adapters
    from chp_server import RemoteChpIntroductionSource

    monkeypatch.setattr(adapters, "discover_adapters", lambda group=None: {"fake": FakeAdapter})

    class GovernedHostPort:
        roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
        source = "local"
        def __init__(self, host):
            self.host = host
        def health(self):
            return "ready"

    # The PEER: a live chp-server actually serving one capability.
    peer_host = LocalCapabilityHost("peer", store=SQLiteEvidenceStore(str(tmp_path / "p.sqlite")))
    peer = Server(ServerConfig(port=0, profile="host", store=str(tmp_path / "ps.sqlite")))
    peer.attach(GovernedHostPort(peer_host))
    peer.start()
    try:
        coord = IntroductionCoordinator(
            LocalCapabilityHost("local", store=SQLiteEvidenceStore(str(tmp_path / "l.sqlite"))),
            registry_path=str(tmp_path / "r.json"))
        src = RemoteChpIntroductionSource(f"http://127.0.0.1:{peer.port}", max_age_s=3600)
        # Empty peer catalog -> empty batch; register a capability on the peer, refresh.
        peer_host.register(
            CapabilityDescriptor(id="remote.cap", version="1.0.0", description="R."),
            lambda _c, _p: None)
        batch = src.snapshot()
        batch["candidates"] = src.fresh_candidates(batch)
        out = coord.activate(batch)
        assert out["activated"] == ["remote-def:remote.cap"]
        fact = coord.active["remote-def:remote.cap"]
        assert fact["payload"]["origin_host"] == "peer" and fact["payload"]["claim"] is True
        # Definition knowledge landed in the registry, disabled; NO local supply.
        from chp_core.registry import load_registry
        assert any(e.id == "remote.cap" and not e.enabled
                   for e in load_registry(str(tmp_path / "r.json")))
        # Local trust: an allowlist that excludes the capability imports nothing.
        picky = RemoteChpIntroductionSource(f"http://127.0.0.1:{peer.port}",
                                            capabilities=["other.cap"])
        assert picky.snapshot()["candidates"] == []
        # Freshness: a max_age of 0 makes every observation stale -> excluded.
        stale = RemoteChpIntroductionSource(f"http://127.0.0.1:{peer.port}", max_age_s=0)
        b = stale.snapshot()
        assert stale.fresh_candidates(b) == []
    finally:
        peer.stop()


def test_installation_is_never_introduction(tmp_path, monkeypatch):
    """Negative invariant: an installed adapter NOT on the allowlist is not
    introduced — and an empty allowlist refuses to validate at all."""
    import chp_core.adapters as adapters
    monkeypatch.setattr(adapters, "discover_adapters",
                        lambda group=None: {"fake": FakeAdapter, "other": FakeAdapter})
    port = EntryPointIntroductionPort(adapters=["fake"])
    batch = port.snapshot()
    assert [c["candidate_id"] for c in batch["candidates"]] == ["supply:fake"]
    with pytest.raises(ValueError, match="allowlist"):
        EntryPointIntroductionPort().validate()
