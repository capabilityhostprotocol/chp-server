#!/usr/bin/env python3
"""Import an MCP server as governed capabilities — adapter-first.

An external MCP server's tools become CHP capabilities by composing the existing
`chp-adapter-mcp` — NOT by teaching chp-server to speak MCP itself. `MCPAdapter` connects to
an MCP server, lists its tools, and yields one governed capability per tool
(`chp.adapters.mcp.<server>.<tool>`) whose `input_schema` IS the tool's own JSON Schema — so
chp-core validates every call BEFORE the tool runs, and every call is admission-gated and
evidenced. The whole MCP ecosystem, wrapped in CHP governance, by composition.

For a REAL server you give MCPServerConfig a `command` (stdio) or `url` (HTTP/SSE):

    app.compose(MCPAdapter(MCPServerConfig(
        name="fs", command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"])))

This example injects a tiny IN-PROCESS stand-in session (the adapter's testing seam) so it
runs with no external process or network — the only difference from a real server is that one
line. Everything downstream (governance, schema enforcement, evidence) is identical.

Run:  pip install chp-server chp-core chp-adapter-mcp && python import_mcp.py
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request

from chp_server import CapabilityServer
from chp_adapter_mcp import MCPAdapter, MCPServerConfig   # the existing MCP-import adapter

WORK = tempfile.mkdtemp(prefix="chp-mcp-")


# --- a stand-in MCP server, in-process (replace with a real command=/url= server) ----------
# These three tiny classes mirror the shapes a real MCP session yields; the adapter treats
# them exactly like a live server's tools and results.

class _Tool:
    def __init__(self, name, description, input_schema):
        self.name, self.description, self.inputSchema = name, description, input_schema


class _Block:
    def __init__(self, text): self._text = text
    def model_dump(self, mode="python"): return {"type": "text", "text": self._text}


class _Result:
    def __init__(self, content, is_error=False): self.content, self.isError = content, is_error


class StandInMCPSession:
    """An in-memory _MCPSession standing in for a live MCP server (stdio/HTTP)."""

    TOOLS = [
        _Tool("add", "Add two integers", {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"]}),
        _Tool("shout", "Uppercase some text", {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"]}),
    ]

    @property
    def tools(self): return self.TOOLS
    def connect(self): pass
    def close(self): pass

    async def call(self, name, arguments):
        if name == "add":
            return _Result([_Block(str(arguments["a"] + arguments["b"]))])
        if name == "shout":
            return _Result([_Block(str(arguments["text"]).upper())])
        return _Result([_Block(f"unknown tool {name}")], is_error=True)


app = CapabilityServer("mcp-import-demo", store=os.path.join(WORK, "host.sqlite"))

# Compose the MCP adapter — each of the server's tools becomes a governed CHP capability.
# (session= is the stand-in; a real server uses command= or url= on the config instead.)
app.compose(MCPAdapter(MCPServerConfig(name="calc", command="stand-in"),
                       session=StandInMCPSession()))


def invoke(port: int, capability_id: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/invoke",
        data=json.dumps({"capability_id": capability_id, "payload": payload}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def show(label: str, resp: dict) -> None:
    outcome = resp.get("outcome")
    detail = resp.get("data") if outcome == "success" else (resp.get("denial") or resp.get("error"))
    print(f"  {label:52} -> {outcome}  {detail}")


def main() -> None:
    server = app.serving(port=0, store=os.path.join(WORK, "srv.sqlite"))
    server.start()
    p = server.port
    try:
        print("MCP server tools, imported as governed CHP capabilities\n")
        # A real imported tool call — proxied to the MCP session, fully evidenced.
        show("mcp.calc.add {a:2, b:3}  (imported tool)",
             invoke(p, "chp.adapters.mcp.calc.add", {"a": 2, "b": 3}))
        show("mcp.calc.shout {text: 'hello'}  (imported tool)",
             invoke(p, "chp.adapters.mcp.calc.shout", {"text": "hello"}))
        # The governance win: the tool's OWN JSON Schema is enforced BEFORE the tool runs.
        show("mcp.calc.add {a: 'two'}  (bad type — denied pre-tool)",
             invoke(p, "chp.adapters.mcp.calc.add", {"a": "two", "b": 3}))
        with urllib.request.urlopen(f"http://127.0.0.1:{p}/capabilities.txt") as resp:
            caps = [ln for ln in resp.read().decode().splitlines() if ln and not ln.startswith("#")]
        print("\nimported MCP tools, now governed capabilities:")
        for c in sorted(caps):
            print("  -", c)
    finally:
        server.stop()


if __name__ == "__main__":
    main()
