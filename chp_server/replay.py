"""A typed, readable view over a ``GET /replay`` response.

The wire response is JSON (a dict) — that is the protocol. But a Python caller
shouldn't have to spelunk raw evidence dicts (``action_digest``, ``payload_commitment``,
``hash_scheme`` …) to answer "what happened, in order, and did it succeed?". ``Replay``
parses the wire dict into typed objects (autocomplete + mypy) and renders a human-readable
trace. Typed objects at the Python edge; dicts stay on the wire.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ReplayEvent:
    """One event in a correlation's hash-chained evidence trail."""

    sequence: int | None
    event_type: str
    capability_id: str | None
    outcome: str | None
    timestamp: str | None
    denial: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_wire(cls, e: dict[str, Any]) -> "ReplayEvent":
        return cls(
            sequence=e.get("sequence"),
            event_type=e.get("event_type") or "?",
            capability_id=e.get("capability_id"),
            outcome=e.get("outcome"),
            timestamp=e.get("timestamp"),
            denial=e.get("denial"),
            raw=e,
        )


@dataclass(frozen=True)
class Replay:
    """The evidence chain for one correlation — a typed view of ``GET /replay/{id}``."""

    correlation_id: str | None
    events: list[ReplayEvent]
    partial: bool = False
    truncated: bool = False
    missing_hosts: list[str] = field(default_factory=list)

    @classmethod
    def from_wire(cls, doc: dict[str, Any]) -> "Replay":
        """Parse a ``GET /replay`` JSON response into a typed ``Replay``."""
        return cls(
            correlation_id=doc.get("correlation_id"),
            events=[ReplayEvent.from_wire(e) for e in (doc.get("events") or [])],
            partial=bool(doc.get("partial")),
            truncated=bool(doc.get("truncated")),
            missing_hosts=list(doc.get("missing_hosts") or []),
        )

    def render(self) -> str:
        """A compact, readable trace — the evidence chain without the cryptographic noise."""
        flags = []
        if self.partial:
            flags.append("partial")
        if self.truncated:
            flags.append("truncated")
        head = f"correlation {self.correlation_id or '?'}  ({len(self.events)} event" \
               f"{'' if len(self.events) == 1 else 's'}" \
               f"{', ' + ', '.join(flags) if flags else ''})"
        lines = [head]
        for e in self.events:
            seq = "?" if e.sequence is None else e.sequence
            cap = f"  {e.capability_id}" if e.capability_id else ""
            detail = ""
            if e.denial:
                detail = f"  DENIED {e.denial.get('code')}: {e.denial.get('message')}"
            elif e.outcome:
                detail = f"  → {e.outcome}"
            ts = f"  {e.timestamp}" if e.timestamp else ""
            lines.append(f"  [{seq}] {e.event_type}{cap}{detail}{ts}")
        if self.missing_hosts:
            lines.append(f"  missing hosts (evidence not gathered): {', '.join(self.missing_hosts)}")
        return "\n".join(lines)
