# Specification Review — Execution Authority Boundary

**Repository:** canstralian/mandare  
**Status:** `Draft` — architectural decision selected; open for review. No runtime implementation is authorized by this document.  
**Track:** B (Specification)  
**Source-of-truth baseline:** `main` at `7c132a7d5768dde64e9a659a0f0acdeb530db9e7`  
**Related:** PR #145 finding F7; `docs/spec-review-identity-spine-migration.md`; `docs/spec-review-capability-snapshot-authority.md`

This review answers one question:

> **What must be true, and what immutable authorization evidence must exist, before any capability can cross into mechanical execution?**

Normative terms `MUST`, `MUST NOT`, `SHALL`, and `SHALL NOT` are binding within this review. Statements labelled **Current implementation** describe shipped behaviour at the baseline above. Statements labelled **Selected contract** describe the proposed boundary and are not claims about current code.

---

## 1. Status and scope

This is a focused review of the seam between governance/admission and mechanical execution. It does not redesign policy, identity, capability snapshots, persistence, MCP authority, or the capability model generally.

**Decision status:** resolved in this document. The selected authority model is **Design B — kernel consumes and validates proof of prior authorization**.

The review remains open until the repository's normal specification-governance process approves it. Until a separate implementation change lands, PR #145 F7 remains a documented caller-enforced boundary rather than a structurally enforced property.

---

## 2. Current implementation evidence

### 2.1 Governed caller path

**Current implementation.** `RIFRuntime.execute_capability()` is the governed orchestration path. It:

1. derives a `PolicyRequest` from the `ExecutionManifest`;
2. calls `evaluate()`, which records a `PolicyDecision`;
3. returns a denied `ExecutionResult` when policy does not allow;
4. calls `CapabilityRegistry.admit()` after an allow decision;
5. calls `ExecutionKernel.execute()`;
6. appends completion evidence to `capability_evidence.jsonl`.

This means policy authorization and admission precede the kernel **when this caller is used**.

### 2.2 Kernel is mechanically callable without authority proof

**Current implementation.** `ExecutionKernel.execute()` accepts only an `ExecutionManifest`. It resolves the capability from `CapabilityRegistry` and immediately calls `capability.execute(manifest)`. It does not receive, establish, or validate policy authority or admission evidence.

`tests/execution/test_kernel.py` proves that a capability registered without a governance record can execute directly through the kernel. `.claude/skills/run-rif-runtime/drive_capability_layer.py` also demonstrates policy evaluation and kernel execution as two independent calls.

PR #145 finding F7 correctly classifies the result: "no execution path may bypass policy evaluation" is not currently a structural property; governance is enforced by the caller.

### 2.3 Admission is mutable state, not execution proof

**Current implementation.** `CapabilityRegistry.admit()` checks an existing `CapabilityRecord` for verified integrity, at least one passing evaluation, and an allowed lifecycle state. On success it mutates `record.lifecycle.status` to `admitted` and returns the record.

No immutable admission event or execution-scoped proof is produced. `CapabilityRegistry.resolve()` returns the executable adapter independently of `admit()`.

### 2.4 `PolicyDecision` is not sufficient authorization evidence

**Current implementation.** `PolicyDecision` contains decision result, actor, action, target, environment, posture, reason, matched rule, and timestamp. It has no `decision_id`, capability identity, manifest identity, parameters hash, capability-snapshot reference, or admission reference.

A policy allow therefore cannot safely be treated as a reusable execution credential: it is not bound to enough of the operation to prove that the later mechanical call is the same operation that was evaluated.

### 2.5 Existing execution/evidence records

**Current implementation.** `ExecutionResult` records status, message, output, metadata, and timestamps. `RIFRuntime.execute_capability()` appends policy decision plus result data to `capability_evidence.jsonl` using ordinary `JsonlStore`.

`decisions.jsonl` is different: it uses `HashChainedJsonlStore`, making the chained portion tamper-evident. `capability_evidence.jsonl` is not hash-chained at this baseline.

`ExecutionManifest` is documented as immutable, but its dataclass is not frozen. The current manifest object must therefore not be treated as immutable authorization evidence.

### 2.6 Replay is read-only reconstruction

**Current implementation.** `ReplayEngine` reads `decisions.jsonl` and reconstructs governance graph/posture state. It does not invoke `ExecutionKernel`, resolve capabilities, or call adapters. This is consistent with the capability-snapshot review's rule that replay reconstructs history and is not recovery.

### 2.7 Existing narrow precedent

**Current implementation.** `mcp/metasploit.py` already demonstrates a narrower proof pattern: a `CapabilityToken` is capability-, target-, scope-, intent-hash-, and time-bound, authenticated with an HMAC, and rejected on missing/invalid signature, expiry, capability mismatch, target mismatch, or intent-hash mismatch.

**Inference.** That token is not the generic execution contract and this review does not expand MCP write authority. It does, however, demonstrate that authenticated, operation-bound authority evidence is compatible with the codebase's existing security primitives.

---

## 3. Problem statement

Mandare currently has two distinct paths:

```text
Intended governed path
ExecutionManifest
  -> RIFRuntime.execute_capability()
  -> PolicyEngine
  -> CapabilityRegistry.admit()
  -> ExecutionKernel.execute()
  -> Capability.execute()

Mechanically callable path
ExecutionManifest
  -> ExecutionKernel.execute()
  -> Capability.execute()
```

The second path can perform the same mechanical work without proving that the first path occurred. The architecture therefore relies on caller discipline at exactly the point where authority must become non-bypassable.

The required correction is not "move more policy code downward." It is to make mechanical execution unable to proceed without authenticated evidence that governance and admission already authorized the exact operation being attempted.

---

## 4. Normative invariants

1. **Prior authorization.** No effectful execution SHALL occur without prior explicit authorization.
2. **Knowledge is not authority.** Intent, discovery results, model output, trust scores, MCP metadata, skill definitions, capability declarations, and provider credentials SHALL NOT by themselves constitute execution authority.
3. **Fail closed.** Missing, stale, mismatched, unauthenticated, revoked, or otherwise invalid authorization SHALL fail before effects.
4. **Exact binding.** Authority evidence MUST bind to enough identity and operation context that it cannot safely authorize a different actor, capability, action, target, parameter set, decision, admission basis, or capability snapshot by accident.
5. **Retry ceiling.** A mechanical retry MAY reuse existing authority only for the same `Decision` and the same operation binding. A retry MUST NOT silently acquire broader parameters, targets, capabilities, or authority.
6. **No historical mutation.** A change in intent, operation, authority, or authoritative capability observation requires a new `Decision`; a changed admission basis requires a new admission event. Historical authorization evidence MUST NOT be mutated to cover the change.
7. **Replay is non-effectful.** Replay reconstructs recorded history only. It SHALL NOT invoke the execution kernel, an adapter, or an authorization issuer, and SHALL NOT become a recovery/execution API.
8. **No lower-level bypass.** Production effectful adapters and lower-level execution primitives SHALL NOT provide an undocumented route around the authorization-verifying kernel boundary.
9. **Evidence before effect.** The authorization record required to justify an execution MUST be durably recorded or otherwise verifiably committed before the first effect occurs. Failure to establish that evidence fails closed.
10. **Authority is explicit.** Registration, resolution, availability, discovery, admission state, or possession of an executable adapter is not equivalent to permission to execute it.

---

## 5. Candidate designs

### A — Kernel performs authorization itself

`ExecutionKernel.execute()` would call policy/governance machinery directly before invoking an adapter.

**Strengths:** the mechanical boundary becomes self-governing; a caller cannot omit policy evaluation.

**Weaknesses:** the kernel becomes coupled to policy, posture, admission, identity, snapshot, and future governance concerns; policy evaluation becomes harder to separate from execution for testing and replay; callers that already hold a Decision would need the kernel to recreate or reinterpret governance state; retries risk producing new decisions merely because the mechanical layer is retried.

**Verdict:** rejected.

### B — Kernel consumes proof of prior authorization

Governance and admission produce an immutable, authenticated authorization object. `ExecutionKernel.execute()` requires that object and validates its authenticity, freshness, and exact operation binding before invoking an adapter.

**Strengths:** preserves policy/execution separation; makes bypass fail closed at the mechanical boundary; allows deterministic replay to record decisions without re-running policy; supports multiple mechanical attempts under one unchanged Decision; makes boundary tests local and falsifiable.

**Weaknesses:** requires a small authorization-evidence contract and verifier; a plain caller-constructed dataclass is insufficient, so the proof must be authenticated or resolved through a trusted issuer/verifier.

**Verdict:** selected.

### Rejected hybrid — kernel re-evaluates policy and also validates proof

This duplicates the authority decision at two times and can produce contradictory answers from changed posture/rules/catalog state. The kernel should validate whether a prior grant is still valid, not create a second policy decision for the same attempt.

---

## 6. Selected design and rationale

**Selected contract: Design B.**

The authority pipeline becomes:

```text
Intent / plan / discovery
        |
        v
Policy evaluation + capability admission
        |
        v
immutable ExecutionAuthorization
        |
        |  authenticated + durably recorded
        v
ExecutionKernel.execute(manifest, authorization)
        |
        |  validate proof + exact binding + freshness
        v
mechanical adapter invocation
        |
        v
ExecutionResult + execution evidence
```

The kernel is an **authorization verifier**, not an authorization decider. It MUST NOT infer authority from intent, trust, discovery, capability metadata, or the mere presence of an allow-shaped object.

This design best fits the existing architecture because `RIFRuntime` already owns orchestration and governance while `ExecutionKernel` is capability-specificity-free. The missing circuit component is a cryptographically or otherwise verifier-authenticated handoff between those layers.

---

## 7. Authorization object / boundary contract

The initial contract name is **`ExecutionAuthorization`**.

An `ExecutionAuthorization` is immutable after issuance and MUST contain, at minimum:

| Field | Required binding |
|---|---|
| `schema_version` | Versioned authorization contract |
| `authorization_id` | Stable identifier for this issued grant |
| `run_id` | Owning Run from the identity spine |
| `decision_id` | Decision whose authority is being exercised |
| `actor` | Authorized actor identity |
| `capability` | Exact executable capability identifier |
| `action` | Exact authorized action |
| `effective_target` | Exact target used for authorization; `manifest.target` or the capability identifier when target is absent |
| `operation_digest` | SHA-256 over canonical operation data: actor, capability, action, effective target, parameters, and manifest metadata; `manifest_id` is excluded as correlation-only |
| `capability_snapshot_id` | Decision-bound capability observation, using the capability-snapshot review's explicit absence sentinel where applicable |
| `admission_id` | Immutable reference to the admission event/basis for the executable capability |
| `environment` | Environment under which authority was issued |
| `issued_at` | Issuance time |
| `expires_at` | Optional time bound; when present it is enforced |
| `proof` | Authenticator over the complete authorization payload |

### 7.1 Proof requirements

The `proof` MUST be unforgeable to ordinary callers of the execution API. A frozen object type or private constructor alone is not sufficient in Python.

A conforming first implementation MAY use HMAC over a canonical serialization with a verifier-held key, following the existing Metasploit token pattern, or MAY use an opaque authorization identifier resolved by a trusted verifier. In either case:

- callers cannot self-assert a valid grant;
- mutation of a signed/committed field invalidates the grant;
- the kernel can distinguish authentic issued authority from structurally similar input;
- failure to verify is a denial before adapter invocation.

### 7.2 Operation digest

For version 1, `operation_digest` is the SHA-256 digest of RFC8785-JCS canonical JSON over:

```text
{
  actor,
  capability,
  action,
  effective_target,
  parameters,
  metadata
}
```

`manifest_id` is excluded so a mechanically retried attempt can receive a new correlation ID without changing its authority. Any other field that can alter dispatch or adapter-visible semantics MUST be included in the digest; a future exclusion requires a contract-version change.

### 7.3 Decision and admission semantics

A policy `allow` is necessary but not sufficient. Capability admission is necessary but not sufficient. **Execution authority exists only when both are represented in a valid `ExecutionAuthorization` for the exact operation.**

A mechanical retry of the same operation MAY reference the same `authorization_id` and `decision_id`. If actor, capability, action, effective target, parameters, metadata, capability snapshot, or required authority changes, the old authorization is inapplicable and a new Decision/authorization is required. If the capability's admission basis changes, a new admission event is also required.

### 7.4 Adapter containment

`CapabilityRegistry.resolve()` and `Capability.execute()` are mechanical implementation surfaces, not authority surfaces. A conforming implementation MUST ensure production callers cannot use them to perform effects outside the authorization-verifying boundary.

The preferred implementation shape is for the kernel to be the sole component that obtains effectful adapter handles. If an adapter must remain independently callable for technical reasons, its effectful entry point MUST require a kernel-issued execution context that is itself bound to a successfully validated `ExecutionAuthorization`.

---

## 8. Failure semantics

The boundary fails closed.

| Condition | Required behaviour |
|---|---|
| Authorization missing | Reject before adapter invocation |
| Proof invalid/unverifiable | Reject before adapter invocation |
| Authorization expired | Reject before adapter invocation |
| Authorization explicitly revoked or stale under current governance state | Reject; caller must re-enter governance and obtain a new Decision/authorization |
| `run_id` / `decision_id` mismatch | Reject |
| Actor mismatch | Reject |
| Capability mismatch | Reject |
| Action mismatch | Reject |
| Effective-target mismatch | Reject |
| Operation-digest mismatch | Reject |
| Capability-snapshot mismatch | Reject |
| Admission reference invalid/missing | Reject |
| Authorization evidence cannot be committed before effect | Reject |

A rejection at this boundary is an authorization failure, not an adapter failure, and MUST NOT invoke the adapter as part of error handling.

If an effect has already occurred and subsequent execution-evidence persistence fails, the runtime MUST NOT silently retry the effect. It must surface an evidence-generation failure that preserves the fact that effect status is uncertain or already occurred. This review does not redesign the post-effect evidence store.

---

## 9. Replay and evidence implications

Replay SHALL reconstruct the recorded chain:

```text
Run
  -> Decision
  -> ExecutionAuthorization
  -> Execution attempt(s)
  -> Result / Observation / Evidence
```

Replay MUST treat an `ExecutionAuthorization` as historical evidence, not as a live credential. A replay-deserialized authorization SHALL NOT be accepted directly by an execution API merely because its historical proof is present.

Recovery remains separate from replay. Recovery that intends to produce a new effect must re-enter the live authorization-verification boundary. If the existing Decision and authorization remain valid for an identical operation, a mechanical retry may continue under that authority; if authority is stale or the operation changes, a new Decision is required.

The authorization record must be append-only in meaning: later revocation/supersession is represented by a new event, not mutation of the original authorization payload.

---

## 10. Compatibility with existing specification reviews

### Identity spine migration

**Compatible.** This review adopts the identity-spine separation of `Decision` from `Execution`: one Decision may govern multiple mechanical Execution attempts, while changed intent/authority/parameters requires a new Decision. `ExecutionAuthorization` is decision-scoped evidence consumed by one or more identical mechanical retries; it does not become a new aggregate root.

This review does not decide identity-spine migration sequencing or persistence keys. `run_id` and `decision_id` are normative target fields; implementation must sequence with the identity-spine migration rather than invent a competing identity model.

### Capability snapshot authority

**Compatible.** The capability-snapshot review binds one `capability_snapshot_id` to a Decision and forbids re-observation per mechanical attempt. This review carries that resolved snapshot identity into `ExecutionAuthorization` so the kernel can reject authority accidentally applied to a different observed capability world.

This review does not resolve OD-C1 through OD-C5. In particular, it does not decide whether `capability_snapshot_id` is physically stored on `PolicyDecision` or on the future first-class `Decision`; it only requires the resolved value to be present in the execution authorization handoff.

Both reviews agree that replay is read-only reconstruction and recovery is a separate effect-producing concern.

---

## 11. Open-PR conformance assessment

| PR | Classification | Assessment |
|---|---|---|
| **#164 — agent identity / evidence-driven capability trust** | **REQUIRES ADAPTATION** | Identity, declarations, evaluations, and trust are valid governance/admission inputs, but trust or registry `authorize()` output is not itself execution authority. The branch still leaves `RIFRuntime.execute_capability()` calling the kernel without an immutable authorization proof; its admission/trust result must feed the Decision/admission basis from which `ExecutionAuthorization` is issued. |
| **#165 — resource discovery** | **CONFORMS** | The PR explicitly treats discovered candidates and relevance scores as observations rather than authorization and does not invoke discovered resources. Promotion from discovery to execution must still pass snapshot/Decision/admission/authorization, but the PR's scoped discovery architecture does not bypass this boundary. |
| **#171 — governed GitHub MCP gateway** | **REQUIRES ADAPTATION** | `call_tool()` evaluates policy and then directly invokes the downstream MCP client. That reproduces the same caller-enforced seam as F7 outside `ExecutionKernel`; read-only scope lowers consequence but does not change the authority model. The effectful forwarding boundary must consume/validate `ExecutionAuthorization` or route through a kernel-equivalent verifier before `client.call_tool()`. |
| **#172 — governed skill runtime** | **CONFORMS** | `SkillRuntime` treats a skill as procedure, not authority, and delegates every step to `RIFRuntime.execute_capability()` rather than calling the kernel or adapter directly. Once `execute_capability()` issues `ExecutionAuthorization` and the kernel validates it, the skill layer inherits the boundary without a parallel authority model. |

No PR is repaired by this review.

---

## 12. Required implementation tests

A future implementation is incomplete unless tests prove all of the following:

1. `ExecutionKernel.execute()` with no authorization fails before adapter invocation.
2. A caller-constructed or forged authorization fails before adapter invocation.
3. A valid authorization for another actor fails.
4. Capability, action, target, parameter, or metadata changes produce an operation-digest mismatch and fail.
5. A missing/invalid admission reference fails.
6. A capability-snapshot mismatch fails.
7. Expired, revoked, or stale authority fails.
8. A valid exact-match authorization invokes the adapter once and records the `authorization_id` on execution evidence.
9. An identical mechanical retry may use the same Decision/authorization without acquiring broader authority.
10. A retry with changed parameters/target/capability cannot reuse the old authorization and requires a new Decision.
11. Direct production use of `CapabilityRegistry.resolve()` / `Capability.execute()` cannot create an effect without the kernel-validated execution context.
12. Failure to commit authorization evidence prevents the effect.
13. Replay reconstructs authorization/execution history without invoking kernel, verifier issuance, or adapter code.
14. A stricter posture or explicit authority revocation between issuance and execution causes the verifier to reject the stale grant without re-running policy inside the kernel.
15. Existing governed callers (`RIFRuntime`, SkillRuntime once rebased, and MCP gateways once adapted) all cross the same proof-verifying execution boundary.

---

## 13. Migration / compatibility implications

1. Add an immutable `ExecutionAuthorization` contract and verifier.
2. Change `RIFRuntime.execute_capability()` to issue/commit authorization only after policy allow and successful admission, then pass it to the kernel.
3. Change `ExecutionKernel.execute()` so an authorization argument is mandatory and validated before adapter invocation.
4. Convert capability admission from mutable lifecycle state as the only evidence into an immutable admission event/reference suitable for `admission_id`; lifecycle state may remain as a projection, not authority proof.
5. Contain raw adapter resolution so production code cannot use `Capability.execute()` as a parallel execution API.
6. Record `authorization_id` and relevant decision/admission references in execution evidence.
7. Sequence `run_id` / `decision_id` integration with the identity-spine migration; do not create a competing execution-root identity.
8. Adapt direct/manual kernel demos and tests so they either exercise explicit denial without authorization or obtain a test authorization through the same verifier path.

This migration is intentionally a separate implementation task. Until it lands, documentation must continue describing the current boundary as caller-enforced.

---

## 14. Explicit non-goals

This review does **not**:

- implement the selected runtime change;
- redesign the identity spine;
- redesign capability snapshot construction, retention, or OD-C1–OD-C5;
- create MCP write authority or broaden any existing MCP capability;
- introduce autonomous execution;
- redesign persistence generally;
- redesign policy evaluation;
- redesign capability trust scoring;
- refactor unrelated governance code;
- make replay a recovery path;
- define a general distributed authorization service.

One seam, one decision: **mechanical execution requires authenticated proof of prior governance and admission for the exact operation.**

---

## 15. Approval status and next implementation step

**Approval status:** `Draft / Open Review`.

**Architectural decision:** **SELECTED — Design B, kernel consumes and validates immutable proof of prior authorization.** The central authority model is not open.

**Next implementation step after approval:** create one narrowly scoped runtime PR that introduces `ExecutionAuthorization` + verifier, changes the kernel signature to require it, updates `RIFRuntime.execute_capability()` to issue it after policy/admission, and adds the Section 12 boundary tests. Do not combine that PR with identity-spine migration, capability-snapshot redesign, MCP write enablement, or persistence refactoring.

The implementation PR is complete only when a direct kernel call without valid authorization is demonstrably unable to invoke an effectful adapter.