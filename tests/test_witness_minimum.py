"""doc 16: a safety-prod host is UNCLAIMABLE unless its ready WitnessPort meets the configured
minimum independence class. Opt-in + backward-compatible (no minimum => no change). rad:2f429210"""

from __future__ import annotations

import pytest

from chp_server import Server, ServerConfig, ServerStatus
from chp_server.ports import AttachmentRegistry, unmet_witness_minimum, witness_class_rank


class _Port:
    source = "local"

    def __init__(self, roles, independence_class=None):
        self.roles = roles
        if independence_class is not None:
            self.independence_class = independence_class

    def validate(self): ...
    def start(self): ...
    def health(self): return "ready"
    def stop(self): ...


def _safety_prod(tmp_path, *, witness_class, minimum):
    s = Server(ServerConfig(port=0, profile="safety-prod", store=str(tmp_path / "e.sqlite"),
                            witness_min_independence=minimum))
    s.attach(_Port(("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")))
    s.attach(_Port(("ContainmentPort",)))
    s.attach(_Port(("WitnessPort",), independence_class=witness_class))
    s.attach(_Port(("SecretPort",)))
    return s


# -- pure helper ----------------------------------------------------------------
def test_witness_class_rank_accepts_short_and_full():
    assert witness_class_rank("W3") == 3
    assert witness_class_rank("W3_INDEPENDENT_HOST") == 3
    assert witness_class_rank("bogus") is None and witness_class_rank(None) is None


def test_unmet_witness_minimum_fail_closed_on_unknown():
    reg = AttachmentRegistry()                       # no witness ready
    assert unmet_witness_minimum(reg, "W3")           # unknown/absent < W3 -> a reason
    assert unmet_witness_minimum(reg, None) is None   # no minimum -> satisfied


# -- integration: server fail-closed --------------------------------------------
def test_safety_prod_unclaimable_below_minimum(tmp_path):
    s = _safety_prod(tmp_path, witness_class="W2", minimum="W3")
    with pytest.raises(RuntimeError, match="witness independence"):
        s.start()                                    # W2 < required W3 -> fail closed
    assert s.state == ServerStatus.STOPPED


def test_safety_prod_claimable_at_minimum(tmp_path):
    s = _safety_prod(tmp_path, witness_class="W3", minimum="W3")
    s.start()
    try:
        assert s.state == ServerStatus.READY
        assert s.ready()["ready"] is True and "witness_minimum_unmet" not in s.ready()
    finally:
        s.stop()


def test_no_minimum_is_backward_compatible(tmp_path):
    # no witness_min_independence set -> a W1 witness still claims safety-prod (today's behavior)
    s = _safety_prod(tmp_path, witness_class="W1", minimum=None)
    s.start()
    try:
        assert s.state == ServerStatus.READY and s.ready()["ready"] is True
    finally:
        s.stop()
