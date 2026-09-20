"""``CapabilityServer`` — the clean, decorator-first way to surface capabilities.

    from chp_server import CapabilityServer

    app = CapabilityServer("my-host")

    @app.capability("math.add")
    def add(a: int, b: int) -> dict:
        "Add two numbers."
        return {"sum": a + b}

    app.run(port=8800)

`app.capability(...)` registers a governed capability from a plain function:

- the **docstring** becomes the description,
- the **type hints** become the input schema — and the pipeline *enforces* it: a
  malformed call is denied (`input_schema_validation_failed`) before your handler runs,
- payload fields arrive as **keyword arguments** (write `def add(a, b)`, not `payload`).

It is thin sugar over `LocalCapabilityHost` + `Server.serving`; reach for the explicit
host/attachment API (`ExistingHostPort`, resolution, federation, the distribute path,
custom evidence stores) when you outgrow it. chp-core only.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, Callable

from chp_core import LocalCapabilityHost, SQLiteEvidenceStore
from chp_core.decorators import capability as _capability

from .server import Server

if TYPE_CHECKING:
    from chp_core import CapabilityDescriptor


class CapabilityServer:
    """A host you decorate capabilities onto, then serve."""

    def __init__(self, host_id: str = "chp-server", *, store: str | None = None) -> None:
        self.host = LocalCapabilityHost(
            host_id, store=SQLiteEvidenceStore(store or f"{host_id}.sqlite"))

    def capability(self, id: str, *, version: str = "1.0.0",
                   description: str | None = None,
                   input_schema: dict | bool | None = None,
                   **descriptor_kwargs: Any) -> Callable[[Callable], Callable]:
        """Register the decorated function as a governed capability.

        ``description`` defaults to the function's docstring; ``input_schema`` defaults
        to one inferred from its type hints (pass a dict to override, or ``False`` to
        declare none). Any other ``CapabilityDescriptor`` field (``policy``, ``risk``,
        ``tags``, ``timeout_s``, ...) may be passed through.
        """
        def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
            desc = description or (inspect.getdoc(fn) or "").strip() or id
            # input_schema None -> infer from type hints (chp-core does it);
            # False -> declare none; a dict -> use it verbatim.
            explicit = input_schema if isinstance(input_schema, dict) else None
            decorated = _capability(
                id=id, version=version, description=desc,
                input_schema=explicit, infer_schema=(input_schema is None),
                **descriptor_kwargs)(fn)
            self.host.register(decorated)
            return decorated
        return decorate

    def compose(self, adapter: Any, *, replace: bool = False) -> list[CapabilityDescriptor]:
        """Compose an EXISTING adapter's capabilities onto this server — the adapter-first
        way to add git / http / secrets / filesystem / … without reimplementing them. A
        server serves whatever mix it needs: hand-written ``@capability`` functions *and*
        any ``chp-adapter-*`` (a ``chp_core.adapters.BaseAdapter`` of ``@capability``
        methods). One governed implementation, reused here — not a parallel copy. Returns
        the registered capability descriptors; ``replace=True`` overwrites duplicates (e.g.
        an adapter re-created with new config)."""
        from chp_core import register_adapter
        return register_adapter(self.host, adapter, replace=replace)

    def serving(self, **serving_kwargs: Any) -> Server:
        """Build (do not start) a Server projecting this host — for embedding/tests."""
        return Server.serving(self.host, **serving_kwargs)

    def _served_capability_ids(self) -> list[str]:
        """Best-effort list of capability ids the host serves (for the run() banner).

        host.discover() returns a HostDescriptor dict ({..., "capabilities": [{"id": ...}]});
        tolerate an object shape too so this never breaks the banner.
        """
        try:
            desc = self.host.discover()
        except Exception:
            return []
        caps = (desc.get("capabilities") if isinstance(desc, dict)
                else getattr(desc, "capabilities", None)) or []
        ids = []
        for c in caps:
            cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
            if cid:
                ids.append(cid)
        return sorted(ids)

    def run(self, *, port: int = 8800, bind: str = "127.0.0.1",
            **serving_kwargs: Any) -> None:
        """Serve this host over HTTP (blocking)."""
        server = self.serving(port=port, bind=bind, **serving_kwargs)
        server.start()
        base = f"http://{bind}:{server.port}"
        caps = self._served_capability_ids()
        # A first-run banner that SHOWS the payoff: the URL, what's served, a ready-to-paste
        # invoke, and the replay hint (the evidence chain is the point). flush=True so it
        # appears immediately even when stdout is piped/redirected, not just on a tty.
        print(f"chp-server serving at {base}  (Ctrl-C to stop)", flush=True)
        if caps:
            shown = ", ".join(caps[:8]) + (f"  (+{len(caps) - 8} more)" if len(caps) > 8 else "")
            print(f"  {len(caps)} capabilit{'y' if len(caps) == 1 else 'ies'}: {shown}", flush=True)
            print("  try it:", flush=True)
            print(f"    curl -s {base}/invoke -H 'Content-Type: application/json' \\", flush=True)
            print(f"         -d '{{\"capability_id\": \"{caps[0]}\", \"payload\": {{}}}}'", flush=True)
            print(f"    curl -s {base}/replay/<correlation_id>   # the signed evidence chain",
                  flush=True)
        else:
            print(f"  no capabilities registered — GET {base}/server for honest feature truth",
                  flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.stop()
