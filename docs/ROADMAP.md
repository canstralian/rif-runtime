# RIF Runtime Roadmap

## North star

RIF Runtime is a governed execution substrate for agents and tools. Natural-language intent becomes a visible, policy-evaluated command object before any capability is invoked. Every decision should be explainable through evidence, posture, policy precedence, and execution outcome.

RIF is not an autonomous agent framework; it is a governance and execution substrate for agents.

## Status

| Area | Status |
| --- | --- |
| Security hardening (Critical/High) | **Next** — see [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) Phase 0 |
| Tooling / CI / governance | Planned — Phase 2 |
| Policy Engine | In Progress |
| Explainability | In Progress |
| Evidence Layer | Planned |
| Reflexive Healing | Planned |
| Controlled Evolution | Planned |
| HF Space | Planned |

## Execution plan

The prioritized, acceptance-tested sequence (security → tooling → architecture) lives in
**[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)**. That document is the working backlog;
milestones below remain the product north star and map to Phase 3 (A–G) there.

## Current foundation

- governance runtime and reflexive loop;
- persistence primitives and durable decision history;
- MCP interception boundary;
- policy, posture, graph, telemetry, and audit surfaces;
- explainability regression tests;
- CI, release, secret scanning, dependency review, code-quality, and security-scanning workflows;
- development environment + agent instructions (see PR #37 / `AGENTS.md` when merged).

## Milestone 1 — Deterministic governance core

**Goal:** make every runtime decision reconstructable.

**Depends on:** Implementation Plan Phase 0 H2 (true deny-by-default) and Phase 2 CI.

- Stabilize the causal-path/explainability contract.
- Define policy precedence and frozen environment snapshots.
- Settle capability-snapshot authority — what external capability observation a
  decision is authorized against, and what governs its replacement. Held at
  specification review: `docs/spec-review-capability-snapshot-authority.md`.
- Normalize audit, posture, and decision records.
- Add regression coverage for deny-by-default, fallback, and policy-conflict behavior.

## Milestone 2 — Evidence and retrieval

**Goal:** attach relevant history and policy context without making retrieval authoritative.

- Introduce an EvidenceRecord schema.
- Add pluggable embedding and reranking adapters.
- Build cited retrieval with source metadata.
- Keep retrieval read-only in the initial runtime.

## Milestone 3 — Reflexive healing

**Goal:** diagnose and test bounded repairs.

- Define `FailureEvent`, `Diagnosis`, `RepairProposal`, and `VerificationResult` schemas.
- Add scanner/SARIF and GitHub Actions adapters.
- Add sandbox execution contracts and rollback semantics.
- Implement L0-L3 autonomy only: observe, diagnose, propose, sandbox-test.

## Milestone 4 — Controlled evolution

**Goal:** make architecture and policy changes reviewable promotions, not silent drift.

- Define `EvolutionProposal` and promotion criteria.
- Require threat model, evaluation, rollback plan, and approval metadata.
- Track post-deployment observation windows.
- Keep merge and policy mutation human-approved.

## Milestone 5 — Reference Space

**Goal:** publish a reproducible demonstration of RIF's governance thesis.

- Deploy a Hugging Face Space with a Gradio interface.
- Demonstrate intent evaluation, explainability, Diagnosis, RepairProposal, and EvidenceRecord visualization.
- Run without production credentials or privileged write tools.
- Treat the Space as a demo boundary, not a production control plane.

## Non-goals for the MVP

- autonomous protected-branch merges;
- automatic policy changes based on model output;
- unrestricted shell, GitHub, or MCP execution;
- credential storage in public demo infrastructure;
- treating model confidence as approval.
