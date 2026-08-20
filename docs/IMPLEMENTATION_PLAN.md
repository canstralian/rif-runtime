# RIF Runtime — Prioritized Implementation Plan

Source inputs:

- Security audit: [Full repository security audit](https://cursor.com/agents/bc-3fa5ab67-d462-4406-b959-f87633e096ca) (2026-07-21)
- Dev setup: [PR #37 — Set up development environment + AGENTS.md](https://github.com/canstralian/rif-runtime/pull/37)
- Architecture direction: [ADR-0008](adr-0008-agentos-rif-v1-architecture.md) (PR #33) and existing [ROADMAP.md](ROADMAP.md)

This plan is ordered strictly: **security Critical/High → Medium → tooling/CI/governance → architecture milestones**. Do not start architecture slices that depend on deny-by-default or authenticated mutation until Phase 0 and Phase 1 High items are merged.

---

## Audit snapshot

| Severity | Count | Status |
| --- | ---: | --- |
| Critical | 0 | — |
| High | 2 | Open — fix first |
| Medium | 3 | Open — fix next |
| Low | 1 | Open |
| Informational | 2 | Tooling limits only |

Audit method: dependency inventory, policy/API review, Bandit SAST, `pip-audit`, `detect-secrets`, Ruff/MyPy/Pytest. No known vulnerable packages; Bandit and secret scan clean. 86 tests passing at audit time.

---

## Phase 0 — Critical and High security fixes

**Critical:** none. Proceed directly to High.

### H1 — Authenticate the mutable API control plane

**Finding:** Environment switch, posture mutation, Metasploit token minting, and policy CRUD are unauthenticated. Risk is high if `rif serve` is bound beyond localhost.

**Affected:** `src/rif_runtime/api.py`, `src/rif_runtime/cli.py`

**Mutable routes to protect:**

| Method | Path | Risk |
| --- | --- | --- |
| `POST` | `/v1/environment/{name}` | Changes trust boundary |
| `POST` | `/v1/posture/{posture}` | Force posture |
| `POST` | `/v1/posture/reset` | Clear escalations |
| `PUT` | `/v1/policies/{rule_id}` | Rewrite allow/deny |
| `DELETE` | `/v1/policies/{rule_id}` | Remove rules |
| `POST` | `/v1/mcp/metasploit/token` | Mints capability tokens |
| `POST` | `/v1/mcp/invoke` | Triggers governed MCP evaluation (keep gated or authenticated) |

Read-only surfaces (`/health`, `/v1/environments`, summaries, `/v1/audit`, `/v1/policies` GET) may remain open for local MVP, or require a weaker read token — decide in the PR.

**Implementation steps:**

1. Add `RIF_API_TOKEN` (or split `RIF_ADMIN_TOKEN` / `RIF_READ_TOKEN`) loaded from env; refuse start in non-local mode if missing.
2. Add FastAPI dependency (`require_admin`) using `Authorization: Bearer …` with `hmac.compare_digest`.
3. Apply dependency to all mutable routes above.
4. Gate external bind: `rif serve` / uvicorn `--host 0.0.0.0` requires admin token configured (fail closed).
5. Document token setup in `README.md` / `SECURITY.md`; never log the token.
6. Keep CLI `rif check` local-process path unauthenticated (same trust as local Python).

**Acceptance criteria:**

- [ ] Unauthenticated `PUT/DELETE /v1/policies/*`, posture, environment, and token mint return `401`.
- [ ] Valid admin token succeeds; wrong token returns `401` (constant-time compare).
- [ ] Binding to non-loopback without token configured fails at startup.
- [ ] Audit log records actor identity for authenticated mutations (or a stable `principal` field).

**Tests (minimum):**

- `tests/test_api_auth.py`: 401 without token; 200 with token; 401 with wrong token on each mutable route.
- Startup bind guard unit/integration test.
- Existing smoke + policy tests still pass when token is supplied via fixture.

**Dependencies:** none. Blocks Medium M1 (token mint auth) and architecture control-plane work.

---

### H2 — Make policy truly deny-by-default

**Finding:** Wildcard rules (including seeded `deny_unknown_by_default`) are skipped in `PolicyEngine.evaluate()`. Unmatched requests fall through to `matched_rule="default.allow"`.

**Affected:** `src/rif_runtime/policy.py`, `data/policies.json`, CLAUDE.md gotcha on exact-match-only rules.

**Implementation steps:**

1. Define explicit precedence (document in `docs/DATA_MODEL.md` or a short ADR):
   1. `posture.locked` → deny
   2. Exact (non-wildcard) allow/deny rules
   3. Built-in package / MCP / network host constraints
   4. Partial wildcards (`action=*` xor `target=*`) by specificity
   5. Full `*/*` deny/allow rules
   6. **Final fallback: deny** (`default.deny`), never `default.allow`
2. Stop skipping all wildcard rules; implement `rule_matches` precedence so `deny_unknown_by_default` is live.
3. Replace the terminal `Decision.allow` / `default.allow` path with deny unless a prior rule/constraint allowed.
4. Re-seed / review `data/policies.json` so intended allows remain explicit (host rules + any non-network allows).
5. Update explainability strings and docs that mention `default.allow`.
6. Fix CLAUDE.md gotcha to describe the new precedence.

**Acceptance criteria:**

- [ ] Unknown action/target → `decision=deny`, `matched_rule` is `default.deny` or `policy.deny_unknown_by_default`.
- [ ] Known allow (e.g. `https://api.anthropic.com` under `http.request`) still allows.
- [ ] Network host deny and package/MCP egress denies unchanged.
- [ ] Locked posture still denies everything first.
- [ ] Wildcard deny no longer inert; tests prove it matches when no more-specific allow exists.
- [ ] Replay of historical decisions with old `default.allow` remains readable (do not rewrite JSONL); new decisions use new rule ids.

**Tests (minimum):**

- Deny-by-default for unmatched action (e.g. `shell.exec` / novel action).
- Explicit allow still wins over wildcard deny.
- Specific deny wins over broader allow (conflict matrix).
- Network limited-host path regression (`blocked.example.com` → deny + posture escalate).
- Explainability / causal-path regression updated for new fallback rule id.
- Policy-store integration: upserting a wildcard deny is effective.

**Dependencies:** none. Required before Milestone A (deterministic governance) and any capability router that assumes deny-by-default.

---

## Phase 1 — Medium and Low (complete before architecture expansion)

### M1 — Metasploit broker token minting

Any API caller can mint tokens with a free-form `approver`. After H1, minting requires admin auth; additionally:

- Require `approver` to match an allowlisted principal set (config or env).
- Reject missing/empty approver (no default `"human:operator"` in production mode).
- Tests: mint without allowlisted approver → 403/422; with allowlist → ok.

### M2 — Metasploit signing key

`RIF_MSF_BROKER_KEY` falls back to ephemeral random key.

- Fail closed in staging/production if unset.
- Allow ephemeral key only when `RIF_ENV=dev` / loopback (explicit opt-in).
- Tests: missing key in production mode raises; tokens verify across process restart when key set.

### M3 — Dependency pinning and `pip-audit` in CI

- Pin runtime and dev deps (lockfile or exact pins in `requirements*.txt`).
- Add `pip-audit` job/step to CI (fail on known vulns).
- Deduplicate `requirements-dev.txt` vs `pyproject.toml` optional-deps.

### L1 — `/v1/recovered-state` 500

Implement `RIFRuntime.recovered_summary()` (or remove the route). Add API test asserting 200 + expected shape.

---

## Phase 2 — Development tooling, CI, and repository governance

Baseline today (post PR #37 setup): Ruff/MyPy/Pytest run in CI; `ruff format` only in `quality.yml`; no `[tool.ruff]` / `[tool.mypy]` / `[tool.pytest]` / pre-commit / Black; Python 3.12 vs 3.13 drift between workflows; governance files mostly present.

### 2.1 Ruff

**Configure in `pyproject.toml`:**

```toml
[tool.ruff]
target-version = "py312"
line-length = 88
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM"]

[tool.ruff.format]
quote-style = "double"
```

**Acceptance:** `ruff check .` and `ruff format --check .` pass locally and in CI; CONTRIBUTING lists both.

### 2.2 Black

**Decision gate (pick one in the implementing PR):**

| Option | Recommendation | Rationale |
| --- | --- | --- |
| **A — Ruff format only** | **Preferred** | Repo already formats with Ruff; dual formatters fight. |
| **B — Black format + Ruff lint** | Acceptable | Disable `ruff format` in CI/pre-commit; add Black 24.x with `line-length = 88`. |

If the user mandate requires both packages installed: pin Black, add a `format-check` that runs **either** Black **or** Ruff format (not both), document the choice in CONTRIBUTING. Do not run Black and `ruff format` on the same tree.

**Acceptance:** Exactly one formatter is enforced in pre-commit + CI; style matches double quotes / trailing commas already used.

### 2.3 MyPy

Add to `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.12"
mypy_path = "src"
packages = ["rif_runtime"]
warn_return_any = true
warn_unused_ignores = true
# Tighten over time; start with ignore_missing_imports=true to match CI
ignore_missing_imports = true
```

**Acceptance:** `mypy src/rif_runtime` passes without ad-hoc CLI-only flags drifting from config; CI invokes `mypy` using pyproject config.

### 2.4 Pytest

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
filterwarnings = ["error::DeprecationWarning"]  # or narrow once Starlette/httpx warning fixed
```

Improve isolation: new persistence-touching tests use `tmp_path` (pattern in `tests/test_policy_store.py`); stop appending to shared `data/*.jsonl` from unit tests where practical.

**Acceptance:** `pytest` with no extra args matches CI; warning from audit addressed or explicitly filtered with a tracking comment.

### 2.5 Pre-commit

Add `.pre-commit-config.yaml`:

- `ruff` (lint `--fix`) + chosen formatter (Ruff format **or** Black)
- `mypy` (optional local hook; or keep MyPy CI-only if too slow)
- `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-merge-conflict`
- `detect-secrets` or rely on gitleaks workflow (prefer not duplicating noisily)

Document in CONTRIBUTING: `pip install pre-commit && pre-commit install`.

**Acceptance:** Fresh clone + `pre-commit run --all-files` passes; hooks match CI commands.

### 2.6 GitHub Actions CI

Unify and harden:

| Change | Why |
| --- | --- |
| Single Python matrix `3.12` (and optionally `3.13`) in `ci.yml` | End 3.12/3.13 drift vs `quality.yml` |
| Merge overlapping `ci.yml` + `quality.yml` gates or make `quality` format-only | Avoid duplicate divergent gates |
| Always run `ruff format --check` (or Black) in the required CI job | Format currently quality-only |
| Add `pip-audit` step (from M3) | Audit Medium finding |
| Bump `actions/checkout` / `setup-python` to current majors consistently | Version skew across workflows |
| Keep bandit, CodeQL, gitleaks, dependency-review as required or documented advisory | Security posture |
| Set `requires-python = ">=3.12"` in `pyproject.toml` | Declare support surface |

**Acceptance:** Required status checks on `main`: lint, format, mypy, pytest, secret scan; PR template checklist matches required checks.

### 2.7 Repository governance

Already present: `SECURITY.md`, `CONTRIBUTING.md`, `LICENSE`, `CODEOWNERS`, PR/issue templates, Dependabot.

**Complete:**

1. Merge/land `AGENTS.md` from PR #37 if not yet on `main`.
2. Extend PR template checklist with `ruff format --check` (or Black) and auth/governance impact for API changes.
3. Document branch-protection expectations in `docs/BRANCH_CLEANUP.md` or CONTRIBUTING: require PR reviews, required status checks, no direct push to `main`, dismiss stale reviews.
4. Add `CODE_OF_CONDUCT.md` only if desired (optional).
5. Ensure Dependabot security labels stay wired; consider grouping GitHub Actions updates.

**Acceptance:** CONTRIBUTING + PR template + CODEOWNERS + SECURITY form a closed loop; required checks listed explicitly.

---

## Phase 3 — Architecture milestone roadmap

Aligned with ADR-0008 and the existing roadmap, but sequenced after security and tooling. Each milestone is independently mergeable; later milestones must not start until listed dependencies meet acceptance.

```text
Phase 0 (H1, H2)
    → Phase 1 (M1–M3, L1)
    → Phase 2 (tooling/CI/governance)
    → A Deterministic governance + spec contracts
    → B Control plane skeleton
    → C Evidence system
    → D Capability packaging (skills/plugins)
    → E Reflexive healing L0–L3
    → F Controlled evolution
    → G Reference Space / demo
```

### Milestone A — Deterministic governance core + `spec/` contracts

**Goal:** Every decision is reconstructable; contracts live in `spec/`, not only in Python modules.

**Depends on:** H2 (deny-by-default), Phase 2 CI green.

**Work:**

- Stabilize explainability / causal-path contract (`explainability.py` + tests).
- Formalize policy precedence + frozen environment snapshots.
- Normalize audit, posture, decision record shapes.
- Extract `spec/replay/` and `spec/state/` from `replay.py` / runtime state (continue ADR-0008 slices).
- Keep `contracts/rif_familiar/` as device-facing seed until re-export decision.

**Acceptance criteria:**

- [ ] Deny-by-default, fallback, and conflict matrix covered by regression tests.
- [ ] Replay from `decisions.jsonl` rebuilds graph + posture identically (golden fixtures).
- [ ] `spec/governance/`, `spec/evidence/`, `spec/capability/` schemas validate fixtures under `fixtures/`.
- [ ] Docs (`API.md`, `ARCHITECTURE.md`) match `api.py` routes (fix known `/v1/posture/reset` drift).

**Test coverage requirements:**

- ≥ policy engine branch coverage for locked / exact / wildcard / network / package / MCP / default deny paths.
- Replay golden tests for allow+deny+posture escalation sequences.
- Schema tests for every seeded `spec/**/*.schema.json`.

---

### Milestone B — Control plane skeleton

**Goal:** Dedicated coordination seam per ADR-0008 (`control_plane/`: runtime, lifecycle, budget, coordinator, checkpoints, recovery).

**Depends on:** Milestone A; H1 (authenticated mutation).

**Work:**

- Introduce `control_plane/` package with thin facades wrapping existing `RIFRuntime`.
- Lifecycle state machine: Intent → Planning → Capability Resolution → Governance → … (as observable states, even if stubs).
- Checkpoint + recovery APIs backed by existing JSONL initially.
- Wire admin auth into control-plane mutation endpoints only.

**Acceptance criteria:**

- [ ] Control-plane mutations require admin auth.
- [ ] Lifecycle transitions are audited as decisions or dedicated events.
- [ ] Existing `/v1/policy/evaluate` remains stable (adapter or deprecate-with-alias).

**Test coverage requirements:**

- Auth matrix on control-plane routes.
- Lifecycle transition unit tests (illegal transitions denied).
- Recovery round-trip test (checkpoint → recover → summaries match).

---

### Milestone C — Evidence system

**Goal:** Evidence is a system (ledger/recorder/validators/provenance), not a single module; retrieval is non-authoritative.

**Depends on:** Milestone A (`spec/evidence/`).

**Work:**

- `EvidenceRecord` schema in `spec/evidence/` + Pydantic model.
- Append-only evidence ledger (JSONL first; Supabase mapping later per `DATA_MODEL.md`).
- Cited retrieval adapters (optional embeddings) marked read-only.
- LearningRecords store outcomes but never auto-mutate policy.

**Acceptance criteria:**

- [ ] Every policy decision can optionally attach evidence refs.
- [ ] Retrieval cannot override deny decisions in tests (property/invariant).
- [ ] Provenance hash/signature hooks reuse `security.py` helpers.

**Test coverage requirements:**

- Schema + ledger append/read tests.
- Invariant: retrieval suggestions never change `PolicyEngine.evaluate` outcome.
- Redaction tests for secret-bearing evidence payloads.

---

### Milestone D — Capability packaging (skills / plugins)

**Goal:** Skills and plugins are first-class, versioned, testable units.

**Depends on:** Milestone A (`spec/capability/`, later `spec/skill/`); H2.

**Work:**

- Define `spec/skill/` package format (`SKILL.md` + `skill.yaml` + tests).
- `skills/` and `plugins/` directories with one reference skill (e.g. policy-check).
- Admission: load skill → validate manifest → policy gate before execution.
- MCP configs and agent defs travel inside plugins, not ad hoc.

**Acceptance criteria:**

- [ ] Invalid skill manifests fail admission with auditable deny.
- [ ] Reference skill runs only through policy evaluate path.
- [ ] Plugin bundle installs in dev without network egress beyond allowlist.

**Test coverage requirements:**

- Manifest validation table tests.
- Admission deny/allow integration tests.
- At least one end-to-end skill invocation test via API/CLI.

---

### Milestone E — Reflexive healing (L0–L3)

**Goal:** Observe → diagnose → propose → sandbox-test bounded repairs (`REFLEXIVE_EVOLUTION.md`).

**Depends on:** Milestones A–C; Phase 2 scanners in CI (Bandit/CodeQL SARIF adapters).

**Work:**

- Schemas: `FailureEvent`, `Diagnosis`, `RepairProposal`, `VerificationResult`.
- Adapters: SARIF + GitHub Actions workflow results.
- Sandbox execution contract + rollback; **no** L4+ autonomous merge.

**Acceptance criteria:**

- [ ] L0–L3 paths implemented; L4+ remain policy-denied.
- [ ] RepairProposal requires reversibility + verification fields.
- [ ] Sandbox failure does not mutate `main` policies or protected paths.

**Test coverage requirements:**

- Autonomy level deny tests for L4+.
- RepairProposal schema validation.
- Sandbox rollback test (apply in temp → verify → revert).

---

### Milestone F — Controlled evolution

**Goal:** Architecture/policy changes are reviewable promotions.

**Depends on:** Milestone E; H1 (human-approved mutation).

**Work:**

- `EvolutionProposal` with threat model, eval plan, rollback, approval metadata.
- Post-deploy observation window tracking.
- Human approval required for merge and policy mutation (integrate admin auth).

**Acceptance criteria:**

- [ ] EvolutionProposal without approvals cannot change policy store.
- [ ] Observation window recorded in evidence ledger.
- [ ] Docs state non-goals: no autonomous protected-branch merges.

**Test coverage requirements:**

- Approval gate unit tests.
- Rejection path leaves policies unchanged (filesystem assertion).

---

### Milestone G — Reference Space (demo)

**Goal:** Hugging Face Gradio Space demonstrating governance thesis without production credentials.

**Depends on:** Milestones A–C at minimum; E for Diagnosis/RepairProposal UI if shown.

**Work:**

- Gradio UI: intent → decision → explainability → evidence.
- Read-only demo policies; no privileged write tools; no real secrets.
- Treat as demo boundary, not control plane.

**Acceptance criteria:**

- [ ] Space runs with fixture data only.
- [ ] Demo cannot mint Metasploit tokens or mutate hosted policy without local admin (prefer disabled).
- [ ] README documents demo limits.

**Test coverage requirements:**

- UI/callback unit tests where practical; smoke script against demo config.
- Security regression: demo config has no production keys.

---

## Suggested PR slicing (execution order)

| PR | Title | Phase |
| --- | --- | --- |
| 1 | `fix(security): authenticate mutable API routes` | H1 |
| 2 | `fix(policy): deny-by-default with wildcard precedence` | H2 |
| 3 | `fix(security): metasploit token allowlist + broker key fail-closed` | M1, M2 |
| 4 | `fix(api): implement recovered_summary` | L1 |
| 5 | `chore(deps): pin dependencies + pip-audit CI` | M3 |
| 6 | `chore(tooling): ruff/mypy/pytest config + pre-commit` | 2.1–2.5 |
| 7 | `ci: unify Python versions, format gate, action majors` | 2.6 |
| 8 | `docs(governance): branch protection + PR checklist sync` | 2.7 |
| 9+ | Architecture milestones A→G as separate PRs | Phase 3 |

Keep each PR focused; security PRs must not bundle ADR-0008 directory moves.

---

## Out of scope for this plan

- Autonomous L6 merges or model-driven policy mutation.
- Replacing JSONL with Supabase in the same PRs as H1/H2 (track under data-model follow-ups / ADR-0007).
- Choosing Black over Ruff format without an explicit decision in the tooling PR.

---

## Tracking

Update this file’s checkboxes as PRs merge. Keep [ROADMAP.md](ROADMAP.md) status table in sync when a milestone completes. Security regressions belonging to H1/H2 should open private advisories per [SECURITY.md](../SECURITY.md) if found in released tags.
