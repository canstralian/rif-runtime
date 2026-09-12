# PROJECT_STATE.md

Reconciled state as of 2026-09-12 from repository and GitHub workflow evidence.

## Merge decision — PRs #179 and #180

- **Decision:** hold both pending focused corrections.
- **Preferred merge order after fixes and passing required checks:** `#179` then `#180`.
- **No direct file dependency** between the two PRs.
- **No merge performed** in this state snapshot.

## Verified status

- `[VERIFIED]` Both PRs have `Merge Gate` failures tied to `LOCK_SYNC` in their latest failed runs.
- `[VERIFIED]` The failing `lock is in sync with pyproject` jobs show only lockfile command-header drift (`pip-compile ... --no-index` appearing in regenerated headers) in `requirements/runtime.txt` and `requirements/dev.txt`.
- `[VERIFIED]` Gate summaries for those runs show required checks `VERIFY`, `CLEAN_CLONE`, and `DEP_SECURITY` as passing, with only `LOCK_SYNC` failing.
- `[VERIFIED]` `typecheck-tests` remains advisory in Merge Gate and is not part of the required verdict loop.

## Required PR corrections

### PR #179

- Refresh CI evidence against current runs before merge.
- Keep causal attribution separated:
  - `[VERIFIED]` status-context failures seen in checks.
  - `[UNVERIFIED]` external account-cause explanations unless independently confirmed.

### PR #180

- Correct ADR references to include both `docs/adr/` and legacy `docs/adr-*.md`.
- Align validation requirements with the actual Merge Gate commands and required checks.
- Correct or qualify quality-gate delegation wording so it does not overstate what delegated tooling guarantees.

## Separate gate repair (implemented in this branch)

- Canonicalized lockfile command headers via `CUSTOM_COMPILE_COMMAND="make lock"` in:
  - `Makefile` lock targets
  - `.github/workflows/merge-gate.yml` lock-sync recompilation step
- This addresses header drift without weakening the lock-sync gate.

## Vercel applicability and remediation

- Vercel status failures must be evaluated independently from Merge Gate required-check status.
- Use this owner runbook to remediate Vercel failures:

1. In Vercel dashboard, confirm the linked GitHub project/repository mapping and that deployments are enabled for the target branch.
2. Resolve account-level restrictions first (billing/verification/suspension) if dashboard shows account blocked.
3. Confirm runtime environment variables in Vercel match repository expectations:
   - `RIF_DATA_DIR=/tmp/rif-data`
   - `RIF_ENVIRONMENT=RIF_Runtime` (or another name that exists in `config/environments.yaml`)
   - `RIF_CONTROL_PLANE_API_KEYS` configured in Vercel secrets for guarded operations
4. Confirm `vercel.json` includes `config/**` and `rif.toml` so runtime profile files are present at build/runtime.
5. Redeploy the latest commit, then inspect deployment logs for import/startup errors from `api/index.py`.
6. Verify `/health` response and one guarded control-plane path with valid `X-API-Key`.
7. Treat Vercel checks as deployment-surface evidence only; do not substitute them for required Merge Gate checks.

## Follow-up

- Revalidate branch `#173` separately before any stabilization claims are advanced.
- Refresh this file again when stabilization actually lands on `main`.
