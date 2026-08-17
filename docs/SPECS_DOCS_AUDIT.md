# Specification & Documentation Audit

**Scope:** `spec/`, `contracts/`, `docs/`, and root-level `*.md`, audited against
`src/rif_runtime/`, `supabase/migrations/`, `config/`, and `tests/` as of
`pyproject.toml` version `0.3.0rc2`.

**Method:** every normative claim that names a module, route, identifier, table,
or constant was checked against the referenced source. Findings are grouped by
severity; each carries the evidence that establishes it.

**Standing principle used throughout:** per `CLAUDE.md` and `spec/README.md`,
`src/rif_runtime/api.py` is the source of truth for the API surface, and `spec/`
is normative for contracts. Where a doc contradicts code, the doc is the defect
*unless* the doc is a spec — in which case the finding is that the implementation
has not caught up, and the spec must say so rather than claim conformance.

---

## Summary

| # | Finding | Severity |
|---|---|---|
| H1 | `docs/DATA_MODEL.md` claims to be the schema source of truth; the shipped migration shares zero tables with it | High |
| H2 | Three disjoint ADR series reuse the same numbers for different decisions | High |
| H3 | `spec/` schemas are byte-identical duplicates of `contracts/rif_familiar/`, contradicting ADR-0008; only the `contracts/` copies are tested | High |
| H4 | Root `ARCHITECTURE.md` documents eleven modules that do not exist, as current state | High |
| H5 | `spec/mcp/SPEC.md` gates on a `destructive` capability class the named classifier cannot return | High |
| M1 | `spec/mcp/SPEC.md` §4 lane order does not mirror `MetasploitGovernor.evaluate()` as claimed | Medium |
| M2 | Deny-reason identifiers renamed `msf.*` → `mcp.*` with no mapping table | Medium |
| M3 | Capability-token TTL: spec says 300 s, code defaults to 600 s in both call sites | Medium |
| M4 | `docs/API.md` lists a route that does not exist and omits eight that do | Medium |
| M5 | `spec/capability/README.md` points at an unrelated runtime module | Medium |
| M6 | Root-level duplicates of `docs/` files lack the accuracy notes their twins carry | Medium |
| M7 | Identity-spine spec review cites three nonexistent ADRs and skips a section | Medium |
| L1–L7 | Repository hygiene: junk file, misfiled ADR, committed archives, broken paths, stale fork | Low |

---

## High

### H1. `docs/DATA_MODEL.md` is contradicted by the only shipped migration

`docs/DATA_MODEL.md:1-9` declares itself "the canonical schema specification for
RIF Runtime's persistent state" and "the version-controlled source of truth." It
specifies twelve entities: `projects`, `users`, `agents`, `models`, `sessions`,
`prompts`, `tools`, `policies`, `executions`, `execution_logs`, `artifacts`,
`memories`, `evaluations`, plus a six-file migration plan
(`0001_enums.sql` … `0006_rls.sql`).

The repository contains exactly one migration, `supabase/migrations/001_rif_tables.sql`,
creating `identities`, `execution_runs`, `evidence_ledger`, and `state_log`. **No
table name is common to both.** None of the six planned migration files exist.
`src/rif_runtime/integrations/supabase.py:114,129,149` writes to `evidence_ledger`
and `execution_runs` — the shipped names, not the specified ones.

Compounding this, `DATA_MODEL.md` makes `executions` "the hub" of the model,
while `docs/spec-review-identity-spine-migration.md:87` is normative that
`execution_id` "must never be used as a correlation key," with `Run` as the sole
aggregate root. The shipped code sides with the spec review — `run_id` is the key
in `src/rif_runtime/runs/schemas.py`, and `execution_id` appears **nowhere** in
`src/`. `DATA_MODEL.md` is the sole outlier against both the code and the spec.

**Recommendation:** demote `DATA_MODEL.md` from "source of truth" to a dated
design study, or rewrite it around `Run`. It cannot keep its current status claim.

### H2. Three disjoint ADR series collide on the same numbers

Three sets of ADRs coexist, and numbers 0001–0008 are used twice for entirely
different decisions:

| Number | `docs/adr-000N-*.md` | `rif-runtime-adrs.zip` |
|---|---|---|
| 0003 | `mcp-security-model` | `audit-as-evidence-sink` |
| 0004 | `readonly-vs-admin-mcp-workflow` | `memory-context-separation` |
| 0005 | `dev-staging-production-separation` | `replay-as-divergence-verification` |
| 0006 | `ai-safety-rationale` | `capability-gateway-uniform-control` |
| 0007 | `database-development-workflow` | `adaptation-future-executions-only` |
| 0008 | `agentos-rif-v1-architecture` | `documentation-generated-artifact` |

A third series lives in `docs/adr/` using a different case convention
(`ADR-0026-resource-contracts.md`, `ADR-0027-cloud-bootstrap-without-ensurepip.md`),
leaving 0009–0025 unaccounted for. Since ADR-0008 is cited as normative
throughout `spec/` (`spec/README.md:9`, `spec/mcp/SPEC.md:3`), an ambiguous
ADR-0008 undermines every spec that references it.

**Recommendation:** pick one series and one location, renumber the collisions,
and record the renumbering in an index ADR.

### H3. `spec/` duplicates `contracts/`, against ADR-0008's explicit instruction

ADR-0008:53-54 states: "Existing `contracts/rif_familiar/` schemas are the seed
for `spec/capability/` and `spec/skill/` — **migrate rather than duplicate**."

What shipped is duplication. All three schemas are byte-identical between the two
trees (verified by `diff`; all report no differences):

- `contracts/rif_familiar/capability_manifest.schema.json` ≡ `spec/capability/…`
- `contracts/rif_familiar/observation_event.schema.json` ≡ `spec/evidence/…`
- `contracts/rif_familiar/posture_decision.schema.json` ≡ `spec/governance/…`

The three `spec/*/README.md` files each describe their schema as "migrated
unchanged," and `spec/README.md:26-30` is candid that `contracts/rif_familiar/`
"is left in place unchanged for this slice." But a copy left in place is a
duplicate, not a migration, and the divergence risk is not hypothetical:
`tests/test_rif_familiar_contracts.py:9` binds validation to
`ROOT / "contracts" / "rif_familiar"` only. **The `spec/` copies have no test
coverage at all** and can drift from the tested originals silently.

Note also that ADR-0008 names `spec/capability/` and `spec/skill/` as the seed
targets; the actual seeding went to `capability/`, `governance/`, and `evidence/`,
while `skill/` remains a placeholder. The divergence is defensible but undocumented.

**Recommendation (smallest sufficient fix):** parametrize
`tests/test_rif_familiar_contracts.py` over both roots, or add a test asserting
the two trees are byte-identical, so the duplication cannot rot unobserved. Then
decide the re-export-vs-retire question `spec/README.md:29-31` defers.

### H4. Root `ARCHITECTURE.md` documents a module tree that does not exist

`ARCHITECTURE.md` presents a component breakdown and a directory tree as current
fact. Eleven of the modules it names are absent from `src/rif_runtime/`:

| `ARCHITECTURE.md` claims | Actual |
|---|---|
| `execution/compiler.py`, `execution/models.py`, `execution/executor.py`, `execution/sandbox.py` | only `execution/{kernel,manifest,result,state,exceptions}.py` |
| `governance/graph.py` | `graph/memory.py` |
| `governance/policy_store.py` | `configuration/policies.py` |
| `governance/reflexive_loop.py` | `governance/reflexive.py` |
| `storage/decision_store.py`, `storage/posture_store.py` | `storage/jsonl.py` |
| `capabilities/adapter.py` | absent (`capabilities/` has `capability.py`, `echo.py`, `registry.py`) |
| `config/capabilities.yaml` | absent (`config/` contains only `environments.yaml`) |

This is the most consequential of the stale docs because `NEXT_STEPS.md:18`
directs a new operator to "Read `ARCHITECTURE.md` to understand system design" as
step one. It is also 262 lines against the 9-line `docs/ARCHITECTURE.md`, so a
reader will reasonably treat the root file as authoritative.

**Recommendation:** correct the tree against `src/`, or mark the aspirational
sections explicitly the way `docs/api-reference.md` and `docs/cli-reference.md`
already do with their "planned, not yet implemented" notes.

### H5. The MCP hard gate keys off a capability class that cannot be produced

`spec/mcp/SPEC.md` §5 defines a three-class taxonomy — `read_only`,
`consequential`, `destructive` — and §5:126-128 names the implementation
normative: "Classification reuses the existing `capabilities.classify` /
`is_severe` machinery (`src/rif_runtime/mcp/capabilities.py`) … new servers
extend the catalog, they do not fork the classifier."

`src/rif_runtime/mcp/capabilities.py:22-27` defines:

```python
class CapabilityClass(StrEnum):
    read_only = "read_only"
    consequential = "consequential"
    unknown = "unknown"
```

There is **no `destructive` member**, and `classify()` (lines 91-97) can only
return one of those three. Severity is a separate, orthogonal boolean predicate,
`is_severe()` (lines 100-101), backed by `SEVERE_CAPABILITIES`.

This matters because the spec's entire security centre of gravity hangs off that
class. §4.7 ("A `destructive` capability … MUST pass the full §6 hard gate") and
§6 (the seven-check gate) are conditioned on a classification the named normative
classifier can never return, and §11's GREENLIGHT criteria make the destructive
gate a named pass/fail criterion. As written, a conformance checker reading the
spec literally would find the gate unreachable.

Additionally, the spec's `unknown` case is unaddressed: C7 requires
"an unclassified or unregistered tool is denied," and the implementation does deny
`unknown` by routing it through the consequential path — but the spec never maps
`unknown` onto its three-class model.

**Recommendation:** decide whether `destructive` becomes a real fourth
`CapabilityClass` member (with `SEVERE_CAPABILITIES` promoted into it), or whether
the spec should define destructive as `consequential ∧ is_severe()`. Either is
defensible; the current text asserts a mapping that does not exist. This is a
design decision for the spec owner, not a documentation fix, so it is flagged
rather than resolved here.

---

## Medium

### M1. §4's lane order does not mirror the implementation it cites

`spec/mcp/SPEC.md:78-81` states the ordered lanes "mirror
`MetasploitGovernor.evaluate()` and MUST be preserved." Comparing directly:

| Spec §4 lane | `MetasploitGovernor.evaluate()` |
|---|---|
| §4.1 posture gate | `metasploit.py:249` ✅ same position |
| §4.2 egress gate | **not in the governor at all** — the egress check lives in `PolicyEngine.evaluate()` (`policy.py:76-85`), a different component on a different call path |
| §4.3 injection quarantine | `metasploit.py:261` — but *second*, not third |
| §4.4 read-only fast-path | `metasploit.py:278` — third, not fourth |
| §4.5 consequential authority | split across three `GovernanceMode` lanes (`read_only_firewall`, `shadow`, `lab_broker`, lines 290-314) that §4 does not mention |

The `GovernanceMode` enum is the governor's central structuring concept and is
absent from the spec entirely. The spec is also broader on §4.3's scan surface
(it adds tool descriptions, server metadata, and returned tool results;
`scan_for_injection` covers only `intent.text`, `intent.untrusted_context`, and
recursed `params`).

Framework-level generalization is legitimate — but "mirrors … MUST be preserved"
asserts present-tense conformance that does not hold.

**Recommendation:** replace the mirror claim with an explicit conformance-delta
table separating "already implemented" from "required of the framework."

### M2. Deny-reason identifiers were renamed with no mapping

The spec's reason strings use an `mcp.*` namespace; the implementation emits
`msf.*`. Only two of the spec's identifiers actually exist in code:

| Spec | Code | Status |
|---|---|---|
| `posture.locked` | `posture.locked` (`metasploit.py:256`) | ✅ match |
| `mcp.egress.disabled` | `mcp.egress.disabled` (`policy.py:84`) | ✅ match |
| `mcp.injection.quarantined` | `msf.injection.quarantined` | ✗ |
| `mcp.capability.read_only` | `msf.capability.read_only` | ✗ |
| `mcp.authority.absent` | `msf.capability.execution_absent` / `msf.broker.approval_absent` | ✗ |
| `mcp.gate.*` (7 reasons, §6) | `msf.broker.*` | ✗ |

Because these strings are persisted into `EvidenceEvent.matched_rule` and are the
audit trail's primary index, an undocumented rename is a replay hazard: a query
written against the spec finds nothing in the log.

**Recommendation:** add the mapping table to §6, and state whether the `msf.*`
identifiers are to be renamed (a breaking change to historical evidence) or
retained as the reference lane's namespace under a framework-level scheme.

### M3. Capability-token TTL disagrees with the implementation

`spec/mcp/SPEC.md:141-143` — "Default TTL **300 s**; authority is time-bound."

Both call sites default to 600 s:
- `src/rif_runtime/mcp/metasploit.py:219` — `ttl_seconds: int = 600`
- `src/rif_runtime/api.py:195` — `ttl_seconds = int(payload.get("ttl_seconds", 600))`

A doubled default on a security-critical time bound is worth reconciling
deliberately: either the spec's 300 s is the intent and the code should tighten,
or the spec should record 600 s. Note the spec is correct that TTL is enforced
(`metasploit.py:350`) and that the intent hash excludes free-text fields
(`intent_hash()` covers `tool`, `capability`, `target`, `scope_id`, `params` and
omits `text` / `untrusted_context`, exactly as §6 requires).

Two further §6 requirements are genuinely unimplemented, and the spec is honest
about one: single-use `token_id` enforcement (§6.4) has no spent-token store —
acknowledged as "New requirement beyond the metasploit broker; see OD-3."

### M4. `docs/API.md` is both wrong and incomplete

`CLAUDE.md` already flags this route as a known gotcha; it remains unfixed, and
the drift has widened. `docs/API.md` lists `POST /v1/runtime/reset-posture`, which
does not exist — the actual route is `POST /v1/posture/reset` (`api.py:100`).

Eight live routes are undocumented there:

`GET /`, `GET /v1/graph/summary`, `POST /v1/posture/{posture}`,
`GET /v1/recovered-state`, `GET /v1/policies`, `PUT /v1/policies/{rule_id}`,
`DELETE /v1/policies/{rule_id}`, and `POST /v1/runs`.

`POST /v1/runs` (`api.py:234`) is the newest surface and is documented **nowhere** —
not in `docs/API.md`, `docs/RIF_RUNTIME_MVP.md`, `README.md`, or the API surface
block in `CLAUDE.md`. It is also the only route using Supabase JWT identity
(`IdentityId`) rather than `ControlPlaneAuth`, which is a security-relevant
distinction no document currently records.

**Status: being fixed elsewhere.** PR #110 (`claude/doc-sync`) is a dedicated
API-surface sync that corrects `docs/API.md`, `docs/RIF_RUNTIME_MVP.md`, and
`README.md` together, including per-route descriptions and the auth split above.
This audit deliberately leaves `docs/API.md` untouched so the two changes do not
conflict on the same file. If #110 is abandoned, this finding reverts to open.

Note that `CLAUDE.md`'s own API-surface block is a third copy of the same list and
is malformed — the routes after the first `GET /` are run together on one line with
literal `\n` escapes rather than newlines. #110 does not cover `CLAUDE.md`.

### M5. `spec/capability/README.md` points at an unrelated module

The file ends: "Runtime implementation: `src/rif_runtime/mcp/capabilities.py`."

`spec/capability/capability_manifest.schema.json` is the RIF Familiar device
manifest — `$id: rif://contracts/rif-familiar/capability-manifest/v0.1`, with a
required `esp32-c5` hardware platform, Wi-Fi/BLE observation grants, relay policy,
and observation budgets. `src/rif_runtime/mcp/capabilities.py` is the Metasploit
MCP tool taxonomy (`CONTRACT_VERSION = "msf-governance/v1"`). The two share a word,
not a subject.

The schema's only actual consumer is `tests/test_rif_familiar_contracts.py`.

*Fixed in this change — see "Corrections applied" below.*

### M6. Root-level duplicates lack their twins' accuracy notes

Three files exist at root and again under `docs/`, and in each case the `docs/`
copy has been corrected while the root copy has not:

| File | Root copy | `docs/` copy |
|---|---|---|
| `cli-reference.md` | documents `execute`, `evidence`, `telemetry`, `validate`, `policy` as if real | carries a note that these are planned; real commands are `serve`, `check`, `replay`, `msf-check` |
| `mcp-integration-guide.md` | shows an `mcp.servers` YAML block as if configurable | carries a note that no such config block exists |
| `ARCHITECTURE.md` | 262 lines, stale module tree (H4) | 9 lines, accurate but minimal |

`release-engineering-guide.md` exists only at root and is entirely aspirational
(signing, compatibility matrix, evidence bundles) with no note at all.

The corrected `docs/` copies confirm someone already did this audit work once; the
root duplicates silently undo it. Verified against `src/rif_runtime/cli.py`, whose
commands are `serve`, `check`, `replay`, and `msf-check`.

**Recommendation:** delete the root duplicates, or replace each with a one-line
pointer to its `docs/` counterpart.

### M7. The identity-spine spec review cites ADRs that do not exist

`docs/spec-review-identity-spine-migration.md` is normative in tone ("Governs:
ADR-0010", "binding on all future migrations") and repeatedly cites **ADR-0010,
ADR-0012, and ADR-0015** — lines 4, 8, 16, 70, 72, 118, 129, 158. None exists in
`docs/`, `docs/adr/`, or either committed archive. Its ratification checklist
(§11) requires "ADR-0010 is updated to reference this document as its
implementation authority," which cannot be satisfied.

The document also jumps from §11 to §13 — there is no §12 — which suggests a
section was dropped during editing.

One time-sensitive item: §7 scopes the `execution_id` deprecation window as
`v0.2.x → v0.3.0`, with input aliases "removed at `v0.3.0`." The project is now at
`0.3.0rc2`, so that removal is due. The good news is that the code is already
clean — `execution_id` has zero occurrences in `src/` — so the deprecation appears
complete in practice and only the checklist is stale.

---

## Low (hygiene)

- **L1. `tem]`** — a 6.9 KB file at repo root containing ANSI-escaped terminal
  output from `bat` rendering an old `pyproject.toml` (showing `version = "0.2.0"`;
  current is `0.3.0rc2`). Plainly the residue of a shell redirect typo. Safe to delete.
- **L2. Misfiled, duplicated ADR-0001** — `nse-5696690746429404181-3311.md` and
  `nse-5696690746429404181-3311-1.md` are byte-identical copies of
  "ADR-0001: Governance as subsystem, not decorators," sitting at root under
  machine-generated names. ADR-0001 is otherwise missing from `docs/`. Should be
  deduplicated and filed with the other ADRs (subject to the H2 renumbering).
- **L3. Committed archives** — `rif-runtime-adrs.zip` and
  `rif-runtime-specification-docs.zip` hold 15 markdown files as opaque binaries,
  invisible to review, search, and diff. The second contains
  `governance-specification.md`, `replay-semantics-specification.md`,
  `capability-manifest-specification.md`, and `runtime-constitution.md` — material
  that belongs in `spec/`, where `replay/`, `state/`, and `skill/` are still
  placeholders. Worth extracting before the placeholders get written from scratch.
- **L4. Broken path references** — docs cite files that do not exist:
  `spec/openapi.yaml` (`CONTRIBUTING.md`, `DEVELOPMENT.md`), `docs/POLICIES.md`,
  `docs/CAPABILITIES.md`, `docs/EXAMPLES.md`, `docs/KUBERNETES.md`,
  `docs/TROUBLESHOOTING.md`, `config/policies.yaml`, `config/capabilities.yaml`
  (`config/` holds only `environments.yaml`), `rif_runtime/governance/models.py`,
  `tests/unit/test_injection_prevention.py` and `tests/e2e/test_replay_determinism.py`
  (neither `tests/unit/` nor `tests/e2e/` exists).
- **L5. Skill package filename** — `spec/skill/README.md` proposes a schema for
  `skill.yaml` based on `.claude/skills/run-rif-runtime/`, but that directory
  contains `manifest.yaml`, not `skill.yaml`. *Fixed below.*
- **L6. `notebooklm/` is a stale fork** — a nine-file copy of `docs/` frozen at the
  v0.2.x era. Its `README.md` badge advertises "tests 14 passing" (the suite now has
  26 test modules), and its `docs/API.md` predates the Metasploit routes. It is
  unreferenced by any other document; either wire it to a generator or drop it.
- **L7. Trust-tier models disagree** — `docs/DATA_MODEL.md:64` types
  `agents.trust_tier` as "T0–T3"; `spec/mcp/SPEC.md` §3 defines five tiers, T0–T4,
  with T4 (embedded content) carrying the load-bearing zero-authority property. A
  `smallint` sized to the older model cannot express the spec's tier set.

---

## Corrections applied in this change

Only unambiguous factual errors — cases where a document misstates what the code
does — were corrected. Design-level divergences (H1, H2, H5, M1, M2, M3) are
reported, not silently resolved, because each requires an owner's decision about
which side should move.

- `docs/API.md` — **deliberately untouched.** PR #110 is a dedicated API-surface
  sync covering this file plus `README.md` and `docs/RIF_RUNTIME_MVP.md` together;
  editing it here would only produce a conflict on the same file. See M4.
- `spec/capability/README.md` — corrected the runtime-implementation pointer.
- `spec/skill/README.md` — corrected `skill.yaml` to `manifest.yaml`.
- `spec/README.md` — replaced "migrated" with an accurate description of the
  duplicate-and-defer state, and recorded the test-coverage gap from H3.
- `spec/mcp/SPEC.md` — added §14, a conformance-delta table recording, per
  requirement, what the implementation does today. Normative requirements are
  unchanged; only the false present-tense conformance claims are corrected.

## Suggested sequencing

1. **H3's test gap** — smallest change, removes an active silent-drift risk.
2. **H2 ADR renumbering** — every spec cites ADR-0008; the ambiguity blocks
   clean resolution of H5 and M7.
3. **H5 destructive-class decision** — unblocks the MCP framework's conformance story.
4. **H1 / H4** — restate or retire the two documents making false source-of-truth claims.
5. **M6 / L1–L3** — hygiene; mechanical and independently mergeable.
