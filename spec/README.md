# spec/

Versioned contracts for AgentOS/RIF. Everything here defines a boundary that any
runtime (this Python implementation, or a future Rust/Go/.NET one) must conform to.
The runtime under `src/rif_runtime/` implements these contracts; it does not define
them — schema and contract changes land here first, then flow into the
implementation.

Per ADR-0008 (`docs/adr-0008-agentos-rif-v1-architecture.md`), the six contract
domains are:

| Domain | Status | Contents |
| --- | --- | --- |
| `capability/` | seeded | Capability manifest schema (copied from `contracts/rif_familiar/`) |
| `governance/` | seeded | Posture decision schema (copied from `contracts/rif_familiar/`) |
| `evidence/` | seeded | Observation event schema (copied from `contracts/rif_familiar/`) |
| `replay/` | placeholder | Replay contract not yet extracted from `src/rif_runtime/replay.py` |
| `skill/` | placeholder | Skill package format (`SKILL.md` + `skill.yaml` + tests) not yet formalized |
| `state/` | placeholder | Structured runtime state contract not yet extracted from `runtime_state.json` |

Beyond the six original domains, governed-integration contracts also live here:

| Domain | Status | Contents |
| --- | --- | --- |
| `mcp/` | drafted | MCP server framework governance contract (`SPEC.md`): authority tiers, ordered decision procedure, destructive-action hard gate, evaluation scorecard — generalizes `src/rif_runtime/mcp/metasploit.py` |

`contracts/rif_familiar/` is left in place unchanged for this slice — it is the
device-facing (RIF Familiar / Field Observer) contract set and is the origin of the
schemas seeded into `capability/`, `governance/`, and `evidence/` above. A later
slice should decide whether `contracts/rif_familiar/` re-exports from `spec/` or is
retired in favor of it; that decision is out of scope here.

> **Known gap — duplication, not migration.** ADR-0008 calls for these schemas to be
> *migrated rather than duplicated*. What is in the tree today is duplication: the
> three schemas are byte-identical between `contracts/rif_familiar/` and `spec/`, and
> `tests/test_rif_familiar_contracts.py` validates only the `contracts/` copies —
> so the `spec/` copies carry no test coverage and can drift silently. Until the
> re-export-vs-retire question above is settled, treat `contracts/rif_familiar/` as
> the tested copy. See `docs/SPECS_DOCS_AUDIT.md` (H3).

## Next slices
- Extract a `replay/` contract from `src/rif_runtime/replay.py`.
- Extract a `state/` contract. Note that no `runtime_state.json` exists in this
  repository — the name comes from ADR-0008's description of the shape to decompose,
  not from a file on disk. The concrete state the runtime tracks today lives in
  `data/decisions.jsonl` and `data/posture_history.jsonl`.
- Define the `skill/` package format contract (see `spec/skill/README.md` for the
  manifest filename question).
- Close the duplication gap noted above.
