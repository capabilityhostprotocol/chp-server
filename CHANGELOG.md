# Changelog

All notable changes to `chp-server`. Format follows [Keep a Changelog](https://keepachangelog.com);
`chp-server` versions with the CHP protocol train.

## [0.60.2] — 2026-09-21

First public release on PyPI: `pip install chp-server`.

`chp-server` is the reference implementation of the CHP *server* role — a **node** that serves
capabilities (plain Python functions) over HTTP behind the full CHP invocation pipeline: identity,
admission, execution, and an append-only, signed, replayable evidence chain. One mandatory
dependency (`chp-core`).

### Added
- **Published to PyPI** via OIDC trusted publishing; RC→staging→prod release CI
  (`staging.yml` / `release.yml`).
- **Front door:** node-in-a-network README with the "join the network" ladder;
  [`docs/the-network.md`](docs/the-network.md) — the two axes (ambition × federation), what governed
  federation unlocks, and the honest limits.
- **Capabilities to host:** [`docs/capabilities-to-host.md`](docs/capabilities-to-host.md) — the
  catalog of composable governed adapters (git built in; filesystem, github, radicle, process, http,
  mcp, huggingface, mlx, composition, jobs, planning, delegation on PyPI).
- **Use-case cookbook:** [`docs/use-cases.md`](docs/use-cases.md) — governed file API, wrap an MCP
  server, serve an LLM, governed automation, compose several, CHP-enable your app.
- **Agent-assisted setup:** [`llms-install.md`](llms-install.md) (Cline convention), a README
  copy-paste agent prompt, and [`agent/`](agent/install-chp-server.md) — a signable Agentkit install
  skill + profile that provisions a node *through* a CHP host (the install itself is evidenced).
- **Machine discovery:** [`llms.txt`](llms.txt) (the read layer) + [`capabilities.txt`](capabilities.txt)
  (the act layer — CHP's own convention).
- Profiles (`protocol-only` … `gateway`) fail closed by construction; truthful `GET /server`
  feature negotiation from live attachment health; `GET /capabilities.txt`, `/.well-known/chp`,
  authorized `/host`; `GET /resolve`; active/standby HA; tenant-scoped evidence; absolute deadlines.

### Security
- Removed an accidentally-published `.chp` evidence database from the public mirror; added a
  `.gitignore` and sync excludes (`.chp/`, `*.sqlite*`, `*.db`) so evidence stores can never be
  tracked or published.

[0.60.2]: https://github.com/capabilityhostprotocol/chp-server/releases/tag/v0.60.2
