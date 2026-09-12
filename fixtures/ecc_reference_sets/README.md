# ECC Reference-Set Seed Artifacts

These fixtures are evidence inputs for repository quality automation and reviewer tooling.
They are not runtime feature claims and are not loaded by `rif_runtime` at execution time.

## Contents

- `deep_analyzer_corpus.jsonl` - canonical and drifted lock-header analyzer cases.
- `rag_evaluator_comparison.json` - retrieval/evaluator ranking expectations.
- `pr_salvage_review_corpus.json` - stale/reopen/review-thread salvage examples.
- `discussion_triage_corpus.json` - informational/answered/no-response triage cases.
- `harness_compatibility_audit.json` - cross-harness compatibility expectations.

## Maintenance

- Keep examples deterministic and minimal.
- Add new cases when regressions are found in review automation.
