"""Sample capabilities for ``chp-server serve --example``.

A fresh ``chp serve`` starts a truthful ``protocol-only`` server where every
optional feature is ``unsupported`` — honest, but there is nothing to invoke
yet. ``--example`` attaches a governed host carrying a few harmless capabilities
so the very first run is *live* and curl-able, and so the quickstart in the
README works verbatim. It is a teaching aid, not a product surface.

chp-core only — no other CHP package is imported.
"""

from __future__ import annotations

from datetime import datetime, timezone

from chp_core import CapabilityDescriptor, LocalCapabilityHost, SQLiteEvidenceStore


def build_example_host(store_path: str, host_id: str = "chp-example") -> LocalCapabilityHost:
    """A governed host with three sample capabilities: ``greet.hello``,
    ``math.add`` and ``time.now``. Attach it with ``ExistingHostPort``."""
    host = LocalCapabilityHost(host_id, store=SQLiteEvidenceStore(store_path))

    host.register(
        CapabilityDescriptor(
            id="greet.hello", version="1.0.0", description="Greet a name.",
            input_schema={"type": "object",
                          "properties": {"name": {"type": "string"}}}),
        lambda ctx, payload: {"greeting": f"hello, {payload.get('name', 'world')}"},
    )
    host.register(
        CapabilityDescriptor(
            id="math.add", version="1.0.0", description="Add two numbers.",
            input_schema={"type": "object",
                          "properties": {"a": {"type": "number"}, "b": {"type": "number"}}}),
        lambda ctx, payload: {"sum": payload.get("a", 0) + payload.get("b", 0)},
    )
    host.register(
        CapabilityDescriptor(
            id="time.now", version="1.0.0",
            description="Current UTC time as an ISO-8601 string."),
        lambda ctx, payload: {
            "now": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")},
    )
    return host
