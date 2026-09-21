# Agent-assisted setup for chp-server

Two ways to have an AI agent install and configure a chp-server node — pick by who's asking.

## 1 · Any coding agent (new user) → `../llms-install.md`
If you're a developer with **Claude Code, Cursor, or Cline**, point your agent at
[`../llms-install.md`](../llms-install.md) (or paste the prompt in the
[README](../README.md#set-up-with-your-ai-agent)). The agent runs the shell steps directly and
verifies each. This is the broad, no-prerequisites path.

## 2 · A CHP / Agentkit operator (governed) → the skill + profile here
If you already run a **CHP host**, provision the node *through* it so the installation itself is
evidenced — every command and check is a governed capability invocation with a replayable trail.

- **[`install-chp-server.skill.json`](install-chp-server.skill.json)** — a portable, signable
  [Agentkit `Skill`](https://github.com/capabilityhostprotocol): `name`, `description`,
  `instructions`, and the `tools` it may call (`chp.adapters.process.run`,
  `chp.adapters.http.request`). Load with `chp_agentkit.Skill.from_dict(json.load(...))`; its
  `sha256()` is the provenance digest a signature binds to.
- **[`install-chp-server.profile.json`](install-chp-server.profile.json)** — a runnable agent
  profile (`id`, `role`, `persona`, `instructions`, `tools`) that executes the skill on your host.

Both grant only two capabilities — governed shell (`process.run`) and governed HTTP
(`http.request`) — so the whole setup is admission-gated and recorded. Steps the host's policy
gates (a first `process.run`, for example) pause for human approval by design.

> The capabilities live in chp-dev (`chp-adapter-process`, `chp-adapter-http`); the node you're
> installing needs only `chp-server` itself. This directory is optional setup data — it is not part
> of the installed package and does not change its one-dependency (chp-core) contract.
