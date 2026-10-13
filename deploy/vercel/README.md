# CHP server on Vercel

Run a governed CHP host as a Vercel Python Function — reachable over HTTPS as a **CONNECT node**
by any mesh peer (`RemoteCapabilityHost`), with the full chp-core governance surface
(`/invoke`, `/host`, `/replay`, `/verify`, `/health`) served by one function.

See `../../../docs/product/chp-server-on-vercel/DESIGN.md` for the architecture and the
slice plan (issues `47d0e82`, `b51d14e`, `cf155d2`).

## How it works

`api/index.py` is a FastAPI `app` (Vercel auto-detects it). A catch-all route (`vercel.json`
rewrites `"/(.*)" -> "/api/index"`) funnels every request into `chp_vercel_host.dispatch`, which
drives the **real chp-core request handler** through an in-memory socket — so auth, version
negotiation, capability scope, the 12-gate invocation pipeline, evidence and replay all run
verbatim from chp-core. No governance is re-implemented here; only transport is adapted.

The host is built once per cold start (`build_host`) with its baked capabilities and evidence
store, and reused across warm invocations.

## Files
- `api/index.py` — FastAPI entrypoint (catch-all → dispatch).
- `chp_vercel_host/__init__.py` — `build_host()` + the `dispatch()` in-memory-socket shim.
- `vercel.json` — catch-all rewrite + `maxDuration: 300`.
- `requirements.txt` — `fastapi`, `chp-server`.
- `tests/test_dispatch.py` — offline proof (no network): invoke → replay → `verify_chain`.

## Configuration (env)

| Var | Purpose |
|-----|---------|
| `CHP_SERVER_HOST_ID` | Host id (default `chp-vercel`). |
| `CHP_EVIDENCE_PATH` | Evidence SQLite path (default `/tmp/chp-vercel-evidence.sqlite`). |
| `CHP_HOST_API_KEYS` | `name:key[:scope]` per-caller keys — binds a verified subject. |
| `CHP_HOST_API_KEY` | Single shared key (anonymous authenticated). |
| `CHP_HOST_TOKEN_KEYS` | `sub:pubkey,…` — ed25519 signed-bearer-token auth. |

Set secrets with `vercel env add <NAME> production --sensitive`. With no auth env configured the
host is open (local-first default) — always configure a key for a public deployment.

## Deploy

Governed path (preferred): `activate(DEPLOY, target=vercel)` → `chp.adapters.vercel.trigger_deploy`
(see the Phase-2 activation registry). Direct CLI for local iteration: `vercel deploy` from this
directory (`vercel dev` to run locally; needs Vercel CLI ≥ 48.1.8 and a local venv with
`requirements.txt`).

## Verify live (from a mesh node)

```python
from chp_core.http import RemoteCapabilityHost
h = RemoteCapabilityHost("https://<deployment>.vercel.app", api_key="<key>")
print(h.invoke_envelope({"capability_id": "demo.echo", "payload": {"message": "hi"}}))
# then GET /replay/<correlation_id> or h.replay_result(<corr>) and verify_chain()
```

## Constraints (slice 1)
- **Evidence is `/tmp` SQLite** — durable within a warm instance (real governed execution +
  a verifiable chain per invocation), **not across cold starts**. Durable external store
  (Neon Postgres via the store-object injection on `CapabilityServer`) is slice 1b.
- `maxDuration` 300s — long/retryable work needs the Workflow/Queues async lane (future).
- No persistent process — no zenoh peer, no in-process HA/drain/streaming.
- mTLS is unavailable behind Vercel's TLS edge — header auth only.
- Signing degrades to `hash-chain` without a persistent key (inject via env in slice 1b).
