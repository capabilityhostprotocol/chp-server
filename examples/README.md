# chp-server examples

## `quickstart.py` — the clean way to surface capabilities

The decorator-first surface: three plain functions become governed capabilities via
`CapabilityServer` — docstring as description, type hints as the enforced input schema,
payload fields as keyword arguments. Start here.

```bash
pip install chp-server chp-core
python quickstart.py            # then curl the endpoints it prints
```

## `compose.py` — serve an existing adapter + your own capability

Adapter-first composition: one `CapabilityServer` serves the real `chp-adapter-filesystem`
capabilities (scoped to a temp dir) **and** a hand-written `text.wordcount`, all over one
governed host. Don't reimplement filesystem/http/secrets — `app.compose(adapter)` them.

```bash
pip install chp-server chp-core chp-adapter-filesystem
python compose.py
```

## `import_mcp.py` — import an MCP server as governed capabilities

The adapter-first way to consume MCP: `app.compose(MCPAdapter(...))` turns every tool of an
external MCP server into a governed capability `chp.adapters.mcp.<server>.<tool>` — the tool's
own JSON Schema enforced pre-invocation (a bad-typed call is **denied before the tool runs**),
every call evidenced. Runs with no external server (an in-process stand-in session); a real
server is one line: `MCPServerConfig(command=...)` or `url=...`.

```bash
pip install chp-server chp-core chp-adapter-mcp
python import_mcp.py
```

## `demo.py` — end-to-end "invocable anywhere, on any host"

A single runnable script that stands up real `chp-server` instances serving real
capabilities and then acts as a client over HTTP, exercising every production feature
in one narrated walkthrough. It needs **only** `chp-core` + `chp-server` — the whole
point of the distribution.

```bash
pip install chp-server chp-core
python demo.py
```

It demonstrates, in order:

1. **Liveness / readiness / identity** — `/health`, `/ready` (reports `role`), and the
   public signed host identity at `/.well-known/chp-identity`.
2. **Truthful feature negotiation** — `Server.Describe` (`/server`): distribution vs
   protocol version, active profile, and each semantic feature's real state
   (`capability.discovery` ready, `mcp.import` unsupported — never faked).
3. **Three distinct discovery surfaces** — `/.well-known/chp` (bootstrap pointer),
   `/capabilities.txt` (public non-authoritative hint), and authorized live `/host`
   (a restricted capability is hidden from a caller outside its `allowed_actors`).
4. **Governed invocation + evidence** — `/invoke` returns a signed-chain outcome; the
   evidence is replayable at `/replay/{correlation}`.
5. **Honest long-running work** — a human-review capability returns `indeterminate`
   (never a fake success), queryable later without a held connection.
6. **Absolute deadlines** — an invocation past its deadline is denied `deadline_exceeded`
   *before any effect runs* (proposal 0052).
7. **Tenant-scoped evidence query** — one caller cannot replay another's evidence (404).
8. **Capability resolution** — `/resolve` answers *where* a capability is served
   (endpoints), honoring lease/freshness.
9. **High availability** — two instances of one logical Host contend for an ownership
   lease; the **active** admits work, the **standby** refuses `server_not_active`
   (fail-closed).

The script is self-contained (ephemeral ports, temp stores, cleans up) and prints a
section-by-section trace so you can read exactly what each governed surface returned.
