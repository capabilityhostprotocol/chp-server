# Serving your own capabilities

`chp-server` turns a set of capabilities — plain Python functions — into a governed
HTTP service: every call is admission-gated, executed, and recorded as a signed,
replayable evidence chain. This guide shows how to serve capabilities of your own.

Serving is **rung 2 of running a node**: what you expose here is what other nodes can later
discover, compose, and — as you opt in — federate with (see [the network](the-network.md)).

There are two paths:

- **[Embed](#a-embed-capabilities-in-your-program)** — build a host in your own program and
  serve it. Best for an application that owns its capabilities. *(Start here.)*
- **[Distribute](#b-distribute-capabilities-as-an-attachment-package)** — ship your capabilities
  as a package that any operator can attach to their server. Best for reusable capability sets.

Both need only `chp-core` + `chp-server`.

---

## A. Embed capabilities in your program

> **Fastest start:** `chp-server new mycaps` scaffolds a runnable version of everything in this
> section into `mycaps.py`; `python mycaps.py` serves it. Read on to understand what it generated.

### The clean path: `CapabilityServer`

For most cases, decorate plain functions and serve them — the docstring becomes the description,
the type hints become the (enforced) input schema, and payload fields arrive as keyword arguments:

```python
from chp_server import CapabilityServer

app = CapabilityServer("my-host")

@app.capability("math.add")
def add(a: int, b: int) -> dict:
    """Add two numbers."""
    return {"sum": a + b}

app.run(port=8800)          # serve over HTTP (blocking)
```

That's it — `curl localhost:8800/invoke -d '{"capability_id":"math.add","payload":{"a":2,"b":3}}'`
returns a signed, replayable result, and a malformed call (`"a": "two"`) is **denied**
(`input_schema_validation_failed`) before `add` runs. A full runnable version with three
capabilities is [`examples/quickstart.py`](../examples/quickstart.py).

`app.capability(id, *, version="1.0.0", description=None, input_schema=None, **descriptor_fields)`
lets you set the version, override the description or schema (pass a dict, or `False` to declare
none), and pass any other descriptor field (`policy`, `risk`, `tags`, `timeout_s`, …).
`app.host` is the underlying host; `app.serving(**kw)` returns a `Server` you start yourself.

`CapabilityServer` is thin sugar over the API below — reach for it directly when you need
resolution, federation, the distribute path, or a custom evidence store. The rest of this section
is what the decorator does under the hood.

### 1. Define a capability

A capability is a **descriptor** (its contract) plus a **handler** (the function that runs):

```python
from chp_core import CapabilityDescriptor

GREET = CapabilityDescriptor(
    id="greet.hello",
    version="1.0.0",                      # semver; (id, version) is the identity
    description="Greet a name.",
    input_schema={"type": "object",       # optional JSON Schema for the payload
                  "properties": {"name": {"type": "string"}}},
)

def greet(ctx, payload):                   # handler: (context, payload) -> data
    return {"greeting": f"hello, {payload.get('name', 'world')}"}
```

**The handler contract:**

- Signature is `(ctx, payload)`. `payload` is the caller's input (a dict). Return a JSON-able
  dict — that's the invocation's `data`.
- `ctx` is the execution context: `ctx.correlation_id`, `ctx.subject` (the verified caller),
  `ctx.envelope`, and `ctx.emit(...)` for custom evidence (see below).
- **Sync or async — both work.** Return a value directly, or write `async def` and return a
  coroutine; the host awaits it. Async generators stream. (See [Sync or async?](#sync-or-async).)
- To signal work that can't complete now, **raise `IndeterminateExecution`** — the honest
  outcome, never a fabricated success (see [Deferred work](#4-long-running--deferred-work)).
- To deny a *post-admission* authority failure the gates can't see — a downstream provider returns
  401/403, a credential is absent or revoked — **raise `CapabilityDenied`**; the host records
  `outcome: "denied"`, not a failure. *Pre*-admission denials (policy, auth, deadline) remain the
  pipeline's job, not the handler's (see [Denials vs failures](#denials-vs-failures)).

### 2. Register and serve

```python
from chp_core import LocalCapabilityHost, SQLiteEvidenceStore
from chp_server import Server

host = LocalCapabilityHost("my-host", store=SQLiteEvidenceStore("host.sqlite"))
host.register(GREET, greet)               # descriptor + handler

server = Server.serving(host, port=8800, store="server.sqlite")   # one line to serve
server.start()
server.serve_forever()
```

`Server.serving(host, ...)` projects a pre-built `LocalCapabilityHost` — one governed object that
fulfils the Host + Admission + Execution + Evidence roles — through the server without rebuilding or
mutating it. It defaults to the `host` profile, which requires exactly that; the server **fails
closed at boot** if it's missing.

To add *more* attachments (e.g. a resolver so `GET /resolve` works), use the explicit form —
`Server.serving` is sugar for it:

```python
from chp_server import Server, ServerConfig, ExistingHostPort, DirectoryResolutionPort

server = Server(ServerConfig(port=8800, profile="host", store="server.sqlite"))
server.attach(ExistingHostPort(host))
server.attach(DirectoryResolutionPort([...]))     # answer GET /resolve
```

### 3. Invoke it

```console
$ curl -s localhost:8800/invoke -H 'Content-Type: application/json' \
    -d '{"capability_id": "greet.hello", "payload": {"name": "CHP"}}'
{"outcome": "success",
 "data": {"greeting": "hello, CHP"},
 "correlation": {"correlation_id": "corr_…"},
 "evidence_ids": ["evt_…", "evt_…"]}

$ curl -s localhost:8800/replay/corr_…      # the signed, append-only chain
{"events": [{"event_type": "execution_started"}, {"event_type": "execution_completed"}]}
```

> Want a running server to poke at first? `chp-server serve --example` attaches
> `greet.hello`, `math.add` and `time.now` so a fresh install is live immediately.

### 4. Long-running & deferred work

If a capability can't produce a result synchronously (human review, an async job), **raise
`IndeterminateExecution`** — the invocation resolves as `indeterminate`, is recorded, and stays
queryable later without holding a connection open:

```python
from chp_core import IndeterminateExecution

def review(ctx, payload):
    # ... enqueue the work, record a ticket ...
    raise IndeterminateExecution("awaiting human reviewer")
```

An `indeterminate` outcome is honest ("not done yet"), never a fake `success`.

### Sync or async?

The host is **async at its core** (`ainvoke_envelope` / `ainvoke_stream`), with a **synchronous
`invoke()` convenience wrapper** for scripts. The HTTP binding is a **thread-per-request** server
that runs the async pipeline per request. Practically:

- Write handlers **sync or async** — whichever suits the work. A blocking sync handler is fine;
  it runs in its request's own worker thread.
- Call `host.invoke(...)` from ordinary code, but from inside an event loop use
  `await host.ainvoke(...)` — the sync wrapper refuses to run inside a running loop.

### 5. Custom evidence

Beyond the host-owned lifecycle events (`execution_started` / `execution_completed` / …), emit
your own **domain** events from a handler:

```python
def transcode(ctx, payload):
    ctx.emit("transcode_started", {"codec": payload["codec"]})
    # ... do the work ...
    return {"bytes": 1234}
```

Emit *domain-specific* event types. Do **not** emit the reserved lifecycle events — the host owns
those, and emitting them produces duplicate, outcome-less terminal events.

---

## Access control

### Capability visibility (policy)

Attach a `PolicyDescriptor` to restrict who may discover and invoke a capability:

```python
from chp_core.types import PolicyDescriptor

host.register(
    CapabilityDescriptor(id="secret.ping", version="1.0.0", description="restricted",
                         policy=PolicyDescriptor(allowed_actors=["alice"])),
    lambda ctx, payload: {"pong": True},
)
```

`secret.ping` is then hidden from `GET /host` for any caller outside `allowed_actors`, and
invocation by others is denied — enforced by the pipeline, uniformly.

### Caller authentication

Configure API keys via the `CHP_HOST_API_KEYS` environment variable (`actor:key` pairs); callers
present `X-CHP-Key`:

```bash
export CHP_HOST_API_KEYS="alice:key-a,bob:key-b"
```
```console
$ curl -s localhost:8800/invoke -H 'X-CHP-Key: key-a' -H 'Content-Type: application/json' \
    -d '{"capability_id": "greet.hello", "payload": {"name": "CHP"}}'
```

The authenticated actor becomes the invocation's principal — it drives visibility and scopes
evidence: a caller can only `/replay` its **own** correlations; another's is `404`, not disclosed.

### Deadlines

A caller can attach an absolute `deadline` (ISO-8601) to the invocation; a request past its
deadline is denied `deadline_exceeded` **before any effect runs** — no partial work, no wasted
side effects:

```console
$ curl -s localhost:8800/invoke -H 'Content-Type: application/json' \
    -d '{"capability_id": "greet.hello", "payload": {}, "deadline": "2020-01-01T00:00:00Z"}'
{"outcome": "denied", "denial": {"code": "deadline_exceeded"}}
```

### Denials vs failures

There are three distinct non-success outcomes, and it matters which one a handler produces:

- **Pipeline denials** — unauthorized actor, unmet policy, exceeded deadline, unsupported feature —
  are decided by the **gates before the handler runs**, and surface as `outcome: "denied"`. You don't
  write these; express the rule as policy/config and let the gate enforce it.
- **Handler denials** — a *post-admission* authority failure the gates cannot see (a downstream
  provider returns 401/403; a credential is absent or revoked) — are raised by the handler with
  **`CapabilityDenied`**, and recorded as `outcome: "denied"` with your `denial.code` (not a failure):

  ```python
  from chp_core import CapabilityDenied

  def fetch(ctx, payload):
      resp = call_provider(...)
      if resp.status == 401:
          raise CapabilityDenied("provider rejected the credential", code="unauthorized")
      return {"data": resp.body}
  ```

  This keeps "not authorized" distinct from "authorized but broke."
- **Failures** — any *other* unexpected error the handler raises becomes `outcome: "failure"`.

So a handler returns `data`, or raises `IndeterminateExecution` (not done yet), `CapabilityDenied`
(not authorized), or lets an unexpected error fail. A plain exception is always a failure, never a
denial — reach for `CapabilityDenied` deliberately.

---

## B. Distribute capabilities as an attachment package

To let *any* operator attach your capabilities, ship an **attachment provider** that registers in
the `chp_server.ports` entry-point group.

### 1. Implement the attachment surface

An attachment is any object exposing this minimum surface (a `Protocol`):

```python
class MyCaps:
    roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
    source = "local"                       # local | remote | platform | adapter

    def __init__(self, store="caps.sqlite"):
        self._host = LocalCapabilityHost("my-caps", store=SQLiteEvidenceStore(store))
        self._host.register(GREET, greet)  # ... your capabilities ...

    def validate(self) -> None: ...        # raise on bad configuration
    def start(self) -> None: ...
    def health(self) -> str: return "ready"    # "ready" | "degraded" | "unavailable"
    def stop(self) -> None: ...
```

`roles` must be a subset of the canonical `PORT_ROLES`. An attachment may declare
`requires = (<role>, ...)` to start only after another attachment fulfils those roles
(dependency-ordered start; cycles are a boot error, not a hang). `FeatureRegistry` reads feature
truth from `health()`, so `GET /server` reflects what your attachment can *actually* do.

### 2. Register the entry point

In your package's `pyproject.toml`, point a factory at the `chp_server.ports` group:

```toml
[project.entry-points."chp_server.ports"]
my-caps = "my_package.attach:MyCaps"
```

### 3. The operator opts in

Installing your package is **not** enough to enable it — installed code is never enabling
authority. The operator lists the attachment (and any kwargs) in their server config's
`attachments` section; only listed names load:

```json
{ "profile": "host",
  "attachments": { "my-caps": { "store": "/var/lib/chp/my-caps.sqlite" } } }
```

The server calls your factory as `factory(**kwargs)`, attaches the result, runs `validate()`,
starts attachments in dependency order, and computes feature truth from their health.

---

## Expose your capabilities to MCP agents

Your capabilities are already usable by MCP agents (Claude, Cursor, …) — you don't build an MCP
server. chp-core ships one generic bridge, `chp_core.mcp_bridge`, that projects any host's
capabilities as MCP tools (reusing the same descriptor→tool projection as the Anthropic/OpenAI
bridges). It composes with everything above:

```python
import asyncio
from chp_core.mcp_bridge import run_stdio        # or serve_mcp(host) for the Server object

app = CapabilityServer("my-host")
# ... @app.capability(...) definitions ...
asyncio.run(run_stdio(app.host))                 # serve over MCP (stdio); needs chp-core[mcp]
```

Define once with `CapabilityServer`; serve over HTTP with `app.run()` and/or over MCP with
`run_stdio(app.host)` — same governed host, same evidence.

## Profiles (fail-closed)

A **profile** declares which port roles a server requires; boot fails closed if one is absent, so
a server never silently comes up under-provisioned. `protocol-only` (default) is the pure protocol
surface; `host` serves your capabilities (this guide); `local`, `standalone`, `managed`, `edge`,
`gateway` layer on execution, resolution, and multi-host topologies. See the package README.

## Testing your capabilities

Because a capability is a plain function on a host, test the host directly — no HTTP needed:

```python
def test_greet():
    host = LocalCapabilityHost("t", store=SQLiteEvidenceStore(":memory:"))
    host.register(GREET, greet)
    result = host.invoke("greet.hello", {"name": "CHP"})
    assert result.success and result.data == {"greeting": "hello, CHP"}
```

For the HTTP surface end to end, [`examples/demo.py`](../examples/demo.py) stands up real servers
and exercises invocation, evidence, deadlines, visibility, resolution, and HA in one script.

## Next

- **[`agent-integration.md`](agent-integration.md)** — a recipe for LLMs & agents to CHP-enable a
  codebase (wrap existing functions as capabilities, serve over HTTP/MCP).
- **[`public-exposure.md`](public-exposure.md)** — exposing a server safely: ingress auth/mTLS,
  the governed ingress route, and egress governance.
- **[`the-network.md`](the-network.md)** — why this is a node in a network: the two axes, what
  governed federation unlocks, and the honest limits.
- **[`examples/demo.py`](../examples/demo.py)** — every governed surface, runnable.
- **[`chp-core`](https://github.com/capabilityhostprotocol/chp-core)** — the descriptor,
  evidence, signing, and the 12-gate invocation pipeline.
- **Public API** — `Server`, `ServerConfig`, `ExistingHostPort`, `DirectoryResolutionPort`,
  `PROFILES`, `FeatureRegistry` (`chp_server.__all__`).
