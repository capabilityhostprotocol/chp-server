"""Multi-instance ownership lease — HA part 1 (HA-003 foundation).

A store-backed active-ownership lease with a **monotonic fencing epoch**, per
HA_MULTI_INSTANCE_DESIGN.md. Exactly one instance holds the lease at a time and is
``active``; the rest are ``standby``. The epoch increments on every ownership
*change* (never on a renew), so a deposed former owner is fenced out (its stale
epoch loses) even if its in-flight consequential work lands late (HA-004).

This is the primitive only. The role-aware /ready, admission gating, and fenced
writes are later HA parts. Fail-closed is baked in where a decision is made:
``role()`` returns ``standby`` if ownership cannot be positively confirmed
(HA-005 — consequential effect needs positive proof of ownership, never the mere
absence of a visible competitor).

Backing: the shared SQLite evidence-store database (all instances of one logical
Host point at the same store), in a dedicated ``chp_ownership_lease`` table, so
acquisition is an atomic compare-and-set under a single ``BEGIN IMMEDIATE`` writer
lock. A Postgres-backed store would use the same table shape + ``SELECT … FOR
UPDATE``; the interface here is storage-agnostic.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable

ACTIVE = "active"
STANDBY = "standby"


@dataclass(frozen=True)
class LeaseState:
    """A point-in-time read of the lease for one logical Host."""

    host_id: str
    owner: str | None      # owning instance id, or None if never held
    epoch: int             # monotonic fencing token; 0 = never held
    expires_at: float      # unix seconds; the lease is valid only while now < expires_at

    def held_by(self, instance_id: str, now: float) -> bool:
        return self.owner == instance_id and now < self.expires_at

    def is_current_epoch(self, epoch: int) -> bool:
        return epoch != 0 and epoch == self.epoch


class OwnershipLease:
    """Store-backed active-ownership lease for one logical Host."""

    def __init__(self, db_path: str, host_id: str, *,
                 clock: Callable[[], float] | None = None) -> None:
        self._db = db_path
        self._host = host_id
        import time
        self._now = clock or time.time
        with self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS chp_ownership_lease ("
                "  host_id TEXT PRIMARY KEY,"
                "  owner TEXT,"
                "  epoch INTEGER NOT NULL DEFAULT 0,"
                "  expires_at REAL NOT NULL DEFAULT 0,"
                "  heartbeat_at REAL NOT NULL DEFAULT 0)")

    def _conn(self) -> sqlite3.Connection:
        # autocommit mode (isolation_level=None) so we drive transactions explicitly;
        # a short busy timeout so a contended writer waits briefly rather than erroring.
        conn = sqlite3.connect(self._db, timeout=5.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _read(self, conn: sqlite3.Connection) -> tuple[str | None, int, float]:
        row = conn.execute(
            "SELECT owner, epoch, expires_at FROM chp_ownership_lease WHERE host_id=?",
            (self._host,)).fetchone()
        return (row[0], row[1], row[2]) if row else (None, 0, 0.0)

    def current(self) -> LeaseState:
        """Read the lease (no acquisition)."""
        conn = self._conn()
        try:
            owner, epoch, expires = self._read(conn)
        finally:
            conn.close()
        return LeaseState(self._host, owner, epoch, expires)

    def try_acquire(self, instance_id: str, ttl_seconds: float) -> LeaseState:
        """Atomically acquire or renew ownership.

        - No current owner, or the lease has expired, or WE already own it → we become
          (or stay) the owner and the lease is extended to ``now + ttl_seconds``.
        - Ownership CHANGE (a new owner, i.e. acquiring a free/expired lease we did not
          previously hold) bumps the fencing ``epoch`` by 1; a renew by the same owner
          leaves the epoch unchanged.
        - A live lease held by ANOTHER instance is left untouched — the returned state
          shows that other owner (we are standby).

        Returns the resulting LeaseState. Raises on store failure (the caller must
        treat that as loss of ownership — see ``role``).
        """
        now = self._now()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            owner, epoch, expires = self._read(conn)
            held_by_other = owner is not None and owner != instance_id and now < expires
            if held_by_other:
                conn.execute("COMMIT")
                return LeaseState(self._host, owner, epoch, expires)
            renew = owner == instance_id and now < expires
            new_epoch = epoch if renew else epoch + 1
            new_expires = now + ttl_seconds
            conn.execute(
                "INSERT INTO chp_ownership_lease(host_id, owner, epoch, expires_at, heartbeat_at)"
                " VALUES(?,?,?,?,?)"
                " ON CONFLICT(host_id) DO UPDATE SET owner=excluded.owner, epoch=excluded.epoch,"
                " expires_at=excluded.expires_at, heartbeat_at=excluded.heartbeat_at",
                (self._host, instance_id, new_epoch, new_expires, now))
            conn.execute("COMMIT")
            return LeaseState(self._host, instance_id, new_epoch, new_expires)
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def renew(self, instance_id: str, ttl_seconds: float) -> LeaseState | None:
        """Heartbeat: extend our lease iff we still own it (unexpired). Returns the new
        state, or None if we have lost ownership (someone else took over) — the caller
        must then stop acting as active."""
        state = self.try_acquire(instance_id, ttl_seconds)
        return state if state.owner == instance_id else None

    def role(self, instance_id: str) -> str:
        """ACTIVE iff we positively hold an unexpired lease right now, else STANDBY.
        FAIL CLOSED (HA-005): any store error, or an unconfirmable lease, is STANDBY —
        consequential effect requires positive proof of ownership, not the absence of a
        competitor."""
        try:
            return ACTIVE if self.current().held_by(instance_id, self._now()) else STANDBY
        except sqlite3.Error:
            return STANDBY

    def fence_ok(self, epoch: int) -> bool:
        """A fencing check for a consequential write stamped with ``epoch`` (HA-004):
        True only if that epoch is still the current ownership epoch. A deposed owner's
        stale epoch fails, so its late write is refused. Fail closed on store error."""
        try:
            return self.current().is_current_epoch(epoch)
        except sqlite3.Error:
            return False
