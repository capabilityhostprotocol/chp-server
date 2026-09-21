# llms-install.md — set up a chp-server node (agent-oriented)

> For an AI coding agent (Claude Code, Cursor, Cline, …). Execute these steps **in order**;
> each ends in a check you can verify before continuing. You should be able to stand up a
> working node from **only this file**. Human-facing detail lives in `README.md` and
> [`docs/serving-capabilities.md`](docs/serving-capabilities.md).

## What this installs
`chp-server` — a **node** that serves capabilities (plain Python functions) over HTTP behind the
full CHP invocation pipeline: every call is admission-gated and recorded as a signed, replayable
evidence chain. It pulls exactly **one** CHP package, `chp-core` (with the `schema` extra).

## Requirements
- **Python 3.11+** (`python3 --version` → 3.11 or higher). If lower, stop and tell the operator.
- Network access to PyPI for `pip install`.
- A free TCP port (default `8800`).

## Step 1 — Install
```bash
python3 -m pip install chp-server
```
**Verify:** `python3 -c "import chp_server, chp_core; print('ok')"` prints `ok`.

## Step 2 — Stand up a node (fastest check)
```bash
chp-server serve --example --port 8800
```
This starts a live node with sample capabilities (`greet.hello`, `math.add`, `time.now`) attached.
Leave it running (background it, or use a second shell for Step 3).
**Verify:** `curl -s http://127.0.0.1:8800/health` returns HTTP 200.

## Step 3 — Prove a governed invocation
```bash
curl -s http://127.0.0.1:8800/invoke -H 'Content-Type: application/json' \
  -d '{"capability_id": "greet.hello", "payload": {"name": "CHP"}}'
```
**Verify:** the JSON response has `"outcome": "success"` and a `correlation.correlation_id`.
Then replay that call's signed evidence chain (substitute the id you got):
```bash
curl -s http://127.0.0.1:8800/replay/<correlation_id> | chp-server replay
```
**Verify:** you see `execution_started` and `execution_completed` events. The install is proven —
a call ran the full pipeline and left a replayable, hash-chained evidence trail.

## Step 4 — Serve the operator's own capabilities
Create `mycaps.py` (or run `chp-server new mycaps` to scaffold it):
```python
from chp_server import CapabilityServer

app = CapabilityServer("my-host")

@app.capability("greet.hello")
def hello(name: str = "world") -> dict:
    "Greet a name."
    return {"greeting": f"hello, {name}"}

app.run(port=8800)
```
Run it with `python3 mycaps.py`. The docstring becomes the description, the type hints become the
(enforced) input schema, and payload fields arrive as keyword arguments. Re-run Step 3 against it.

## Commands & endpoints
- Commands: `chp-server serve [--example] [--port N] [--profile P]`, `chp-server new <name>`,
  `chp-server adapters` (list installable capability sets to `compose()`), `chp-server describe`,
  `chp-server replay`, and `chp serve` (protocol-only node; attach capabilities when ready).
- Endpoints: `GET /health` · `GET /ready` · `GET /server` (Server.Describe) · `GET /host` ·
  `GET /capabilities` · `POST /invoke` · `GET /replay/{correlation}` · `GET /resolve` ·
  `GET /.well-known/chp` · `GET /capabilities.txt`.

## Operational notes
- **Truthful features:** `GET /server` reports each feature's real state from live attachment
  health — never faked from what's installed. Anything unsupported answers `unsupported`, not a
  fabricated success. Report what it actually says; do not assume a feature is present.
- **Profiles fail closed:** the default is `protocol-only`; `--example` uses the `host` profile.
  A profile that requires an attachment the environment lacks **fails to boot** by design — that
  is correct, not a bug to work around.
- **Access control** (optional): `export CHP_HOST_API_KEYS="alice:key-a"` then send
  `-H 'X-CHP-Key: key-a'`. A caller can only `/replay` its own correlations.
- Do **not** add dependencies beyond `chp-server` to make a step pass; the one-dependency contract
  (chp-core only) is deliberate. If a step fails, report the exact command and output.

## Support
- Human guide: `README.md` · Serve your own: [`docs/serving-capabilities.md`](docs/serving-capabilities.md)
- Why this is a node in a network: [`docs/the-network.md`](docs/the-network.md)
- Governed setup through a CHP host (evidenced install): [`agent/`](agent/)
- Protocol: [`chp-core`](https://github.com/capabilityhostprotocol/chp-core)
