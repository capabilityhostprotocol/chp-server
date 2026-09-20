# The network — why chp-server is a node, not just a server

A `chp-server` you run alone is already worth running: capabilities served over HTTP, every call
admission-gated and recorded as signed, replayable evidence. But the reason CHP exists is what
happens when nodes *point at each other*. This doc is the "why."

## Two axes

Think of where a deployment sits on two independent axes.

- **Ambition** — how much a node does: *embed* governance in one app → *serve* capabilities →
  *compose* several into new ones → *orchestrate* multi-step work → *federate* across owners.
- **Federation** — how far it reaches: one node → your own fleet → **across trust boundaries you
  don't control.**

Most tools only move you along the first axis. CHP's distinguishing move is the second:
**governed federation** — composing capabilities across parties who don't share a database and
don't fully trust each other, while still being able to *prove what happened* and *control what's
allowed*, with no central owner in the middle. That combination is the whole point:

- A **central platform** can prove and control — but only by making everyone surrender their data
  and their flow to a middleman.
- **Point APIs / EDI / open agent meshes** cross org lines — but prove nothing and bound nothing;
  a dispute is he-said-she-said.
- **Governed federation** is the only shape where each party keeps its own node *and* the whole
  interaction stays provable and governable.

## The on-ramp is the same ladder as the README

Run your node → serve → discover → compose → resolve & federate → trust across boundaries. Each
rung is complete on its own. A node must be **fully valuable solo while pointing outward** — that
is the deliberate answer to the network's cold-start problem: you never need anyone else to get
value, and value compounds as the network fills in.

## The frontier — what governed federation unlocks

These are the ceiling, not the getting-started. Some rest on primitives that exist today
(evidence, resolution, delegation); some are still maturing (markets, confidential compute at
scale). They're here to say what the network is *for*.

### 1 · Cross-organization workflows with end-to-end provenance
One task spanning capabilities on several owners' nodes — a lookup here, a computation there, an
approval elsewhere — yielding **one cryptographically verifiable provenance chain across
organizational boundaries.** The evidence *is* the audit trail, the receipt, and (as actions grow
consequential) the basis for accountability between parties. Ungoverned meshes can reach across
orgs but can't prove the chain; a central platform can prove it but owns everyone's data.

### 2 · A capability market with evidence as the settlement layer
Capabilities advertised, discovered, invoked, and **metered** across nodes, with the signed
evidence chain doubling as the auditable ledger — invoke *N* times, prove *N* times, settle.
Sovereign providers host their own capabilities (data and compute stay home); consumers pay per
governed, provable invocation. A market without a market-*maker* taking rent and data.

### 3 · Confidential federated computation
Invoke a capability on a **sealed payload** — one party's data processed by another party's
capability *without the second party ever seeing the plaintext* — still fully evidenced. You get
the result and the proof it ran, not the exposure. This is the unlock that makes federation viable
where "just call their API" is a non-starter: regulated data, competitive IP, clean-room analysis.

### 4 · Governed, revocable authority — including agent labor
Authority to *act* — spend, commit, dispatch — granted as a **scoped, capped, revocable** grant
that can be sub-delegated across boundaries and unwound at any link, with the credential itself
never crossing the wire. This is the difference between an agent that *drafts* and one *authorized
to commit*. At its limit it's a **workforce that crosses org lines**: agents join by being
verified and admitted (declare → verify → admit), hire specialist agents on other nodes, and every
deliverable carries provenance a consumer can check against fabrication.

## Two flagships you can actually picture

**When capabilities commit the physical world — manufacturing.** A production run threads through
designer → material supplier → fabricator → QA → logistics → buyer: parties who don't share a
database. Wrap the fab step as a governed capability (a 3D-print/order capability is exactly this
shape) and the four primitives light up at once — the evidence chain becomes the certificate of
conformance and the recall query; a **sealed** design file lets you use a fab you don't fully
trust; a **bounded** grant is what makes an agent-placed purchase order safe; **resolution** finds
a qualified sovereign shop across the federation instead of a walled marketplace. The same pattern
generalizes to pharma/lab chain-of-custody, energy dispatch-and-settle, food provenance, and
customs handoffs.

**When the capability is the labor — agent work.** Here the capability isn't a function or a part;
it's cognitive work. Governed federation turns a swarm of untrusted agents into a workforce whose
authority is *bounded* and whose work is *provable* — accountable A2A instead of an open, unbounded
registry.

## The honest floor — where trust bottoms out

Say this plainly, because it's load-bearing, not a flaw to hide: **evidence proves that a process
ran, on valid authority, over recorded inputs. It does not prove the output is physically true or
substantively correct.**

- For a physical part, the chain proves what was *ordered and reported* — not that the atoms match
  spec. Trust still bottoms out at an **inspection/attestation oracle.**
- For cognitive work, governance catches the *malformed*, not the *plausible-but-wrong*, and there
  is often no ground truth at all. Correctness still bottoms out at a **human or deterministic
  verifier.**

That boundary is exactly where CHP's design puts its weight: human-in-the-loop gates on
consequential actions, deterministic pipelines where reliability matters more than flexibility, and
graded trust that says *how much* to rely on a party rather than pretending verification is free.
Governed federation carries an interaction right up to that wall and makes everything below it
provable — which is far more than any alternative offers, and honest about the rest.

---

*Built on [`chp-core`](https://github.com/capabilityhostprotocol/chp-core): identity, evidence,
signing, and the 12-gate invocation pipeline. Start with the [README](../README.md) and
[`examples/demo.py`](../examples/demo.py).*
