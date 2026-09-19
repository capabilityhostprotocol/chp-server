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
from typing import Any, Callable

from chp_core import LocalCapabilityHost, SQLiteEvidenceStore
from chp_core.decorators import capability as _capability

from .server import Server


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

    def compose(self, adapter: Any, *, replace: bool = False) -> list:
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

    def run(self, *, port: int = 8800, bind: str = "127.0.0.1",
            **serving_kwargs: Any) -> None:
        """Serve this host over HTTP (blocking)."""
        server = self.serving(port=port, bind=bind, **serving_kwargs)
        server.start()
        print(f"chp-server serving at http://{bind}:{server.port}  (Ctrl-C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.stop()
