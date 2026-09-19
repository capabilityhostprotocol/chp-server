#!/usr/bin/env python3
"""The clean way to surface capabilities — decorator-first with CapabilityServer.

Run:  python quickstart.py      (then curl the endpoints it prints)

Each function below becomes a governed capability: its docstring is the description,
its type hints are the input schema (which the pipeline *enforces* — a malformed call
is denied before the handler runs), and payload fields arrive as keyword arguments.
Needs only chp-core + chp-server.
"""

from __future__ import annotations

from chp_server import CapabilityServer

app = CapabilityServer("quickstart")


@app.capability("math.add")
def add(a: int, b: int) -> dict:
    """Add two numbers."""
    return {"sum": a + b}


@app.capability("text.wordcount")
def wordcount(text: str) -> dict:
    """Count the words and characters in some text."""
    return {"words": len(text.split()), "chars": len(text)}


@app.capability("greet.hello")
def hello(name: str = "world", excited: bool = False) -> dict:
    """Greet a name, optionally with enthusiasm."""
    return {"greeting": f"hello, {name}" + ("!" if excited else "")}


if __name__ == "__main__":
    print("Serving 3 capabilities. In another shell, try:\n")
    print("  curl -s localhost:8800/capabilities.txt")
    print("  curl -s localhost:8800/invoke -H 'Content-Type: application/json' \\")
    print("       -d '{\"capability_id\": \"math.add\", \"payload\": {\"a\": 2, \"b\": 3}}'")
    print("\n  # a malformed call is denied before the handler runs:")
    print("  curl -s localhost:8800/invoke -H 'Content-Type: application/json' \\")
    print("       -d '{\"capability_id\": \"math.add\", \"payload\": {\"a\": \"two\", \"b\": 3}}'\n")
    app.run(port=8800)
