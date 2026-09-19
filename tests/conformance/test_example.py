"""`chp-server serve --example` sample capabilities.

`build_example_host` gives a fresh install something real to invoke on first run.
It must register the three advertised capabilities and each must execute — and,
served, they appear on the public capabilities hint. chp-core-only.
"""

from __future__ import annotations

import json
import urllib.request

from chp_server import Server
from chp_server._example import build_example_host


def test_example_host_registers_and_invokes(tmp_path):
    host = build_example_host(str(tmp_path / "ex.sqlite"))
    ids = {c.id for c in host.list_capabilities()} if hasattr(host, "list_capabilities") \
        else set(host._capabilities.keys())
    for cap in ("greet.hello", "math.add", "time.now"):
        assert any(cap in i for i in ids), f"{cap} not registered"

    assert host.invoke("greet.hello", {"name": "CHP"}).data == {"greeting": "hello, CHP"}
    assert host.invoke("math.add", {"a": 2, "b": 3}).data == {"sum": 5}
    now = host.invoke("time.now", {}).data["now"]
    assert now.endswith("Z") and "T" in now          # ISO-8601 UTC


def test_example_capabilities_are_served(tmp_path):
    server = Server.serving(build_example_host(str(tmp_path / "ex.sqlite")),
                            port=0, store=str(tmp_path / "srv.sqlite"))
    server.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/capabilities.txt") as r:
            hint = r.read().decode()
        for cap in ("greet.hello", "math.add", "time.now"):
            assert cap in hint
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/invoke",
            data=json.dumps({"capability_id": "math.add", "payload": {"a": 40, "b": 2}}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            out = json.loads(r.read())
        assert out["outcome"] == "success" and out["data"] == {"sum": 42}
    finally:
        server.stop()
