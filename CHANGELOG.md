# Changelog

This changelog records user- and contributor-relevant changes. It does not replace the detailed release notes under `docs/releases/`.

## Unreleased

### Fixed

- **A missing `environments.yaml` no longer refuses to start.** Raising on an
  unknown environment name is right when the file exists and omits it; it was
  wrong when there is no file at all, because the fallback config invented its
  own `production` name and the mismatch was an artefact. That crashed the
  Vercel cold start, which sets `RIF_ENVIRONMENT=RIF_Runtime` from a CWD
  without `config/`. The fallback now adopts the configured name and keeps the
  restrictive `limited` profile; an unknown name in a file that *does* exist
  still raises. `vercel.json` also ships `config/` so the deployment uses the
  real profiles rather than the fallback.

- **`GET /v1/audit` reads the decision log once instead of five times.** It is
  unauthenticated unless `RIF_REQUIRE_READ_AUTH` is set, and re-read and
  re-hashed the whole log per call. Also a correctness fix: five separate reads
  of a log being appended to can disagree, so the "summary" described no single
  state of the file.
- **The MST harness reports blocked turns.** `score_session` counts a blocked
  turn's `null` as "not a regression", so a session the policy gated shut
  scored a *perfect* MST while verifying nothing. The result now carries
  `turns_blocked` and `score_is_meaningful`, and the CLI warns and exits
  non-zero rather than printing `mst_score=4`.
- **`docker-compose.prod.yml` no longer defaults the Metasploit signing key.**
  `${RIF_MSF_BROKER_KEY:-}` passes an empty string, which the governor treats
  as absent and replaces with a fresh random key per process — so with
  `restart: always` every restart silently invalidated every outstanding
  capability token, while the comment claimed the opposite.

- **Concurrent writers no longer fork the decision chain.** The tail hash was
  cached for a store object's lifetime, so a `rif check` run against a live
  `rif serve` — both building a `RIFRuntime` over the same `RIF_DATA_DIR` —
  produced a forked chain, and `/v1/audit` then reported `verified: false`
  permanently, indistinguishable from tampering. Appends now take an exclusive
  `flock` and re-read the tail from the end of the file inside it. Covered by a
  test running three real processes; verified that it fails without the lock.

- **The container could not write its own state.** Every layer before
  `USER appuser` runs as root, so `COPY . .` left `/app/data` root-owned while
  the process ran unprivileged: the container reported healthy and then failed
  on the first decision append with `PermissionError`. `/app/data` is now
  chowned to the runtime user. The Image workflow's smoke test previously only
  read `/health`, which cannot catch this — it now evaluates a policy request
  and asserts the decision reached `decisions.jsonl` on disk.
- **`.dockerignore` excludes local runtime state.** `COPY` reads the build
  context rather than git, so a developer's `data/*.jsonl` was baked into the
  image despite being git-ignored. `data/policies.json` still ships: it is the
  seeded default policy.

- **Server, environment and root-path settings are now honoured.** Seven of the
  eleven `RIF_*` settings were parsed, validated and then read by nothing.
  `RIF_SERVER_HOST` / `RIF_SERVER_PORT` were the worst of it: `.env.example`
  presented them as the way to choose a bind address while `rif serve`
  hardcoded its own. `rif serve` now takes its defaults from configuration
  (explicit flags still win), `RIF_SERVER_ROOT_PATH` reaches the ASGI app, and
  `RIF_ENVIRONMENT` selects the active profile — with an unknown name raising
  rather than silently falling back, since the environment carries the egress
  constraints.
- **The default bind address is loopback.** `[server] host` defaulted to
  `0.0.0.0`, which was harmless only because nothing read it. Wiring it up
  unchanged would have turned every `rif serve` into a network listener, so the
  default and the shipped `rif.toml` are now `127.0.0.1`; the container image
  passes `--host=0.0.0.0` explicitly.
- **The shipped `rif.toml` named an environment that does not exist**
  (`production`, absent from `environments.yaml`). Now `RIF_Runtime`.
- **The `.env.example` fidelity guard no longer passes vacuously.** It grepped
  `src/` for each variable name, which `config.py`'s own `_ENV_MAP` satisfies
  for every name, so it proved nothing. Replaced with per-setting behavioural
  tests plus a completeness check, so a setting that stops being honoured fails
  regardless of how the lookup is written. Settings that are deliberately
  recorded-but-not-enforced are declared explicitly and must say so in
  `.env.example`.

- **`POST /v1/runs` is allowed by the shipped policy.** Enabling catch-all
  evaluation made `deny_unknown_by_default` apply to `run.create`, so every
  authenticated run creation returned 403. Deny-by-default means denying what
  is *not enumerated*, so the runtime's own first-party actions are now
  enumerated: `data/policies.json` and `DEFAULT_POLICIES` ship an
  `allow_run_create` rule, and a test pins the full first-party action
  inventory so the next one cannot be swept up silently.

- **Breaking (governance): wildcard policy rules are now evaluated.**
  `PolicyEngine.evaluate()` previously skipped every rule with
  `action: "*"` or `target: "*"`, which meant the shipped
  `deny_unknown_by_default` rule was loaded, returned by `GET /v1/policies`,
  and never applied — an unconfigured action fell through to `default.allow`.
  Wildcard rules now apply, so the default policy denies by default as it has
  always claimed to. Rules are evaluated most-specific-first, and catch-all
  (`"*"`/`"*"`) rules run after the environment constraints so a broad `allow`
  cannot disable the `allowed_hosts` allowlist. Actions that relied on the old
  fallthrough must now be permitted by an explicit rule; the MST eval harness
  is one such consumer and now declares an `allow` rule for `code.refine`.
  See "Policy evaluation order" in `docs/API.md`.


- **Resolved the zero-coverage modules.** `graph/relationships.py` had no
  caller, contract, documentation or test and was removed. The rest turned out
  to be seams rather than accidents and are now covered instead:
  `agents/manifest.py` binds `.rif/agents/manifest.schema.yaml` (a test now
  fails if the dataclass and schema drift), `agents/deputy.py` and
  `agents/orchestrator.py` are the worked examples `agents/template.py`
  documents, and `execution/state.py` is seeded material for the Track B work
  held by `docs/spec-review-identity-spine-migration.md` — its overlap with
  `runs.schemas.RunStatus` is now pinned by a test so a silent reconciliation
  is noticed. Coverage rose from 89% to 95%.

- **Removed `tem]`**, a tracked 6.9 KB file of ANSI-escaped terminal output
  rendering an obsolete `pyproject.toml` (version `0.2.0`), committed by a
  shell redirect typo. Also removed a function-local `PolicyRequest` import in
  `api.py` that shadowed the module-level one.

- **Startup configuration validation moved to a lifespan handler.** Beyond
  clearing the `on_event` deprecation, the old hook gave the failure path no
  usable semantics: a `SystemExit` raised inside it was swallowed by anyio's
  task group and reached callers as `CancelledError`, so invalid configuration
  was indistinguishable from a cancelled startup. `ConfigError` now propagates.
  `startup.py` went from 53% coverage with an untested failure branch to full
  cover, and an AST-based test fails if `on_event` is reintroduced.

- **The OpenAPI document reports the real package version.** `api.py`
  hardcoded `version="0.3.0"` while the package was `0.3.0rc2`, so
  `/openapi.json` advertised a release the installed distribution was not. It
  now uses `__version__`, and a test fails if a literal is reintroduced.

- **`rif serve` no longer forces auto-reload.** Reload was hardcoded on, so the
  start command documented in the README quick start spawned uvicorn's
  file-watching supervisor even when serving for real. It is now `--reload`,
  off by default.
- **The production image installs the hash-pinned lock.** `Dockerfile` built
  from the deliberately unpinned `requirements.txt`, so the locked-toolchain
  discipline stopped at the image. It now installs
  `requirements/runtime.txt` with `--require-hashes` (which carries every
  `uvicorn[standard]` extra), adds a `HEALTHCHECK` against `/health`, and runs
  the installed `rif_runtime.api:app` rather than the `src.`-prefixed path that
  only resolved via implicit namespace packages.
- **Fixed the production compose healthcheck**, which invoked `curl` in a
  `python:slim` image that has no curl and could therefore only fail. Its
  environment block also set four variables nothing reads, including
  `RIF_SECURITY_SANDBOX_MODE: "strict"`.

- **The decision log is now hash-chained.** `audit.py` implemented the chain
  primitives from the start, but nothing in `src/` used them, so
  `decisions.jsonl` was append-only rather than tamper-evident. Decisions are
  now written through `HashChainedJsonlStore`; edits, deletions, reorderings and
  hand-spliced rows are detected. `GET /v1/audit` reports the result under
  `decision_chain`. Rows written before this change are reported as
  `unchained_leading`, never counted as verified. `SECURITY.md` documents what
  the property does and does not cover — notably that truncation can be
  rewritten into a shorter valid chain.

- **`.env.example` no longer documents configuration that does not exist.**
  It listed 58 variables, of which the runtime read 3. The 55 inert names
  included `RIF_SECURITY_SANDBOX_ENABLED`, `RIF_SECURITY_NETWORK_ISOLATION`,
  `RIF_SECURITY_CAPABILITY_DROP`, `RIF_AUTH_ENABLED` and `RIF_AUDIT_ENABLED` —
  settings that read as security controls while doing nothing — and it omitted
  the real `RIF_DATA_DIR`. The file now documents exactly what the code reads,
  and a test fails on any name nothing in `src/` references.

- **Security: governance-state read endpoints can now require authentication.**
  `/v1/audit`, `/v1/policies` (GET), `/v1/recovered-state`,
  `/v1/persistence/summary`, `/v1/telemetry/summary` and `/v1/graph/summary`
  return decision history and configured rules and were unauthenticated with no
  way to change that. Setting `RIF_REQUIRE_READ_AUTH=true` now guards them with
  the existing `X-API-Key` check. The flag defaults to off so existing read
  clients keep working; it is intended to become the default. `docs/API.md` also
  no longer claims `GET /v1/policies` is a guarded mutable operation.
- **A route-inventory test now fails CI on any new unguarded endpoint**, so the
  public surface has to be declared rather than defaulted into.

- **Governance: the configured posture now reaches the runtime.**
  `RIF_POSTURE` / `[runtime] posture` was parsed, validated, and never read, so
  a runtime configured `locked` started up allowing everything. It is now
  applied as a floor on the restored posture: configuration can tighten a
  runtime but never relax one. `POST /v1/posture/reset` still relaxes the
  running process, but the floor is re-applied on restart. Defaults are
  unchanged (`normal` is a no-op floor). `config.PostureLevel` is now
  `schemas.Posture` rather than a second identical enum.

### CI

- **Consolidated four overlapping workflows into a clear division of labour.**
  `ci.yml`, `quality.yml` and `lint.yml` all re-ran ruff/mypy/pytest at
  inconsistent Python versions (3.12 vs 3.13 vs a matrix), inconsistent lint
  scopes (`src tests` vs `.`) and inconsistent action versions
  (`setup-python@v4` and `codecov-action@v3` alongside `@v5`/`@v6`). All three
  are removed: `merge-gate.yml`'s `verify` matrix already ran exactly that work
  on both interpreters, and remains the single required check.
  - New `Coverage` workflow: the one thing the gate did not measure. Threshold
    raised from the old 80% to 90% (currently 95%).
  - New `Image` workflow: builds the container, **starts it and polls
    `/health`**, and asserts the image declares a `HEALTHCHECK`. Nothing
    previously executed the image, so a broken Dockerfile was invisible to
    every Python job.

  **Operator action required:** if branch protection still requires checks from
  the removed workflows, they will never report again and `main` cannot be
  merged. Require `gate` instead — see `docs/BRANCH_CLEANUP.md`.

### Documentation and governance

- Reworked the project overview to distinguish implemented behaviour from specification and planned work.
- Added a documentation source-of-truth hierarchy and evidence-language standard.
- Reconciled architecture, API, CLI, development, deployment, testing, release, dependency, security, and contributor documentation with the current repository.
- Replaced the placeholder security reporting contact with a private mailto reporting link.
- Added contributor support guidance and stronger issue/PR templates.
- Removed stale NotebookLM documentation snapshots and generated documentation bundles to reduce documentation drift.
- Removed orphaned duplicate ADR files.

### Security documentation

- Explicitly separated cryptographic primitives from claims about persisted evidence integrity.
- Documented current control-plane API-key authentication and its limitations.
- Documented dependency-lock and CI security controls without implying that workflow configuration proves successful execution.
- Documented remaining supply-chain gaps: SBOM, signed artefacts/provenance, and reproducible builds.

### Architecture

- Clarified that remote provider authorization remains specification work and that provider credentials are not RIF authority.
- Clarified the boundary between replay/reconstruction and proof of external side effects.

## Release history

See [`docs/releases/`](docs/releases/) for historical release notes.
