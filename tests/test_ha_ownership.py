"""Ownership-lease primitive (HA part 1) — active-ownership, epoch fencing, fail-closed."""

from __future__ import annotations

import pytest

from chp_server.ha import ACTIVE, STANDBY, OwnershipLease


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


@pytest.fixture()
def db(tmp_path):
    return str(tmp_path / "lease.sqlite")


def test_single_instance_acquires_and_is_active(db):
    clk = Clock()
    lease = OwnershipLease(db, "host-1", clock=clk)
    st = lease.try_acquire("inst-a", ttl_seconds=30)
    assert st.owner == "inst-a" and st.epoch == 1        # first ownership -> epoch 1
    assert lease.role("inst-a") == ACTIVE


def test_renew_extends_without_bumping_epoch(db):
    clk = Clock()
    lease = OwnershipLease(db, "host-1", clock=clk)
    lease.try_acquire("inst-a", 30)
    clk.advance(10)
    st = lease.renew("inst-a", 30)
    assert st is not None and st.epoch == 1              # renew keeps the epoch
    assert st.expires_at == clk() + 30                  # extended


def test_second_instance_cannot_take_a_live_lease(db):
    clk = Clock()
    a = OwnershipLease(db, "host-1", clock=clk)
    b = OwnershipLease(db, "host-1", clock=clk)
    a.try_acquire("inst-a", 30)
    st = b.try_acquire("inst-b", 30)                     # a still holds it
    assert st.owner == "inst-a" and st.epoch == 1        # b did not take it
    assert b.role("inst-b") == STANDBY
    assert a.role("inst-a") == ACTIVE


def test_takeover_after_expiry_bumps_epoch_and_fences(db):
    clk = Clock()
    a = OwnershipLease(db, "host-1", clock=clk)
    b = OwnershipLease(db, "host-1", clock=clk)
    held = a.try_acquire("inst-a", 30)
    assert held.epoch == 1
    clk.advance(31)                                      # a's lease expires
    st = b.try_acquire("inst-b", 30)                     # b takes over
    assert st.owner == "inst-b" and st.epoch == 2        # ownership change -> epoch bump
    assert b.role("inst-b") == ACTIVE
    assert a.role("inst-a") == STANDBY                   # a is deposed
    # HA-004 fencing: a's old epoch (1) is stale and fails; b's epoch (2) is current.
    assert a.fence_ok(1) is False
    assert b.fence_ok(2) is True


def test_renew_returns_none_when_ownership_lost(db):
    clk = Clock()
    a = OwnershipLease(db, "host-1", clock=clk)
    b = OwnershipLease(db, "host-1", clock=clk)
    a.try_acquire("inst-a", 30)
    clk.advance(31)
    b.try_acquire("inst-b", 30)                          # b takes over
    assert a.renew("inst-a", 30) is None                 # a can no longer renew
    assert a.role("inst-a") == STANDBY


def test_epoch_is_monotonic_across_handovers(db):
    clk = Clock()
    a = OwnershipLease(db, "host-1", clock=clk)
    b = OwnershipLease(db, "host-1", clock=clk)
    e1 = a.try_acquire("inst-a", 10).epoch
    clk.advance(11); e2 = b.try_acquire("inst-b", 10).epoch
    clk.advance(11); e3 = a.try_acquire("inst-a", 10).epoch
    assert e1 < e2 < e3                                  # never decreases


def test_role_fails_closed_on_store_error(tmp_path):
    # A lease pointed at an unusable path cannot confirm ownership → STANDBY, never
    # ACTIVE (HA-005 fail-closed). Point at a directory to force a sqlite error.
    lease = OwnershipLease.__new__(OwnershipLease)
    lease._db = str(tmp_path)          # a directory, not a db file
    lease._host = "host-1"
    lease._now = lambda: 1000.0
    assert lease.role("inst-a") == STANDBY
    assert lease.fence_ok(1) is False
