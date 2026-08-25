# chp-server

Independently installable reference implementation of the CHP Server role.

```bash
pip install chp-server chp-core
chp serve                 # or: chp-server serve
```

The base install runs with **only `chp-core`**: lifecycle, `GET /server` (Server.Describe),
`GET /ready`, protocol-version negotiation, liveness, and truthful *unsupported* responses for every
optional feature. Host exposure, local execution, resolution, MCP, federation, and Platform services
attach through optional packages registering in the `chp_server.ports` entry-point group; feature
truth is computed from attachment health, never from package presence.

Profiles: `protocol-only` (default), `host`, `local`, `standalone`, `managed`, `edge`, `gateway` —
a profile declares which port roles are required and the server fails closed when one is absent.

Built on [`chp-core`](https://github.com/capabilityhostprotocol/chp-core) — the canonical CHP
protocol implementation. Licensed Apache-2.0 (see LICENSE, NOTICE).

This repository is a read-only public mirror; development happens in the private
CHP workspace and syncs here.
