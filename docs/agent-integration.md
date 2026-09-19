# Integrating CHP Server into a codebase — a recipe for LLMs & agents

You are working in a codebase and want to expose some of its functions as **governed,
network-invocable capabilities** — with admission control, type-checked inputs, and a signed,
replayable evidence trail — using `chp-server`. This is the step-by-step recipe. It needs only
`chp-core` + `chp-server`.

## The recipe

1. **Install:** `pip install chp-server chp-core`
2. **Pick functions to expose.** Good candidates do one clear thing, take JSON-able arguments,
   and return a dict. Prefer functions you can name, type-hint, and describe in a sentence.
3. **Write a serve module** (e.g. `serve_chp.py`). You can wrap functions **without editing their
   source** — applying the decorator to an existing function is enough:

   ```python
   from chp_server import CapabilityServer
   from mypackage import add, summarize            # your existing functions

   app = CapabilityServer("my-service")

   app.capability("math.add")(add)                 # wrap existing funcs — no source edit
   app.capability("text.summarize")(summarize)

   @app.capability("report.fetch")                 # or decorate at the definition site
   def report_fetch(report_id: str) -> dict:
       """Fetch a report by id."""
       ...
       return {"report": ...}

   if __name__ == "__main__":
       app.run(port=8800)                          # serve over HTTP (blocking)
   ```
4. **Run it:** `python serve_chp.py`. Every wrapped function is now a governed capability at
   `POST /invoke`.

## Rules for shaping each capability

- **Name it `namespace.verb`** — dotted, lowercase (`invoice.create`, `text.summarize`,
  `math.add`).
- **Type-hint the parameters.** The hints become the input schema, and **the pipeline denies a
  malformed call before your function runs** (`def add(a: int, b: int) -> dict` → a string `a` is
  denied `input_schema_validation_failed`). This is free input validation — use it.
- **Docstring it.** The first line becomes the capability's description in discovery.
- **Return a JSON-able dict.** Payload fields arrive as **keyword arguments** — write
  `def add(a, b)`, not `def add(payload)`.
- **Deny, don't fail, for authority problems.** If a function hits a provider 401/403 or a missing
  credential, `raise CapabilityDenied("provider rejected the credential", code="unauthorized")`
  (`from chp_core import CapabilityDenied`) → recorded as `outcome: denied`, not a failure.
- **Defer honestly.** If work can't finish synchronously, `raise IndeterminateExecution("…")` —
  never fabricate a success.
- **Do not expose** functions you can't type or describe, or with unbounded/unclear side effects,
  without reading [`serving-capabilities.md`](serving-capabilities.md) first (side effects,
  policy, deadlines).

## Compose existing adapters — don't reimplement

Before you write a function, check whether a **`chp-adapter-*`** already does it. CHP ships an
adapter ecosystem — git, github, http, filesystem, secrets, huggingface, radicle, jobs, and more
— **one governed implementation of each domain capability, reused everywhere.** A server composes
whatever mix it needs: your own functions *and* existing adapters.

```python
from chp_server import CapabilityServer
from chp_adapter_http import HttpAdapter          # an existing, governed capability set

app = CapabilityServer("my-service")

@app.capability("report.summarize")               # your own capability
def summarize(text: str) -> dict:
    """Summarize text."""
    ...

app.compose(HttpAdapter())                         # + reuse the http adapter's capabilities
app.run(port=8800)
```

`app.compose(adapter)` registers all of an adapter's capabilities onto this server — served,
governed, and evidenced identically to your own. **This is the rule, not an optimization:**
reaching for a hand-written HTTP / git / secrets function when an adapter exists siloes the value
and drifts from the protocol. If the capability you need has *no* adapter yet, the right move is
to add it once as a `chp-adapter-*` (so every host gains it), not to bury it in one server.

## The adapter library — what's composable

CHP ships **120+ `chp-adapter-*`** capability sets — one governed implementation each — so you
rarely start from scratch. The families:

- **Dev / SCM / CI:** git · github · radicle · ci · release · devloop · capscan · conformance
- **Cloud / infra / compute:** aws · gcp · azure · kubernetes · container · sandbox · process · launchd · service · host
- **Data / storage:** filesystem · postgres · spreadsheet · document-store · vector · memory · knowledge-graph · rag · notes
- **AI / models / inference:** huggingface · mlx · vllm · sglang · tei · local-llm · llm · colibri · freetoken · vlm · yolo · smolagents · eval
- **Web / protocols:** http · browser · websearch · scrapegraph · graphql · grpc · kafka · nats · webhook · openapi · asyncapi
- **Agent protocols:** a2a · mcp · router
- **Comms:** email · slack · matrix · messages · notification · calendar · postiz
- **Exposure / mesh / identity:** ingress · tailscale · meshauth · auth · secrets · telemetry · monitor · scout · stewards · registry
- **Governance / orchestration:** approval · delegation · planning · workflow · state-machine · composition · safety · audit · agency · organization
- **Business systems:** crm · twenty · notion · jira · linear · form
- **Legal vertical:** legal-billing / -document / -docket / -filing / -trust / … + clio · canlii · nexis

Two things to know when composing:

- **Adapters compose adapters.** `source`/`enrich` build on `scrapegraph`; `ingress` drives its
  proxy backend through `http`. Composing one governed capability may bring a governed chain — you
  never re-plumb the layer below.
- **Discover, don't hard-code.** The installed set is enumerable — run **`chp-server adapters`**
  (add `--verbose` for every capability id + description, or `--json` to parse it), or in code
  `chp_core.adapters.discover_adapters()`. Both read the `chp.adapters` entry-point group and list
  what's actually installed here — no rotting catalog. Ask what's available, `compose()` what you
  need, and add a new `chp-adapter-*` only if the capability genuinely doesn't exist yet.

## What you get for free

`POST /invoke` runs the full CHP pipeline: identity → admission → schema validation → execution,
and records a **signed, hash-chained evidence trail** replayable at `GET /replay/{correlation}`.
Discovery is truthful — `GET /host` (authorized), `GET /capabilities.txt` (public hint), and
`GET /server` (feature + version negotiation). You wrote functions; you did not write middleware.

## Serve the same capabilities over MCP

```python
import asyncio
from chp_core.mcp_bridge import run_stdio
asyncio.run(run_stdio(app.host))       # MCP tools for Claude/Cursor/…; needs chp-core[mcp]
```

Define once with `CapabilityServer`; serve over HTTP with `app.run()` and/or over MCP with
`run_stdio(app.host)` — same governed host, same evidence.

## Import an MCP server as governed capabilities

The other direction — consuming an existing MCP server — is **adapter-first**: compose
`chp-adapter-mcp`. It connects to the server, lists its tools, and turns each into a governed
capability `chp.adapters.mcp.<server>.<tool>` whose `input_schema` **is the tool's own JSON
Schema** — so a malformed call is denied *before the tool runs*, and every call is evidenced.

```python
from chp_server import CapabilityServer
from chp_adapter_mcp import MCPAdapter, MCPServerConfig

app = CapabilityServer("my-service")
app.compose(MCPAdapter(MCPServerConfig(                 # stdio server
    name="fs", command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"])))
# or an HTTP/SSE server: MCPServerConfig(name="x", url="https://…", headers={...})
app.run(port=8800)
```

You did **not** teach chp-server to speak MCP — you composed the one adapter that does, so any
MCP server (filesystem, github, a vendor's) arrives wrapped in CHP admission + schema
enforcement + a replayable evidence chain. Runnable end-to-end (no external server needed):
[`examples/import_mcp.py`](../examples/import_mcp.py).

## Exposing it beyond localhost — safely

Do **not** just bind to `0.0.0.0` and open a port. Put authentication in front and route through
the governed ingress, and never try to skip the gate pipeline (you can't — it always runs). See
[`public-exposure.md`](public-exposure.md).

## Go deeper

- [`serving-capabilities.md`](serving-capabilities.md) — the full capability + handler contract
  (policy, auth, deadlines, denials vs failures, the distribute path).
- [`examples/quickstart.py`](../examples/quickstart.py) — a runnable 3-capability server.
