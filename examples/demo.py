#!/usr/bin/env python3
"""End-to-end chp-server demonstration — "invocable anywhere, on any host".

Stands up real chp-server instances serving real capabilities, then acts as a client
over HTTP to exercise, in order: discovery surfaces, truthful feature negotiation,
governed invocation + evidence, absolute-deadline enforcement, tenant-scoped evidence
query, capability resolution, and HA active/standby failover.

Run:  python packages/chp-server/examples/demo.py
Needs only chp-core + chp-server (the whole point — no other CHP package required).
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request

from chp_core import (CapabilityDescriptor, IndeterminateExecution, LocalCapabilityHost,
                      SQLiteEvidenceStore)
from chp_core.types import PolicyDescriptor
from chp_server import DirectoryResolutionPort, ExistingHostPort, Server, ServerConfig


def banner(title: str) -> None:
    print("\n" + "=" * 72 + f"\n  {title}\n" + "=" * 72)


def _parse(raw):
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw.decode() if isinstance(raw, bytes) else raw


def GET(port, path, key=None):
    headers = {"X-CHP-Key": key} if key else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, _parse(r.read())
    except urllib.error.HTTPError as e:
        return e.code, _parse(e.read())


def POST(port, body, key=None):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-CHP-Key"] = key
    req = urllib.request.Request(f"http://127.0.0.1:{port}/invoke",
                                 data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def build_host(store_path, host_id="demo-host"):
    host = LocalCapabilityHost(host_id, store=SQLiteEvidenceStore(store_path))
    host.register(CapabilityDescriptor(id="greet.hello", version="1.0.0",
                                       description="Greet a name."),
                  lambda _c, p: {"greeting": f"hello, {p.get('name', 'world')}"})
    host.register(CapabilityDescriptor(id="math.add", version="1.0.0", description="Add."),
                  lambda _c, p: {"sum": p.get("a", 0) + p.get("b", 0)})

    def review(_c, p):
        raise IndeterminateExecution("awaiting human reviewer")  # long-running human work

    host.register(CapabilityDescriptor(id="human.review", version="1.0.0",
                                       description="Human review (indeterminate)."), review)
    # a capability only 'alice' may discover/invoke (visibility policy)
    host.register(CapabilityDescriptor(id="secret.ping", version="1.0.0", description="restricted",
                                       policy=PolicyDescriptor(allowed_actors=["alice"])),
                  lambda _c, p: {"pong": True})
    return host


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="chp-demo-")
    # Two named callers so we can show visibility + tenant-scoped evidence.
    os.environ["CHP_HOST_API_KEYS"] = "alice:key-a,bob:key-b"

    host = build_host(os.path.join(tmp, "host.sqlite"))
    server = Server(ServerConfig(port=0, profile="host", host_id="demo-host",
                                 store=os.path.join(tmp, "srv.sqlite")))
    server.attach(ExistingHostPort(host))
    server.attach(DirectoryResolutionPort([
        {"capability_id": "greet.hello", "endpoint": "https://edge-a.example/invoke",
         "host_id": "demo-host"},
        {"capability_id": "greet.hello", "endpoint": "https://edge-b.example/invoke",
         "host_id": "demo-host-replica"},
    ]))
    server.start()
    p = server.port
    try:
        banner("1. The server is up — liveness, readiness, identity")
        print("GET /health :", GET(p, "/health")[1])
        print("GET /ready  :", GET(p, "/ready")[1])
        _, ident = GET(p, "/.well-known/chp-identity")
        print("GET /.well-known/chp-identity assurance:", ident.get("assurance"),
              "key_id:", ident.get("key_id"))

        banner("2. Server.Describe — truthful feature negotiation + versions")
        _, desc = GET(p, "/server", key="key-a")
        print("distribution:", desc["distribution_version"], " protocol:", desc["protocol_version"],
              " profile:", desc["profile"], " instance:", desc["instance"]["id"])
        feats = {f["feature"]: f["state"] for f in desc["features"]}
        for f in ("capability.discovery", "invocation.local", "capability.resolve", "mcp.import"):
            print(f"  feature {f:22} -> {feats.get(f)}")

        banner("3. Discovery surfaces (three distinct purposes)")
        _, wk = GET(p, "/.well-known/chp")
        print("/.well-known/chp surfaces:", list(wk["surfaces"]))
        hint = GET(p, "/capabilities.txt")[1]
        print("/capabilities.txt (public hint):")
        print("   " + str(hint).strip().replace("\n", "\n   "))
        alice_caps = {c["id"] for c in GET(p, "/host", key="key-a")[1]["capabilities"]}
        bob_caps = {c["id"] for c in GET(p, "/host", key="key-b")[1]["capabilities"]}
        print("live /host as alice:", sorted(alice_caps))
        print("live /host as bob  :", sorted(bob_caps), " (secret.ping hidden from bob)")

        banner("4. Governed invocation + evidence")
        st, out = POST(p, {"capability_id": "greet.hello", "payload": {"name": "CHP"}}, key="key-a")
        print("invoke greet.hello ->", out["outcome"], out["data"], " evidence_ids:", len(out["evidence_ids"]))
        corr = out["correlation"]["correlation_id"]
        st, rep = GET(p, f"/replay/{corr}", key="key-a")
        print("replay evidence chain:", [e["event_type"] for e in rep["events"]])

        banner("5. Long-running human work is honest (indeterminate, not fake success)")
        _, hr = POST(p, {"capability_id": "human.review", "payload": {}}, key="key-a")
        print("invoke human.review ->", hr["outcome"], " success:", hr["success"],
              " (queryable later; no continuous connection needed)")

        banner("6. Absolute deadlines — stale work is refused before it runs")
        from datetime import datetime, timedelta, timezone
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        _, dl = POST(p, {"capability_id": "greet.hello", "payload": {"name": "late"},
                         "deadline": past}, key="key-a")
        print("invoke with a PAST deadline ->", dl["outcome"], "code:", dl["denial"]["code"])

        banner("7. Evidence query respects the tenant boundary")
        code, _ = GET(p, f"/replay/{corr}", key="key-b")
        print("bob tries to replay alice's correlation ->", code, "(404 = not disclosed)")

        banner("8. Resolution — WHERE is this capability served (invocable anywhere)")
        _, res = GET(p, "/resolve?capability_id=greet.hello", key="key-a")
        for r in res["resolved"]:
            print("  greet.hello @", r["endpoint"], "on", r["host_id"], f"({r['freshness']})")

        banner("9. High availability — active owns, standby refuses (fail-closed)")
        lease_db = os.path.join(tmp, "lease.sqlite")
        a = Server(ServerConfig(port=0, profile="host", host_id="ha-host", store=lease_db,
                                ha_enabled=True))
        a.attach(ExistingHostPort(build_host(os.path.join(tmp, "a.sqlite"), "ha-host")))
        a.start()
        b = Server(ServerConfig(port=0, profile="host", host_id="ha-host", store=lease_db,
                                ha_enabled=True))
        b.attach(ExistingHostPort(build_host(os.path.join(tmp, "b.sqlite"), "ha-host")))
        b.start()
        try:
            print("instance A role:", a.role(), " instance B role:", b.role())
            sa, oa = POST(a.port, {"capability_id": "greet.hello", "payload": {"name": "x"}}, key="key-a")
            print("invoke on ACTIVE  (A) ->", sa, oa.get("outcome"), oa.get("data"))
            sb, ob = POST(b.port, {"capability_id": "greet.hello", "payload": {"name": "x"}}, key="key-a")
            print("invoke on STANDBY (B) ->", sb, ob.get("error", {}).get("code"))
        finally:
            a.stop()
            b.stop()

        banner("Demo complete — one server, chp-core-only, every feature live.")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
