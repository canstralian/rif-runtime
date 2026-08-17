# MCP Server Framework — Governance Specification

Status: **Drafted** · Domain: `spec/mcp/` · Conforms to: ADR-0008, `spec/governance/`, `spec/capability/`, `spec/evidence/`
Reference implementation: `src/rif_runtime/mcp/metasploit.py` (single-server governor this framework generalizes)

> **Read §14 first.** This spec is drafted, not implemented. Sections below
> describe the reference implementation in the present tense in places where the
> runtime does not yet conform — most importantly the `destructive` capability
> class (§5), which the shipped classifier cannot return. §14 records the exact
> delta, including the deny-reason namespace mapping needed to query real evidence.

---

## 1. Purpose and non-goals

The MCP server framework defines how RIF Runtime admits and gates **Model
Context Protocol** tool invocations from one or many MCP servers. MCP is the
runtime's highest-leverage authority surface: unlike an HTTP fetch, an MCP tool
call can *grant capability* — write files, run processes, mutate remote state —
so it is where the authority model bites hardest.

The framework is server-agnostic. The shipped `MetasploitGovernor` is one
concrete lane; this spec lifts its invariants (ordered decision procedure,
signed time-bound target-pinned tokens, injection quarantine, signed evidence)
into a contract every governed MCP server MUST satisfy.

**Non-goals.** This spec does not define the MCP wire protocol (owned upstream),
does not implement transport, and does not replace the policy engine — it
composes with `PolicyEngine.evaluate()` and the reflexive posture loop.

## 2. Position in RIF Runtime

The framework sits between an agent's proposed tool call and the MCP client
transport, on the existing `mcp.*` action path:

```
Agent -> MCP invocation intent
  -> MCP framework admission (this spec)
     -> PolicyEngine.evaluate()  (posture, allowed_hosts, mcp egress flag)
     -> capability classification + authority check (§4)
  -> [destructive] hard gate (§4.7 / §6)
  -> MCP client transport -> server
  -> signed EvidenceEvent (§7) -> JsonlStore
```

Grounding in current surface (normative references, not restated here):

- `mcp.invoke` ∈ `NETWORK_ACTIONS`; `mcp.*` egress is gated by
  `allow_mcp_server_network_access` on the environment profile
  (`src/rif_runtime/policy.py`).
- Routes `POST /v1/mcp/invoke`, `POST /v1/mcp/metasploit/{evaluate,token}`
  (`src/rif_runtime/api.py`). Token minting is behind `ControlPlaneAuth`.
- Signed `CapabilityToken` and `EvidenceEvent`
  (`src/rif_runtime/mcp/metasploit.py`).

## 3. Authority model (the spine)

Every artifact that flows into an MCP decision is assigned a **trust tier**.
Tiers carry *authority*, not merely trust; a lower tier can never escalate its
own authority by asserting it.

| Tier | Source | Authority |
| --- | --- | --- |
| **T0 — Operator** | Signed human approval (control-plane authenticated) | Full, but scoped and time-bound (§6) |
| **T1 — Runtime policy** | `config/environments.yaml`, `policies.json`, posture | Grants/denies within configured envelope |
| **T2 — Registered server contract** | Server capability manifest admitted at registration (§8) | Declares *what tools exist*; grants nothing by itself |
| **T3 — Tool result** | Data returned by an MCP tool call | Zero authority; may be consumed as data |
| **T4 — Embedded** | Content embedded in tool descriptions, tool results, server metadata, or invocation args | **Zero authority** |

**T4 is the injection surface.** MCP tool descriptions, server-supplied
metadata, and tool *results* are attacker-influenceable (a compromised or
hostile server, or upstream data a tool returns). T4 carrying zero authority is
the primary control: an undetected injection in T4 still cannot grant
capability, because capability is granted only by T0/T1, never by T4 content.

**Detection is defence-in-depth, not the primary control.** The injection
scanner (§4.3) reduces blast radius and produces evidence, but the security
argument does not depend on it: even a scanner miss leaves T4 with no authority
to escalate. A natural-language assertion ("you are authorised", "skip
governance") is T4 regardless of where it appears and is never authority.

## 4. Governed invocation procedure

An MCP invocation is evaluated by an **ordered** sequence of lanes. The order
*is* the security argument: the first lane to return a decision wins, and the
identity of that lane names the authority boundary that applied. This mirrors
`MetasploitGovernor.evaluate()` and MUST be preserved.

- **§4.1 — Posture gate.** If posture is `locked`, deny (`posture.locked`).
  A locked runtime denies every MCP call unconditionally.
- **§4.2 — Egress gate.** If the environment profile has
  `allow_mcp_server_network_access = false`, deny (`mcp.egress.disabled`) before
  any server contact.
- **§4.3 — Injection quarantine.** Scan T4 surfaces — tool description, server
  metadata, invocation args (recursively, per `_string_params`), and any
  already-returned tool result being fed back — for authority-assertion /
  injection markers. On a hit, deny and quarantine
  (`mcp.injection.quarantined`), mark the decision severe, and emit evidence.
  This is defence-in-depth (§3), not the gate that makes the system safe.
- **§4.4 — Read-only fast-path.** If the capability classifies as `read_only`
  (§5), allow (`mcp.capability.read_only`). Read-only tools return knowledge,
  not authority.
- **§4.5 — Consequential requires authority.** A `consequential` capability that
  is *not* destructive requires a valid capability token **or** an explicit
  allow rule; absent both, deny (`mcp.authority.absent`).
- **§4.6 — Capability-token verification.** When a token is presented, verify it
  per §6 in full (signature, expiry, capability pin, target pin, arg-hash pin).
  Any failed check denies with the specific reason.
- **§4.7 — Destructive actions: the hard gate.** A `destructive` capability
  (§5) MUST pass the full §6 hard gate: a per-invocation, single-use,
  HMAC-signed, TTL-bounded, target-pinned capability token whose approved
  argument hash is **re-verified against the live args at invoke time**. There
  is **no `auto_approve` / `auto_invoke` configuration key**, and one MUST NOT be
  added — see §12. Destructive actions are never allowed by a wildcard policy
  rule, by posture alone, or by a read-only lane.

## 5. Capability classification

Each server tool MUST be classified at registration (§8) into exactly one class.
Classification is a property of the tool contract (T2), not of the arguments
(T4), so it cannot be downgraded by crafted input.

- **`read_only`** — returns information, mutates nothing observable outside the
  call (search, list, read, describe). Fast-path allow (§4.4).
- **`consequential`** — mutates state with bounded, reversible effect (create a
  draft, post to a sandbox, write within a scoped workdir). Requires authority
  (§4.5).
- **`destructive`** — irreversible or high-blast-radius effect (delete, force
  push, run arbitrary process, exfiltrate, mutate production). Requires the
  §4.7 / §6 hard gate.

Classification reuses the existing `capabilities.classify` /
`is_severe` machinery (`src/rif_runtime/mcp/capabilities.py`) as the normative
implementation; new servers extend the catalog, they do not fork the classifier.

## 6. The destructive-action hard gate

A destructive invocation is admitted **only** if all of the following hold. Each
check maps to a distinct deny reason so evidence names the exact boundary; this
generalizes `MetasploitGovernor._evaluate_broker`.

1. **Signed human approval present.** A `CapabilityToken` (T0) is presented;
   absent ⇒ deny (`mcp.gate.approval_absent`).
2. **Signature valid.** HMAC over the token's canonical signing payload matches
   under the broker key, compared with `hmac.compare_digest`; else deny
   (`mcp.gate.signature_invalid`, severe).
3. **Within TTL.** `now < expires_at`. Default TTL **300 s**; authority is
   time-bound so a stale approval cannot be replayed. Expired ⇒ deny
   (`mcp.gate.token_expired`).
4. **Single-use.** The `token_id` is consumed on first successful use and
   recorded in an append-only spent-token log; a second presentation ⇒ deny
   (`mcp.gate.token_replayed`, severe). (New requirement beyond the metasploit
   broker; see OD-3.)
5. **Capability pinned.** `token.capability == intent.capability`; else deny
   (`mcp.gate.capability_mismatch`).
6. **Target pinned.** `token.target == intent.target`; else deny
   (`mcp.gate.target_pinned`, severe).
7. **Argument hash re-verified at write time.** `token.intent_hash` MUST equal a
   fresh hash of the *live* invocation arguments computed at the moment of
   dispatch, **not** the arguments seen at approval time. This closes the
   TOCTOU window between approval/diff-review and actual dispatch: if the args
   mutate after approval, the hashes diverge and the call is denied
   (`mcp.gate.intent_mismatch`, severe).

Only when 1–7 all pass is the call dispatched to transport
(`mcp.gate.authorized`). The intent hash MUST cover only structural,
authority-bearing fields (tool, capability, target, scope, args) and MUST
exclude free-text/T4 fields, exactly as `MetasploitIntent.intent_hash`.

## 7. Evidence and replay (reference, not restate)

Every decision — allow or deny, every lane — MUST emit a signed, replayable
`EvidenceEvent` and append it via `JsonlStore`. The framework does **not** define
its own evidence format: it conforms to `spec/evidence/observation_event.schema.json`
and reuses the signing/verification in `src/rif_runtime/mcp/metasploit.py`
(`_sign_evidence` / `verify_evidence`). Replay conforms to the (placeholder)
`spec/replay/` contract once extracted. This is a deliberate reference to avoid
the duplication failure mode called out in OD-5.

## 8. Providers layer (server registry)

The Providers layer governs server *admission*: registration, capability-manifest
validation, and discovery. A server MUST be registered with a capability
manifest conforming to `spec/capability/capability_manifest.schema.json` before
any of its tools are invocable. Registration assigns each tool a class (§5) and
fixes the T2 contract used for pinning.

> **Note (OD-5).** The Providers layer overlaps subsystems 0.1–0.2 of the DIE
> (Dependency/Integration Envelope) design. Per the OD-5 ruling this spec keeps
> Providers as a **distinct section but cites DIE §0.1–0.2 as the normative
> source** rather than restating it: §8 adds only what is new at the MCP layer
> (per-tool classification, T2 pinning) and defers the subsystem contract to
> DIE. Promote to a standalone definition only if the two genuinely diverge.

## 9. Configuration

- MCP egress is off by default: `allow_mcp_server_network_access = false`
  (`src/rif_runtime/schemas.py`). Environments opt in via
  `config/environments.yaml`; the flag is never hardcoded per §Conventions.
- The broker signing key is sourced from the environment
  (`RIF_MSF_BROKER_KEY` today; a framework-level `RIF_MCP_BROKER_KEY` is OD-4),
  never persisted to disk or committed.
- Token minting is a control-plane operation and MUST remain behind
  `ControlPlaneAuth`.

## 10. Conformance requirements

A governed MCP server implementation is **conformant** iff:

- **C1 (MUST)** It evaluates every invocation through the ordered lanes of §4,
  in order, first-match-wins.
- **C2 (MUST)** T4 content never grants authority; classification derives from
  T2, not from arguments.
- **C3 (MUST)** Destructive capabilities pass the full §6 gate, including
  write-time arg-hash re-verification (7) and single-use enforcement (4).
- **C4 (MUST NOT)** Expose any `auto_approve` / `auto_invoke` key or otherwise
  allow a destructive call without a fresh T0 token.
- **C5 (MUST)** Emit a signed `EvidenceEvent` for every decision.
- **C6 (SHOULD)** Run injection quarantine (§4.3) as defence-in-depth.
- **C7 (MUST)** Deny by default: an unclassified or unregistered tool is denied.

## 11. Evaluation scorecard

A drafted spec is scored on six weighted dimensions. Each raw criterion scores
`0`, `0.5`, or `1`. Weighted dimension score = raw × weight.

| # | Dimension | Raw criteria | Weight | Weighted max |
| --- | --- | --- | --- | --- |
| D1 | Authority & capability model | 6 | 1.0 | 6.0 |
| D2 | Threat coverage | 5 | 1.0 | 5.0 |
| D3 | Decision-procedure correctness | 6 | 1.0 | 6.0 |
| D4 | **Security** (destructive gate, injection, TOCTOU) | 7 | **2.0** | **14.0** |
| D5 | Conformance & testability | 5 | 1.0 | 5.0 |
| D6 | Evidence & replay | 4 | 1.0 | 4.0 |
| | **Total** | 33 | | **40.0** |

**GREENLIGHT** requires **all** of:

1. Overall weighted score **≥ 30.0 / 40.0** (75%).
2. Security dimension **≥ 10.5 / 14.0** (75% floor).
3. Each of the **named critical D4 criteria** — write-time arg-hash
   re-verification (§6.7), single-use enforcement (§6.4), no-`auto_approve`
   (§4.7 / C4), and T4-carries-zero-authority (§3 / C2) — scores a full `1.0`.

Rationale (per the §12 gate-defect ruling): the security **max is 14** (weight
`2.0`), so the `10.5` floor is a genuine **75%** threshold (`10.5 / 14 = 0.75`),
not a demand for a perfect raw score. A reachable proportional floor gives
headroom for subjective `0.5` deductions on non-critical D4 criteria, while the
small set of *named* critical criteria in (3) remain strict pass/fail. This is
the fix for the defect where a `10.5 / 10.5` floor made GREENLIGHT unreachable
on any single deduction.

## 12. Known defects and flags

- **Upstream scorecard gate defect (resolved here).** The evaluator as
  originally specified stated Security `≥ 10.5/14 weighted` while the dimension's
  weighted max was `10.5` (7 raw × 1.5) — making the floor equal to the max, so a
  single `0.5` deduction made GREENLIGHT unreachable. Ruling: the author's own
  `10.5 / 14 = 0.75` proves a 75% intent, so the **weight is corrected to 2.0
  (max 14)** and the floor stays `10.5` (§11). This is an evaluator-wide fix,
  not local to this spec; every spec scored after this inherits it. Second-order
  flag: raising Security's weight rebalances the total-weight budget across all
  dimensions — confirm the intended total before rollout.
- **`auto_approve` is a standing prohibition, not an omission.** Its absence
  (C4, §4.7) is deliberate. Any future PR adding an auto-approve/auto-invoke key
  for destructive capabilities MUST be rejected at review.

## 13. Open decisions

- **OD-1.** Should the injection scanner run *before or after* the egress gate
  when a server is remote? Current order (§4.2 before §4.3) avoids contacting a
  server we would deny anyway, but means we never scan its metadata. Logged;
  proposed resolution: keep egress-first, scan cached/last-known metadata.
- **OD-2.** Per-tool vs per-server token scoping for `consequential` (non-
  destructive) calls. §4.5 currently allows an allow-rule *or* token; whether
  consequential calls should also be single-use is open.
- **OD-3.** Spent-token store location and retention (single-use enforcement,
  §6.4). Proposed: an append-only `JsonlStore` log keyed by `token_id`, with a
  retention window ≥ max TTL.
- **OD-4.** Framework-level signing key (`RIF_MCP_BROKER_KEY`) vs reusing the
  per-server key (`RIF_MSF_BROKER_KEY`). Reusing couples all servers to one key;
  per-server isolates blast radius but multiplies key management.
- **OD-5 (carried).** Providers layer (§8) overlaps DIE subsystems 0.1–0.2.
  Ruling applied: reference DIE as normative, keep §8 distinct but non-
  duplicating. Revisit only on genuine divergence.

## 14. Conformance status of the reference implementation

This spec is **drafted**, not implemented. Several sections above are written in
the present tense about `src/rif_runtime/mcp/metasploit.py` ("mirrors
`MetasploitGovernor.evaluate()`", "reuses the existing `capabilities.classify`
machinery"); those describe the intended relationship, not current conformance.
The table below records the actual delta so no reader mistakes intent for
shipped behaviour. Requirements above are unchanged — this section only reports
where the runtime stands.

| Requirement | Status in `metasploit.py` / `policy.py` |
| --- | --- |
| §4.1 posture gate | **Implemented** — `metasploit.py`, first check, reason `posture.locked`. |
| §4.2 egress gate | **Implemented elsewhere** — in `PolicyEngine.evaluate()` (`policy.py`, reason `mcp.egress.disabled`), *not* in the governor. The two run on different call paths, so §4's single ordered sequence does not exist in one place today. |
| §4.3 injection quarantine | **Partial** — `scan_for_injection` covers `intent.text`, `intent.untrusted_context`, and recursed `params`. It does **not** scan tool descriptions, server metadata, or returned tool results. |
| §4.4 read-only fast-path | **Implemented** — third check, not fourth (no egress lane precedes it in the governor). |
| §4.5 consequential authority | **Divergent shape** — realised as three `GovernanceMode` lanes (`read_only_firewall`, `shadow`, `lab_broker`) that this spec does not model. |
| §5 `destructive` class | **Not implemented.** `CapabilityClass` has exactly three members: `read_only`, `consequential`, `unknown`. `classify()` can never return `destructive`; severity is the orthogonal `is_severe()` predicate over `SEVERE_CAPABILITIES`. The §4.7 / §6 hard gate therefore has no class to key off. **Open decision — see OD-6.** |
| §5 `unknown` class | **Implemented but unmodelled** — `classify()` returns `unknown` for unrecognised tools, which the broker treats as consequential (satisfying C7's deny-by-default intent). This spec's three-class model has no slot for it. |
| §6.1 approval present | **Implemented** — `msf.broker.approval_absent`. |
| §6.2 signature valid | **Implemented** — HMAC via `hmac.compare_digest`. |
| §6.3 within TTL | **Implemented**, but the default is **600 s**, not the 300 s stated in §6 — see `mint_token(ttl_seconds=600)` and `api.py`'s `payload.get("ttl_seconds", 600)`. |
| §6.4 single-use | **Not implemented** — no spent-token store; see OD-3. |
| §6.5 capability pinned | **Implemented** — `msf.broker.capability_mismatch`. |
| §6.6 target pinned | **Implemented** — `msf.broker.target_pinned`. |
| §6.7 arg-hash re-verified | **Implemented** — `token.intent_hash != intent.intent_hash()`. The hash correctly covers only `tool`, `capability`, `target`, `scope_id`, `params`, excluding the T4 free-text fields as required. |
| §7 signed evidence | **Implemented** — `_sign_evidence` / `verify_evidence`. Not yet validated against `spec/evidence/observation_event.schema.json`. |
| §8 providers registry | **Not implemented** — no server registration or manifest admission exists. |
| C4 no `auto_approve` | **Holds** — no such key exists anywhere in the runtime. |

### Deny-reason namespace

This spec uses an `mcp.*` namespace; the implementation emits `msf.*`. Only
`posture.locked` and `mcp.egress.disabled` match verbatim. These strings are
persisted into `EvidenceEvent.matched_rule` and are the audit trail's primary
index, so the mapping is load-bearing for replay:

| This spec | Implementation |
| --- | --- |
| `mcp.injection.quarantined` | `msf.injection.quarantined` |
| `mcp.capability.read_only` | `msf.capability.read_only` |
| `mcp.authority.absent` | `msf.capability.execution_absent`, `msf.broker.approval_absent` |
| `mcp.gate.signature_invalid` | `msf.broker.signature_invalid` |
| `mcp.gate.token_expired` | `msf.broker.token_expired` |
| `mcp.gate.capability_mismatch` | `msf.broker.capability_mismatch` |
| `mcp.gate.target_pinned` | `msf.broker.target_pinned` |
| `mcp.gate.intent_mismatch` | `msf.broker.intent_mismatch` |
| `mcp.gate.authorized` | `msf.broker.authorized` |
| `mcp.gate.token_replayed` | *(none — §6.4 unimplemented)* |

Renaming the emitted identifiers is a breaking change to historical evidence;
whether the framework adopts `mcp.*` or retains `msf.*` as the reference lane's
namespace is **OD-7**.

### Additional open decisions

- **OD-6.** Does `destructive` become a fourth `CapabilityClass` member (with
  `SEVERE_CAPABILITIES` promoted into it), or is it defined as
  `consequential ∧ is_severe()`? §4.7 and §11's GREENLIGHT criteria are
  unreachable as literally written until this is settled.
- **OD-7.** Deny-reason namespace: rename to `mcp.*` (breaks replay queries over
  existing evidence) or keep `msf.*` per-lane under a framework scheme.
- **OD-8.** TTL default: tighten the code to the spec's 300 s, or record 600 s
  as the intended default.
