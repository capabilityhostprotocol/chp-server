# chp-server

**A governed HTTP server for capabilities — every call is admission-gated and recorded as
signed, replayable evidence. One dependency. Runs anywhere.**

`chp-server` is the reference implementation of the CHP *server* role. You bring a set of
capabilities (plain Python functions); it serves them over HTTP behind the full CHP invocation
pipeline: identity, admission, execution, and an append-only evidence chain — plus truthful
feature negotiation, absolute deadlines, tenant-scoped evidence, capability resolution, and
active/standby HA. The base install depends on **`chp-core` and nothing else**.

```bash
pip install chp-server chp-core
```

---

## 60-second quickstart — surface a capability

```python
from chp_server import CapabilityServer

app = CapabilityServer("my-host")

@app.capability("greet.hello")
def hello(name: str = "world") -> dict:
    "Greet a name."
    return {"greeting": f"hello, {name}"}

app.run(port=8800)
```

The **docstring becomes the description**, the **type hints become the input schema** — and
the pipeline *enforces* it, denying a malformed call before your function runs — and payload
fields arrive as **keyword arguments**. No descriptor boilerplate, no request parsing, no schema
by hand.

```console
$ curl -s localhost:8800/invoke \
    -H 'Content-Type: application/json' \
    -d '{"capability_id": "greet.hello", "payload": {"name": "CHP"}}'
{"outcome": "success",
 "data": {"greeting": "hello, CHP"},
 "correlation": {"correlation_id": "corr_b11dc07c…"},
 "evidence_ids": ["evt_…", "evt_…"]}          # a signed, append-only chain

$ curl -s localhost:8800/replay/corr_b11dc07c…
{"events": [{"event_type": "execution_started"}, {"event_type": "execution_completed"}]}
```

That invocation was admission-gated, executed, and **recorded as a hash-chained evidence trail
you can replay** — without you writing a line of middleware. `CapabilityServer` is thin sugar over
the explicit host/attachment API you drop to when you need resolution, federation, or the
distribute path (see the [serving guide](docs/serving-capabilities.md)). Prefer no code?

```bash
chp-server new mycaps           # scaffold a runnable starter you own, then: python mycaps.py
chp-server serve --example      # a live server with sample capabilities, curl-able at once
chp-server adapters             # list installed chp-adapter-* capability sets you can compose()
chp serve                       # a truthful protocol-only server; attach capabilities when ready
```

---

## What you get that you'd otherwise build yourself

Everything below is real and exercised end-to-end by [`examples/demo.py`](examples/README.md):

| You get | What it means |
|---|---|
| **Governed invocation + evidence** | Every `/invoke` runs the full CHP pipeline and emits a signed, replayable chain (`/replay/{correlation}`). Nothing executes un-recorded. |
| **Truthful feature negotiation** | `GET /server` (Server.Describe) reports each feature's *real* state (`ready` / `unsupported`), computed from live attachment health — never faked from package presence. |
| **Honest long-running work** | A capability that can't answer yet returns `indeterminate` — not a fabricated success — and stays queryable without holding a connection open. |
| **Absolute deadlines** | Send a `deadline`; a stale request is denied `deadline_exceeded` *before any effect runs*. |
| **Tenant-scoped evidence** | Callers can only replay their own correlations; someone else's is `404`, not disclosed. |
| **Restricted visibility** | A capability's `allowed_actors` policy hides it from discovery for callers outside it. |
| **Capability resolution** | `GET /resolve` answers *where* a capability is served (endpoints), honoring lease/freshness — the basis for "invocable anywhere." |
| **Active/standby HA** | Two instances of one logical host contend for an ownership lease; the active admits work, the standby fails closed with `server_not_active`. |
| **Three discovery surfaces** | `/.well-known/chp` (bootstrap), `/capabilities.txt` (public hint), and authorized live `/host` — each with a distinct, honest purpose. |

### See it all at once

```bash
python examples/demo.py
```

One self-contained script stands up real servers and walks every surface above with a narrated
trace — needing only `chp-core` + `chp-server`. See [`examples/README.md`](examples/README.md).

---

## The one-dependency principle

The base install pulls in **only `chp-core`**. That is a deliberate contract, not an accident:
a CHP server must be installable and runnable where every other CHP package is absent. Richer
behavior — host exposure, local execution, resolution, MCP import/export, federation,
Platform services — attaches through optional packages that register in the `chp_server.ports`
entry-point group. **Feature truth is computed from attachment health, never from what happens
to be installed**, so `GET /server` never overstates what the server can actually do.

```python
server.attach(ExistingHostPort(host))          # a pre-built governed host
server.attach(DirectoryResolutionPort([...]))  # answer GET /resolve
# ...MCP, federation, Platform, artifacts — each behind its own port role
```

## Profiles — fail-closed by construction

A **profile** declares which port roles a server *requires*; boot fails closed if one is missing,
so a server never silently comes up under-provisioned.

| Profile | Requires | For |
|---|---|---|
| `protocol-only` (default) | — | the pure protocol surface; everything optional reports `unsupported` |
| `host` | a governed host | serving your own capabilities (the quickstart above) |
| `local` | host + execution | full local admission→execute→evidence |
| `standalone` | + catalog/resolution | a self-describing single node |
| `managed` / `edge` / `gateway` | Platform / federation roles | control-plane-backed and multi-host topologies |

## Endpoints

`GET /health` · `GET /ready` (reports role) · `GET /server` (Describe) · `GET /host` (authorized
discovery) · `GET /capabilities` · `POST /invoke` · `GET /replay/{correlation}` · `GET /resolve` ·
`GET /.well-known/chp` · `GET /capabilities.txt`

---

## Learn more

- **Serve capabilities of your own:** [`docs/serving-capabilities.md`](docs/serving-capabilities.md)
  — capability anatomy, the embed and distribute paths, evidence, policy, auth, deadlines.
- **For LLMs & agents:** [`docs/agent-integration.md`](docs/agent-integration.md) — a recipe to
  CHP-enable a codebase (wrap existing functions as governed capabilities).
- **Expose it safely:** [`docs/public-exposure.md`](docs/public-exposure.md) — ingress auth/mTLS,
  the governed ingress route, egress governance.
- **Full walkthrough:** [`examples/demo.py`](examples/demo.py) + [its guide](examples/README.md)
- **Protocol:** built on [`chp-core`](https://github.com/capabilityhostprotocol/chp-core), the
  canonical CHP implementation (identity, evidence, signing, the 12-gate pipeline).
- **Public API:** `CapabilityServer`, `Server`, `ServerConfig`, `ExistingHostPort`,
  `DirectoryResolutionPort`, `FeatureRegistry`, `PROFILES` — see `chp_server.__all__`.

Licensed Apache-2.0 (see `LICENSE`, `NOTICE`). This repository is a read-only public mirror;
development happens in the private CHP workspace and syncs here.
