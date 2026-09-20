"""CapabilityServer — the decorator-first surface for serving capabilities.

`@app.capability(...)` turns a plain function into a governed capability: docstring
-> description, type hints -> input schema (enforced by the pipeline), payload fields
-> keyword arguments. chp-core only.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from chp_server import CapabilityServer


def _post(server, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/invoke",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _descriptor(app, cap_id):
    key = next(k for k in app.host._capabilities if cap_id in k)
    return app.host._capabilities[key].descriptor


def test_decorator_infers_description_and_schema(tmp_path):
    app = CapabilityServer("t", store=str(tmp_path / "t.sqlite"))

    @app.capability("math.add")
    def add(a: int, b: int) -> dict:
        "Add two numbers."
        return {"sum": a + b}

    d = _descriptor(app, "math.add")
    assert d.description == "Add two numbers."                       # docstring
    assert d.input_schema == {"type": "object",
                              "properties": {"a": {"type": "integer"},
                                             "b": {"type": "integer"}},
                              "required": ["a", "b"]}  # type hints; no defaults -> required


def test_served_capability_invokes_and_enforces_types(tmp_path):
    app = CapabilityServer("t", store=str(tmp_path / "t.sqlite"))

    @app.capability("text.upper")
    def upper(text: str) -> dict:
        "Uppercase text."
        return {"upper": text.upper()}

    server = app.serving(port=0, store=str(tmp_path / "s.sqlite"))
    server.start()
    try:
        _, ok = _post(server, {"capability_id": "text.upper", "payload": {"text": "chp"}})
        assert ok["outcome"] == "success" and ok["data"] == {"upper": "CHP"}
        # the inferred schema is enforced by the pipeline, before the handler runs
        _, bad = _post(server, {"capability_id": "text.upper", "payload": {"text": 123}})
        assert bad["outcome"] == "denied"
        assert bad["denial"]["code"] == "input_schema_validation_failed"
    finally:
        server.stop()


def test_overrides_description_schema_and_passthrough(tmp_path):
    app = CapabilityServer("t", store=str(tmp_path / "t.sqlite"))

    @app.capability("x.y", version="2.0.0", description="explicit",
                    input_schema=False, tags=["demo"])
    def y(anything):
        return {"ok": True}

    d = _descriptor(app, "x.y")
    assert d.version == "2.0.0" and d.description == "explicit"
    assert not d.input_schema                # False disables inference (no constraints)
    assert "demo" in (d.tags or [])          # descriptor kwargs pass through


def test_compose_adapter_alongside_functions(tmp_path):
    """A server serves whatever mix it needs: hand-written @capability functions AND an
    existing adapter's capabilities — the adapter-first way, not a reimplementation."""
    from chp_core.adapters import BaseAdapter
    from chp_core.decorators import capability

    app = CapabilityServer("t", store=str(tmp_path / "t.sqlite"))

    @app.capability("math.add")
    def add(a: int, b: int) -> dict:
        return {"sum": a + b}

    class GreetAdapter(BaseAdapter):          # stands in for any chp-adapter-*
        namespace = "greet"

        @capability(id="greet.hello", version="1.0.0", description="Greet.")
        def hello(self, ctx, payload):
            return {"greeting": f"hi {payload.get('name', 'world')}"}

    descriptors = app.compose(GreetAdapter())
    assert any(d.id == "greet.hello" for d in descriptors)
    # one host serves the composed adapter capability AND the hand-written one
    assert app.host.invoke("greet.hello", {"name": "x"}).data == {"greeting": "hi x"}
    assert app.host.invoke("math.add", {"a": 1, "b": 2}).data == {"sum": 3}
