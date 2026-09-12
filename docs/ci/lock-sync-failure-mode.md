# LOCK_SYNC Failure Mode Evidence

This document captures a verified lock-sync failure mode for troubleshooting and regression checks.

## Source run

- Workflow: `Merge Gate`
- Run ID: `33774728390`
- Run URL: `https://github.com/canstralian/mandare/actions/runs/33774728390`
- Failed jobs:
  - `100722750255` (`lock is in sync with pyproject`)
  - `100723040953` (`gate`)

## Verified failure signature

- `pip-compile` regenerated lock headers with explicit `--no-index` command text.
- `git diff --exit-code -- requirements/` failed on header lines only.
- Gate summary marked `LOCK_SYNC=failure`, while `VERIFY`, `CLEAN_CLONE`, and `DEP_SECURITY` were `success`.

### Diff excerpt captured from job logs

```diff
-#    pip-compile --allow-unsafe --extra=dev --generate-hashes --output-file=requirements/dev.txt --strip-extras pyproject.toml
+#    pip-compile --allow-unsafe --extra=dev --generate-hashes --no-index --output-file=requirements/dev.txt --strip-extras pyproject.toml

-#    pip-compile --allow-unsafe --generate-hashes --output-file=requirements/runtime.txt --strip-extras pyproject.toml
+#    pip-compile --allow-unsafe --generate-hashes --no-index --output-file=requirements/runtime.txt --strip-extras pyproject.toml
```

## Remediation pattern used in this repository

Canonicalize lock generation headers with:

```bash
CUSTOM_COMPILE_COMMAND="make lock" pip-compile ...
```

Apply the same canonical command source in both:

- `Makefile` lock targets
- `.github/workflows/merge-gate.yml` lock-sync regeneration step
