#!/usr/bin/env python3
"""Composing an existing adapter into a server — adapter-first.

One CapabilityServer serves a hand-written capability AND an existing chp-adapter-* (the
filesystem adapter, scoped to a temp dir) — one governed host, every call over HTTP,
every call admission-gated and evidenced. The point: don't reimplement filesystem / http /
secrets / … — compose the adapter.

Run:  pip install chp-server chp-core chp-adapter-filesystem && python compose.py
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request

from chp_server import CapabilityServer
from chp_adapter_filesystem import FilesystemAdapter, FilesystemConfig   # an existing capability set

WORK = tempfile.mkdtemp(prefix="chp-compose-")

app = CapabilityServer("compose-demo", store=os.path.join(WORK, "host.sqlite"))


@app.capability("text.wordcount")
def wordcount(text: str) -> dict:
    """Count words and characters in some text."""
    return {"words": len(text.split()), "chars": len(text)}


# Compose an EXISTING adapter's capabilities, scoped to WORK — not a reimplementation.
app.compose(FilesystemAdapter(FilesystemConfig(allowed_roots=[WORK])))


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
    print(f"  {label:38} -> {outcome}  {detail}")


def main() -> None:
    server = app.serving(port=0, store=os.path.join(WORK, "srv.sqlite"))
    server.start()
    p = server.port
    try:
        print(f"one server, composed surface (scoped to {WORK})\n")
        note = os.path.join(WORK, "note.txt")
        show("filesystem.write_file (composed)",
             invoke(p, "chp.adapters.filesystem.write_file",
                    {"path": note, "content": "hello from a composed adapter"}))
        show("filesystem.read_file (composed)",
             invoke(p, "chp.adapters.filesystem.read_file", {"path": note}))
        show("filesystem.list_directory (composed)",
             invoke(p, "chp.adapters.filesystem.list_directory", {"path": WORK}))
        show("text.wordcount (hand-written)",
             invoke(p, "text.wordcount", {"text": "one two three four"}))
        with urllib.request.urlopen(f"http://127.0.0.1:{p}/capabilities.txt") as resp:
            caps = [ln for ln in resp.read().decode().splitlines() if ln and not ln.startswith("#")]
        print("\nserved capabilities (adapter + hand-written):")
        for c in sorted(caps):
            print("  -", c)
    finally:
        server.stop()


if __name__ == "__main__":
    main()
