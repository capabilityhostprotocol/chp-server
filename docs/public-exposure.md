# Exposing a CHP server publicly — ingress & egress, safely

The one invariant to internalize first: **exposure never bypasses governance.** However a call
arrives — direct, through a reverse proxy, or via a resolved relay — it runs the *full* CHP
invocation pipeline at the serving host and is recorded as signed evidence. Resolution and ingress
confer **no authority** (doc 35 §7). So the question is never "is it safe to be reachable" — it is
"who may call, what may they invoke, and what may the handler reach." Those are the three gates
below.

## Ingress — being called from outside

Layer these; they compose.

- **Per-caller authentication (`X-CHP-Key`).** Set `CHP_HOST_API_KEYS="agent-a:key1,steward:key2"`;
  each caller presents `X-CHP-Key`. The key names an **actor**, which drives visibility (a
  capability's `allowed_actors`) and scopes evidence (a caller can only replay its own
  correlations). This is the minimum gate for anything past localhost. `X-CHP-Token` is also
  accepted.
- **mTLS (strongest transport auth).** The HTTP binding can demand and verify a **client
  certificate** (`CERT_REQUIRED`): a missing or bad cert fails the TLS handshake — *no bytes reach
  a handler* — and a verified cert's identity binds to the evidence subject. stdlib `ssl`, no new
  dependency. Prefer this for cross-org / zero-trust exposure.
- **Compose an exposure adapter — don't hand-edit a proxy.** Exposure is itself adapter-first: you
  `compose()` an ingress adapter and drive it with a capability, so *who exposed what publicly,
  when* is an evidenced, revocable governed action, not config-file drift.
  - **`chp-adapter-ingress`** — `chp.adapters.ingress.route({name, upstream, host?, path_prefix?})`
    idempotently ensures a reverse-proxy route (TLS + a public URL) in front of the host;
    `…​.list` / `…​.remove` / `…​.status` manage it. Its backend is **pluggable behind one
    `IngressBackend` interface — Caddy today, Cloudflare-tunnel / nginx next, same capability** —
    and backend admin runs through the governed `chp.adapters.http.request` (never a raw socket),
    so the proxy itself is composed, not shelled out to.
  - **`chp-adapter-tailscale`** — `serve` (tailnet-private HTTPS) and `funnel` (public) expose the
    host over your tailnet with **no open port and no proxy container** — good when the caller is
    also on the tailnet, or for a quick public URL. Emits `tailscale_served` / `tailscale_funneled`
    evidence; needs `TAILSCALE_API_KEY`.
  The pattern is the same either way: `app.compose(IngressAdapter(...))` (or `TailscaleAdapter(...)`),
  then invoke the route/funnel capability — one governed, evidenced exposure surface.
- **The lifecycle gates still apply.** A **draining** instance refuses new `/invoke` (`server_
  draining`); an **HA standby** refuses it (`server_not_active`). Exposure does not defeat these.
- **Relay for hosts behind NAT/an org boundary.** A non-directly-routable host advertises its
  ingress/relay endpoint into a directory tagged `reachability: relay` (resolver part 4); callers
  resolve the reachable endpoint and invoke it through the relay transport (`chp-transport-zenoh`
  or the ingress URL). The advertisement feed is itself trust-gated (`POST /advertise` +
  `SourceTrustPolicy`), so only trusted hosts add supply.

## Egress — what the handler may reach

A served capability that calls out (an API, a subprocess, a file) is governed too:

- **Declared side effects.** A mutating or networking capability declares `side_effects`
  (`network`, `filesystem_write`, `repository_write`, …). A bare host does **not** auto-`ALLOW`
  an effectful capability — admission/policy decides, explicitly and evidenced, rather than a
  handler quietly reaching out.
- **Process egress control.** For capabilities that spawn processes, `inherit_env=False` gives the
  child an environment built from an **allowlist** only — a subprocess can't inherit the host's
  full environment or reach arbitrary credentials.
- **Brokered secrets, never cached.** Credentials are brokered: values never cross the invocation
  wire (token-provider seams hand a live token to the handler in-process), and `secrets.get`
  results are flagged `cache_results=False` so a secret value never sits at rest in the §13
  replay cache. Egress that needs a credential uses this path — it does not embed the secret in
  the payload or the evidence.
- **Policy gates *what*.** `allowed_actors` + a capability's `PolicyDescriptor` decide which caller
  may invoke which capability — so an exposed surface can be narrow per caller.

## Recommended postures

| Context | Ingress | Egress |
|---|---|---|
| **Inside your mesh** | `X-CHP-Key` (named actors) + zenoh transport auth; the gateway federates | declared `side_effects`; brokered secrets |
| **Public / cross-org** | **mTLS** + a composed exposure adapter (`ingress.route` — Caddy/nginx/cloudflare — or tailscale `funnel`); narrow the surface with `allowed_actors`/visibility; trust-gate any advertisement feed | brokered secrets; `inherit_env=False` for subprocesses; declared `side_effects` |
| **Never** | bind `0.0.0.0` with no auth; skip the gate pipeline | put secret values in payloads/evidence; auto-allow effectful capabilities |

## Why this is enough

Reachability is not authority. Auth (keys/mTLS) gates **who**; policy + `allowed_actors` gate
**what**; `side_effects` + brokered secrets gate **egress** — and every invocation, whoever
reached it and however, is admission-checked and recorded as a signed, replayable chain. Exposing
a CHP server is publishing a *governed* surface, not opening a hole.

See [`agent-integration.md`](agent-integration.md) to build the surface and
[`serving-capabilities.md`](serving-capabilities.md) for the policy/auth/deadline contract.
