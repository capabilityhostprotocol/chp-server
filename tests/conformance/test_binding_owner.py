"""Authoritative owner for the `binding` fact (GAP-SRV-001).

A binding fact is now recorded as coordinator-owned live state (keyed by its
content-addressed digest) instead of accepted as provenance only — while still
granting NO invocation authority (admission stays a per-invocation pipeline step).
"""
from __future__ import annotations

import pytest

from chp_core import LocalCapabilityHost, SQLiteEvidenceStore
from chp_server import IntroductionCoordinator
from chp_server.introduction import BATCH_SCHEMA_VERSION, IntroductionError, canonical_digest


@pytest.fixture()
def host(tmp_path):
    return LocalCapabilityHost("bind-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))


def _batch(candidates, source_id="bundle", generation="g1"):
    return {"schema_version": BATCH_SCHEMA_VERSION, "source_id": source_id,
            "generation": generation, "candidates": candidates}


def _binding_candidate(cid, capability_id, version="1.0.0"):
    payload = {"capability": {"id": capability_id}, "version": version,
               "provider": {"id": "prov-1"}, "host": {"id": "owned-host-1"}}
    return {"candidate_id": cid, "fact_class": "binding",
            "payload": payload, "canonical_digest": canonical_digest(payload)}


def test_binding_fact_gets_authoritative_owner(host):
    coord = IntroductionCoordinator(host)
    cand = _binding_candidate("bind:1", "chp.example.json_transform")
    out = coord.activate(_batch([cand]))

    assert out["activated"] == ["bind:1"]
    digest = cand["canonical_digest"]
    live = coord.live_binding(digest)
    assert live is not None
    assert live["capability_id"] == "chp.example.json_transform"
    assert live["binding_digest"] == digest


def test_binding_grants_no_invocation_authority(host):
    coord = IntroductionCoordinator(host)
    coord.activate(_batch([_binding_candidate("bind:1", "chp.example.json_transform")]))
    # a binding is not supply: the live host gained no executable capability
    assert host.discover()["capabilities"] == []


def test_binding_without_capability_rejected(host):
    coord = IntroductionCoordinator(host)
    bad = {"candidate_id": "bind:bad", "fact_class": "binding",
           "payload": {"provider": {"id": "p"}}}
    bad["canonical_digest"] = canonical_digest(bad["payload"])
    with pytest.raises(IntroductionError):
        coord.activate(_batch([bad]))


def test_superseding_binding_is_appended_not_overwritten(host):
    coord = IntroductionCoordinator(host)
    a = _binding_candidate("bind:v1", "chp.example.json_transform", version="1.0.0")
    b = _binding_candidate("bind:v2", "chp.example.json_transform", version="2.0.0")
    coord.activate(_batch([a]))
    coord.activate(_batch([b], generation="g2"))
    # both digests are retained — a governance change yields a new digest (CHP-CAP-011),
    # and the prior binding record is not destroyed
    assert coord.live_binding(a["canonical_digest"]) is not None
    assert coord.live_binding(b["canonical_digest"]) is not None
    assert a["canonical_digest"] != b["canonical_digest"]
