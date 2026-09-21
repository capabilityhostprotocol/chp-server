# Use cases — a cookbook

Concrete things to build on a node. Each recipe is *need → compose → invoke → the evidence payoff*:
every call is admission-gated and recorded as a signed, replayable chain, so you get the result
**and** the proof it ran. The runnable version of each is in [`../examples/`](../examples).

Install once: `pip install chp-server` (adds `chp-core`). Recipes add one `chp-adapter-*` each — see
[capabilities-to-host.md](capabilities-to-host.md) for the full menu.

---

## 1 · A governed file / document API
**Need:** expose file operations to an app or agent, scoped and auditable.

```python
from chp_server import CapabilityServer
from chp_adapter_filesystem import FilesystemAdapter, FilesystemConfig   # pip install chp-adapter-filesystem

app = CapabilityServer("files")
app.compose(FilesystemAdapter(FilesystemConfig(allowed_roots=["./data"])))   # scoped, not the whole disk
app.run(port=8800)
```
`POST /invoke` `chp.adapters.filesystem.write_file` / `read_file` / `list_directory` / `grep` — each
denied outside `allowed_roots`, each replayable at `/replay/{correlation}`. Runnable:
[`examples/compose.py`](../examples/compose.py).

## 2 · Wrap an existing MCP server
**Need:** give an MCP server's tools CHP governance without rewriting them.

```python
from chp_server import CapabilityServer
from chp_adapter_mcp import MCPAdapter, MCPServerConfig   # pip install chp-adapter-mcp

app = CapabilityServer("tools")
app.compose(MCPAdapter(MCPServerConfig(
    name="fs", command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"])))
app.run(port=8800)
```
Each MCP tool becomes `chp.adapters.mcp.fs.<tool>`, and **the tool's own JSON Schema is enforced
before it runs** — a malformed call is denied pre-tool, every call is evidenced. The whole MCP
ecosystem, wrapped in governance, by composition. Runnable: [`examples/import_mcp.py`](../examples/import_mcp.py).

## 3 · Serve an LLM as a governed, replayable capability
**Need:** an inference endpoint where every generation is attributable and auditable.

```python
from chp_server import CapabilityServer
from chp_adapter_mlx import MLXAdapter, MLXConfig   # pip install chp-adapter-mlx  (Apple silicon)
# or: from chp_adapter_huggingface import ...       # pip install chp-adapter-huggingface (pulls torch)

app = CapabilityServer("inference")
app.compose(MLXAdapter(MLXConfig(base_url="http://localhost:8081")))   # point at a running MLX server
app.run(port=8800)
```
Invoke the adapter's chat/generate capability (`chp-server adapters --verbose` for the exact ids;
each adapter ships its own README). Every prompt and completion is a signed evidence event — the
difference between "an LLM endpoint" and "an LLM endpoint you can audit."

## 4 · A governed shell / automation endpoint
**Need:** let a workflow run commands — safely, with a human gate on the dangerous ones.

```python
from chp_server import CapabilityServer
from chp_adapter_process import ProcessAdapter, ProcessConfig   # pip install chp-adapter-process

app = CapabilityServer("automation")
app.compose(ProcessAdapter(ProcessConfig(allowed_commands=["git", "ls", "cat"])))   # scope what can run
app.run(port=8800)
```
`chp.adapters.process.run` is policy-gated and HITL-approvable — the pipeline can require approval
before a command executes, and the full command + outcome is recorded. Automation you can actually
trust to an agent.

## 5 · One node, many capabilities
**Need:** a single governed surface mixing your own functions with composed adapters.

```python
app = CapabilityServer("my-host")

@app.capability("text.wordcount")
def wordcount(text: str) -> dict:
    "Count words and characters."
    return {"words": len(text.split()), "chars": len(text)}

app.compose(FilesystemAdapter(FilesystemConfig(allowed_roots=["./data"])))
app.compose(MCPAdapter(MCPServerConfig(name="fs", command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"])))
app.run(port=8800)
```
Hand-written and composed capabilities share one host, one evidence chain, one `/capabilities.txt`.
`chp-server adapters` lists it all. Runnable: [`examples/compose.py`](../examples/compose.py).

## 6 · CHP-enable your existing app — zero rewrite
**Need:** put a governed, evidenced boundary in front of functions you already have.

```python
app = CapabilityServer("my-app")

@app.capability("orders.quote")
def quote(sku: str, qty: int = 1) -> dict:
    "Quote a price for a SKU."
    return {"sku": sku, "qty": qty, "total": price_of(sku) * qty}   # your existing logic

app.run(port=8800)
```
The docstring becomes the description, the type hints become the **enforced** input schema, payload
fields arrive as keyword args. A malformed call is denied before your function runs; every call is
replayable. See [agent-integration.md](agent-integration.md) for the LLM/agent recipe.

---

## Where next
- **What else you can host:** [capabilities-to-host.md](capabilities-to-host.md).
- **Compose mechanics** (embed vs distribute, config, policy, auth, deadlines): [serving-capabilities.md](serving-capabilities.md).
- **Every governed surface, runnable:** [`examples/demo.py`](../examples/demo.py).
- **Why this is a network:** [the-network.md](the-network.md).
