# Capabilities to host

Your node serves plain functions — and it can **compose whole governed capability sets** from the
CHP adapter ecosystem. Each is one `pip install`; every capability runs the full CHP pipeline
(admission-gated, recorded as signed, replayable evidence) exactly like your own. Discover what's
installed with `chp-server adapters`; your running node advertises what it can do at
`/capabilities.txt`.

Every adapter below is **published on PyPI** and installs alongside `chp-server`. Capability
counts are what `chp-server adapters` reports — run it (or `--verbose`) for the exact ids.

## Zero extra install

`chp-core` already ships the **git** adapter, so a bare `pip install chp-server` node hosts **8
governed version-control capabilities** on its own — `chp-server adapters` shows `chp-git` with no
adapter package added.

## Compose one in three lines

```python
from chp_server import CapabilityServer
from chp_adapter_filesystem.adapter import FilesystemAdapter   # pip install chp-adapter-filesystem

app = CapabilityServer("my-host")
app.compose(FilesystemAdapter())      # 6 governed file capabilities, now served + evidenced
app.run(port=8800)
```

`chp-server adapters` then lists every capability the node serves; each invocation is admission-gated
and replayable. Compose as many as you need — one node served **63 capabilities** from 11 adapters
in testing.

## The catalog

### Files & data
| Adapter | Install | Your node can… |
|---|---|---|
| **filesystem** · 6 | `pip install chp-adapter-filesystem` | read, write, list, glob, grep, and extract files — governed |

### Dev & version control
| Adapter | Install | Your node can… |
|---|---|---|
| **git** · 8 | *(ships with `chp-core`)* | status, diff, log, commit, branch — governed VCS |
| **github** · 12 | `pip install chp-adapter-github` | issues, pull requests, repos, workflow runs |
| **radicle** · 19 | `pip install chp-adapter-radicle` | sovereign git — issues, patches, push/sync/seed |
| **process** · 1 | `pip install chp-adapter-process` | governed shell execution (policy-gated, HITL) |

### AI & inference
| Adapter | Install | Your node can… |
|---|---|---|
| **huggingface** | `pip install chp-adapter-huggingface` | models, inference, embeddings, datasets, image generation *(pulls torch)* |
| **mlx** | `pip install chp-adapter-mlx` | Apple-silicon local LLM — chat, generate, serve *(pulls mlx)* |

### Integration
| Adapter | Install | Your node can… |
|---|---|---|
| **http** · 1 | `pip install chp-adapter-http` | governed outbound HTTP requests (secret-injected headers, no secret in evidence) |
| **mcp** · dynamic | `pip install chp-adapter-mcp` | wrap **any MCP server's tools** as governed CHP capabilities (0 static; N once connected — see [`import_mcp.py`](../examples/import_mcp.py)) |

### Orchestration
| Adapter | Install | Your node can… |
|---|---|---|
| **composition** · 4 | `pip install chp-adapter-composition` | define and run multi-capability compositions |
| **jobs** · 4 | `pip install chp-adapter-jobs` | async work — submit → poll → result |
| **planning** · 4 | `pip install chp-adapter-planning` | plan, reflect, revise (agent planning) |
| **delegation** · 4 | `pip install chp-adapter-delegation` | governed work handoff — create, accept, complete |

## Discover & advertise

- **`chp-server adapters --verbose`** — every installed adapter and its capability ids, config-free.
- **`GET /capabilities.txt`** — your running node advertises what it can *do* (the action layer;
  see [`../capabilities.txt`](../capabilities.txt)).
- **`GET /host`** — the authoritative, access-controlled live catalog for a verified caller.

## Next

- **Compose mechanics** (embed vs distribute, config, evidence, policy):
  [`serving-capabilities.md`](serving-capabilities.md).
- **Wrap an existing MCP server**: [`../examples/import_mcp.py`](../examples/import_mcp.py).
- **Compose several at once**: [`../examples/compose.py`](../examples/compose.py).
- Each `chp-adapter-*` ships its own README with its capability contracts.

> Adapters install from PyPI at their published versions; a domain capability lives once as a
> `chp-adapter-*` and is consumed everywhere — one governed implementation, uniformly evidenced
> across every CHP node.
