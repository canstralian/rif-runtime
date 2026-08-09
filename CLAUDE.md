# CLAUDE.md

Guidance for AI assistants (Claude Code and others) working in this repository.

## What this is

RIF Runtime is a governed agent runtime: a policy engine that mediates actions
taken by AI agents (HTTP requests, MCP tool invocations, package installs) and
produces an auditable trail of allow/deny decisions. It is a small FastAPI
service plus a Typer CLI, backed by JSONL/JSON files for persistence — no
database, no external services.

Core execution circuit:

```
Agent request
  -> PolicyEngine.evaluate()                  (src/rif_runtime/policy.py)
  -> PolicyDecision
  -> GovernanceGraph.record_decision()        (src/rif_runtime/graph/memory.py)
  -> ReflexiveLoop.observe() -> new Posture   (src/rif_runtime/governance/reflexive.py)
  -> JsonlStore.append()                      (src/rif_runtime/storage/jsonl.py)
  -> Audit / telemetry / graph summary APIs
```

Trust model: deny by default, environment-scoped allowed hosts, and a
"posture" that escalates automatically as denials accumulate
(`normal -> elevated -> restricted -> locked`). A `locked` posture denies
everything regardless of other rules. Severe Metasploit-class denials
escalate posture immediately, bypassing the reflexive threshold.

Current version: **0.3.0rc1** (source of truth: `pyproject.toml`).

## Layout

```text
src/rif_runtime/
  api.py                   FastAPI app — all HTTP routes (source of truth for the API surface)
  cli.py                   Typer CLI: `rif serve`, `rif check`, `rif replay`
  runtime.py               RIFRuntime — wires config, policy engine, reflexive loop,
                            graph, metasploit governor, and persistence; one instance per process
  config.py                Loads rif.toml + RIF_* env vars into RifSettings (new primary config),
                            and environments.yaml into RuntimeConfig (legacy, used by RIFRuntime)
  policy.py                PolicyEngine — the actual allow/deny decision logic
  schemas.py               Pydantic models: PolicyRequest, PolicyDecision, Decision,
                            Posture, EnvironmentProfile, RuntimeConfig
  replay.py                ReplayEngine — rebuilds graph + posture from decisions.jsonl
                            (forensic recovery after restart)
  auth.py                  ControlPlaneAuth — X-API-Key guard for mutable endpoints;
                            key list loaded from RIF_CONTROL_PLANE_API_KEYS env var;
                            fails closed (503) when unconfigured
  audit.py                 AuditRecord + hash-linked chain helpers (append_record,
                            verify_chain); each record hashes over its predecessor
  explainability.py        DecisionExplanation — captures request, decision, rule
                            precedence, posture before/after, and environment snapshot
  security.py              Cryptographic utilities: Fernet encryption (PBKDF2 key
                            derivation), HMAC signing/verification, SHA-256 digests,
                            canonical JSON, secret redaction for audit logs
  startup.py               register_config_startup() — FastAPI on_event("startup")
                            hook that validates RifSettings and stores on app.state
  _version.py              Version resolution: importlib.metadata → pyproject.toml →
                            RuntimeWarning("unknown"); no hardcoded version string

  agents/
    orchestrator.py        OrchestratorAgent — example multi-step request agent
    auditor.py             AuditorAgent — aggregates audit summary from RIFRuntime
    deputy.py              DeputyAgent — example delegation-pattern agent
    template.py            TemplateAgent — copy-and-rename starting point for new
                            governed agents; implements request()/handle_decision()
    manifest.py            AgentManifest — frozen dataclass describing an agent's
                            responsibilities, I/O, dependencies, and quality gates

  capabilities/
    capability.py          Capability ABC — abstract base for all executable capabilities
    registry.py            CapabilityRegistry — explicit-registration, deterministic-
                            resolution registry of Capability instances
    echo.py                EchoCapability — trivial reference implementation

  execution/
    kernel.py              ExecutionKernel — governed execution entry point; resolves
                            capability from registry and calls capability.execute(manifest)
    manifest.py            ExecutionManifest — immutable policy→kernel contract:
                            actor, capability, action, target, parameters
    result.py              ExecutionResult + ExecutionStatus enum (pending/running/
                            succeeded/failed/denied)
    state.py               ExecutionState enum — lifecycle phases of a governed execution
    exceptions.py          ExecutionError hierarchy: PolicyViolationError,
                            CapabilityNotFoundError, AdapterExecutionError,
                            ExecutionTimeoutError, EvidenceGenerationError

  governance/
    posture.py             PostureManager (denial thresholds → Posture) +
                            escalate_posture() (one-rung step-up, capped at locked)
    reflexive.py           ReflexiveLoop — glues TelemetryStore + PostureManager
    telemetry.py           TelemetryStore — in-memory rolling window of decisions

  graph/
    memory.py              GovernanceGraph — networkx MultiDiGraph of actor→target edges
    relationships.py       Query helpers over the graph (actor_targets, denied_edges)

  configuration/
    policies.py            PolicyRule + PolicyStore — JSON-backed CRUD for declarative
                            policy rules, exposed via /v1/policies (NOTE: see Gotchas)
    store.py               JsonStore — generic atomic-write JSON file helper

  storage/
    jsonl.py               JsonlStore — append-only JSONL log with count()/count_by()

  mcp/
    capabilities.py        Metasploit capability taxonomy: CapabilityClass enum,
                            READ_ONLY_CAPABILITIES / CONSEQUENTIAL_CAPABILITIES /
                            SEVERE_CAPABILITIES frozensets, classify(), is_severe(),
                            contract_hash() (stable digest pinned into evidence events)
    metasploit.py          MetasploitGovernor (three governance lanes: read-only firewall,
                            shadow, lab-broker), MetasploitIntent, CapabilityToken,
                            GovernanceMode, GovernanceOutcome, EvidenceEvent,
                            scan_for_injection(), INJECTION_PATTERNS
    corpus.py              benchmark_corpus() (~60 canonical intents) + run_benchmark()
                            — zero-execution-path-leak and 100%-evidence-coverage tests

  resources/
    identity.py            ResourceId (kind/namespace/name) + ResourceKind enum
    descriptor.py          ResourceCapabilityDescriptor + ResourceEffect enum —
                            declarative governed capability against a resource kind
    registry.py            ResourceCapabilityRegistry — descriptor registry
    resource.py            ResourceReference — id + uri + optional version
    snapshot.py            ResourceSnapshot — immutable observation of resource state
    inventory.py           ModuleInfo + TestInfo — filesystem discovery value types
    scanner.py             RepositoryScanner — filesystem observer (no Git, no network)
    repository.py          RepositoryResource + RepositorySnapshot
    builder.py             RepositorySnapshotBuilder — builds snapshot from scanner output
    exceptions.py          DuplicateResourceCapabilityError, UnknownResourceCapabilityError

config/environments.yaml   Environment profiles: RIF_Runtime, RIF_Research, RIF_CI
rif.toml                   Primary runtime config (posture, server, provider, paths);
                            all keys overridable via RIF_* env vars (see Configuration)
data/                      Runtime state: decisions.jsonl, posture_history.jsonl,
                           metasploit_evidence.jsonl (all gitignored); policies.json
                           (checked in, seeds PolicyStore)
docs/                      ARCHITECTURE.md, API.md, RIF_RUNTIME_MVP.md, ROADMAP.md
tests/                     pytest suite; mirrors src/ modules being exercised
scripts/smoke.sh           Curl-based smoke test against a running `rif serve`
```

## Development workflow

Setup:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
pip install -r requirements-dev.txt
```

Run the API:

```bash
rif serve              # uvicorn with --reload, http://127.0.0.1:8000
```

CLI usage:

```bash
rif check <actor> <action> <target>     # evaluate one request, print the decision
rif replay [decisions_path]             # rebuild graph/posture from a decisions.jsonl
```

Test, lint, type-check (this is exactly what `.github/workflows/ci.yml` runs, in order):

```bash
ruff check src tests
mypy src/rif_runtime --ignore-missing-imports
pytest -q
```

The `quality.yml` workflow additionally enforces `ruff format --check .` (Python 3.13,
pinned `ruff==0.15.22`). Run `ruff format .` before committing so formatting doesn't
break the quality gate even if the CI gate passes.

```bash
ruff format .
ruff check src tests
mypy src/rif_runtime --ignore-missing-imports
pytest -q
```

Manual smoke test against a running server:

```bash
rif serve &
BASE=http://127.0.0.1:8000 ./scripts/smoke.sh
```

## Configuration

`rif.toml` (project root) is the primary runtime config file. Every key can be
overridden by a `RIF_*` environment variable (env vars take precedence):

| TOML key                   | Env var                  | Default      |
|----------------------------|--------------------------|--------------|
| `[runtime] posture`        | `RIF_POSTURE`            | `normal`     |
| `[runtime] environment`    | `RIF_ENVIRONMENT`        | `production` |
| `[runtime] cloud_egress`   | `RIF_CLOUD_EGRESS`       | `false`      |
| `[server] host`            | `RIF_SERVER_HOST`        | `0.0.0.0`   |
| `[server] port`            | `RIF_SERVER_PORT`        | `8000`       |
| `[server] root_path`       | `RIF_SERVER_ROOT_PATH`   | `""`         |
| `[provider] mode`          | `RIF_PROVIDER_MODE`      | `local`      |
| `[provider] model`         | `RIF_PROVIDER_MODEL`     | `default`    |
| `[provider] endpoint`      | `RIF_PROVIDER_ENDPOINT`  | `""`         |
| `[paths] data_dir`         | `RIF_DATA_DIR`           | `data`       |
| `[paths] config_dir`       | `RIF_CONFIG_DIR`         | `config`     |

Unknown TOML keys are rejected at startup (`extra="forbid"`); typos surface as a
`ConfigError` that causes `SystemExit(1)` before the server accepts traffic.

`config/environments.yaml` is a separate legacy config loaded by `RIFRuntime` for
the environment profiles (networking rules, allowed hosts). It is still the source
of truth for per-environment policy constraints.

## Authentication

Mutable control-plane endpoints require an `X-API-Key` header. The allowed key list
is loaded from the `RIF_CONTROL_PLANE_API_KEYS` environment variable
(comma-separated values). The guard:

- **fails closed**: if `RIF_CONTROL_PLANE_API_KEYS` is unset or empty, every guarded
  request returns `503 Service Unavailable` rather than silently passing.
- uses `hmac.compare_digest` over SHA-256 digests of equal length to prevent
  timing attacks and length-mismatch errors.

Guarded endpoints: `POST /v1/environment/{name}`, `POST /v1/policy/evaluate`,
`POST /v1/posture/reset`, `POST /v1/posture/{posture}`,
`POST /v1/mcp/metasploit/token`, `PUT /v1/policies/{rule_id}`,
`DELETE /v1/policies/{rule_id}`.

Simulation routes (`POST /v1/mcp/invoke`, `POST /v1/mcp/metasploit/evaluate`) are
intentionally unauthenticated dry-run paths that cannot mutate posture or write
to the JSONL stores (`record=False`).

## Metasploit governance

`MetasploitGovernor` enforces three containment lanes for Metasploit MCP tool calls:

| Lane | `GovernanceMode` | Consequential capability |
|------|------------------|--------------------------|
| Read-only firewall | `read_only_firewall` | Denied outright |
| Shadow harness | `shadow` | Denied and recorded as simulated |
| Lab broker | `lab_broker` | Allowed only with a valid `CapabilityToken` |

All three lanes share one ordered decision procedure:
1. `posture.locked` → deny everything.
2. Prompt-injection / NL-authority scan (`INJECTION_PATTERNS`) → quarantine with
   `severe=True` on match; the presence of an authority assertion is never authority.
3. Read-only capability → allow (security knowledge, not execution authority).
4. Consequential capability → lane-specific decision (see table above).

`CapabilityToken` is a short-lived, target-pinned, HMAC-signed execution grant
minted by `POST /v1/mcp/metasploit/token` after explicit human approval. The token
binds one capability to one target and to a specific `intent_hash`; any mismatch
(capability, target, intent, expiry, or signature) results in a denial.

Every recorded governance decision produces a signed `EvidenceEvent` that is appended to
`data/metasploit_evidence.jsonl`. Dry-run evaluations (`/v1/mcp/invoke`,
`/v1/mcp/metasploit/evaluate`) use `record=False` and do not write this log. The `contract_hash()` embedded in each event is a
stable SHA-256 digest of the capability taxonomy, allowing decisions to be
replayed against the exact contract that produced them.

## Execution subsystem

The `execution/` module formalises the boundary between policy evaluation and
capability execution:

```text
PolicyEngine.evaluate() -> PolicyDecision (allow)
  -> ExecutionManifest  (actor, capability, action, target, parameters)
  -> ExecutionKernel.execute(manifest)
    -> CapabilityRegistry.resolve(manifest.capability)
    -> Capability.execute(manifest)
  -> ExecutionResult    (status, output, metadata, timestamps)
```

`ExecutionKernel` contains no capability-specific logic; it only routes manifests
to the correct `Capability` implementation. `Capability` is an ABC — add new
side-effecting operations by subclassing it and registering with
`CapabilityRegistry`. `EchoCapability` is the reference implementation.

`ExecutionState` models lifecycle phases (`created → policy_approved → routing →
executing → recording_evidence → completed/failed/denied`) independently of
`ExecutionStatus` (which records the final outcome).

## Resources subsystem

`resources/` provides provider-agnostic contracts for addressable runtime assets:

- `ResourceId` — stable identity: `kind:namespace/name` string form.
- `ResourceReference` — identity + URI + optional version.
- `ResourceSnapshot` — immutable timestamped observation of resource state.
- `ResourceCapabilityDescriptor` — declarative description of a governed operation
  (effect: read/write/snapshot/inventory/project/render, replayable flag).
- `ResourceCapabilityRegistry` — registry of descriptors; policy evaluates
  descriptors, providers execute approved operations.
- `RepositoryScanner` — filesystem-only observer of a local repo: discovers Python
  modules and test files, no Git operations or network calls.
- `RepositorySnapshotBuilder` — assembles a `RepositorySnapshot` from scanner output.

## Security utilities (`security.py`)

`security.py` is the canonical cryptographic toolkit — do not hand-roll crypto elsewhere:

- **Fernet encryption**: `encrypt_text` / `decrypt_text` — PBKDF2-HMAC-SHA256 key
  derivation (600,000 iterations by default; `RIF_PBKDF2_ITERATIONS` env var overrides).
- **HMAC signing**: `hmac_signature` / `verify_hmac_signature` — over canonical JSON.
- **SHA-256 digest**: `sha256_digest` — over canonical JSON (used in audit chain).
- **Canonical JSON**: `canonical_json` / `normalize_for_json` — deterministic
  serialisation of nested dicts, lists, datetimes, UUIDs, and bytes.
- **Secret redaction**: `redact_secrets` / `should_redact_key` — strips sensitive
  fields (`api_key`, `token`, `password`, etc.) from dicts before logging; safe
  suffixes (`_hash`, `_digest`, `_id`) are exempted.

## Audit chain (`audit.py`)

`AuditRecord` is a frozen dataclass forming a hash-linked list:
- `previous_hash` chains to the prior record (genesis is `"0" * 64`).
- `current_hash` is a SHA-256 digest of `(event_id, timestamp, payload, previous_hash)`.
- `verify_chain(chain)` validates every link; any tampering breaks the chain.

## Conventions

- Python 3.12+, Pydantic v2 models (`model_dump`, `model_validate`, `model_copy`)
  for everything that crosses an API boundary or gets persisted.
- The codebase is formatted with `ruff format .`; run it before committing.
  Double quotes, spaced operators/keyword args, and trailing commas on multi-line
  calls are the enforced style.
- New persisted state goes through `JsonlStore` (append-only logs: decisions,
  posture history, Metasploit evidence) or `JsonStore` (whole-file JSON with
  atomic temp-file replace: policies). Don't hand-roll file I/O elsewhere.
- `RIFRuntime` is constructed fresh per process/test (`RIFRuntime()`), not a
  singleton with DI. Tests that touch persistent storage use isolated temporary
  paths, following the `tmp_path` pattern (see `tests/test_policy_store.py`).
- Enums (`Decision`, `Posture`, `ExecutionStatus`, …) subclass `enum.StrEnum` so they
  serialize cleanly and compare equal to plain strings.
- `from __future__ import annotations` is present in all new modules; use it in
  any file you create or substantially edit.
- Environment profiles are config-driven (`config/environments.yaml`), not
  hardcoded; add new environments there rather than branching in code.
- Agents follow the pattern in `agents/template.py`: construct `PolicyRequest`,
  consume `PolicyDecision`, never talk to targets directly or bypass the policy engine.
- New capabilities subclass `Capability` (ABC) and register with `CapabilityRegistry`.
  Never add capability-specific logic to `ExecutionKernel`.

## Gotchas / known inconsistencies

- **PolicyStore rule matching is exact-match only.** `RIFRuntime` owns a
  shared `PolicyStore` (`self.policy_store`) and passes its rules into
  `PolicyEngine.evaluate()`. Only fully-specific rules (non-`"*"` `action`
  and `target`) are consulted as overrides. Wildcard rules (like the seeded
  `deny_unknown_by_default`) are intentionally skipped — they're inert
  placeholders until rule precedence for partial wildcards is designed. See
  `policy.py:rule_matches`.
- **Docs lag the code.** `docs/API.md` lists `POST /v1/runtime/reset-posture`,
  but the actual route in `api.py` is `POST /v1/posture/reset`. Treat
  `src/rif_runtime/api.py` as the source of truth for the API surface, and
  update the docs when you change routes.
- **`posture/reset` must be registered before `posture/{posture}`.** The comment
  in `api.py` explains why: without this ordering FastAPI captures `"reset"` as
  a `Posture` path parameter and returns 422.
- **Version bump checklist.** `__version__` resolves via `importlib.metadata`
  (installed package) → `pyproject.toml` (editable checkout) → `RuntimeWarning`.
  Only `pyproject.toml` needs the version bump. Use `scripts/bump-version.sh X.Y.Z`,
  then `pip install -e .` to refresh metadata. `tests/test_version.py` catches drift.
- **Test isolation.** Tests that instantiate `RIFRuntime()` write real records into
  `data/decisions.jsonl`, `data/posture_history.jsonl`, and potentially
  `data/metasploit_evidence.jsonl` as a side effect. `tests/test_policy_store.py`
  uses `tmp_path` correctly — follow that pattern for new tests that touch
  persistent storage.
- **`data/policies.json` is checked in; `data/*.jsonl` files are gitignored.**
  Don't flip that. `data/policies.json` is the seed/default state for `PolicyStore`.
- **MetasploitGovernor signing key.** `RIF_MSF_BROKER_KEY` env var sets the HMAC
  signing key. If unset, the governor generates a random key per process — tokens
  minted in one process cannot be verified in another. Set the env var in production
  and in any test that round-trips a token across a simulated restart.
- **`quality.yml` uses a pinned ruff (`ruff==0.15.22`).** Unpinned installs pull
  a newer version that re-sorts imports and enables new lints, turning main red
  with no code change. Match this version locally when debugging quality failures.
- **ConfigError causes SystemExit(1) at startup.** If `rif.toml` contains unknown
  keys or invalid values, the FastAPI startup hook raises `SystemExit(1)` before
  the server accepts traffic. This is intentional: a misconfigured runtime should
  not silently start.
- **`record_decision()` is not protected by `_lock`.** `RIFRuntime._lock`
  (`threading.Lock`) is held only inside `evaluate_metasploit()`. The
  `evaluate()` → `record_decision()` path — which mutates `governance_graph`,
  `posture`, and `decisions_store` — runs without the lock, so concurrent
  `POST /v1/policy/evaluate` requests can race on posture transitions and JSONL
  appends. Adding `with self._lock:` around the body of `record_decision()` is
  safe (no deadlock: `evaluate_metasploit` inlines its recording rather than
  calling `record_decision`), but has not been done yet. Until fixed, avoid
  issuing parallel policy-evaluate requests in tests or production code that
  depends on strict posture ordering.

## CI workflows

| Workflow | Trigger | What it checks |
|----------|---------|----------------|
| `ci.yml` | push, PR | ruff check, mypy, pytest (Python 3.12) |
| `quality.yml` | push to main, PR | ruff check, ruff format --check, mypy, pytest (Python 3.13) |
| `bandit.yml` | push, PR | SAST via Bandit |
| `gitleaks.yml` | push, PR | Secret scanning |
| `codeql.yml` | push, PR | GitHub CodeQL analysis |
| `dependency-review.yml` | PR | Dependency vulnerability review |
| `bootstrap-guardrails.yml` | push, PR | Bootstrap safety checks |
| `release.yml` | tag push | Release packaging |

## API surface (from `src/rif_runtime/api.py`)

`[auth]` = requires `X-API-Key` header via `ControlPlaneAuth`.

```text
GET    /
GET    /health
GET    /v1/environments
POST   /v1/environment/{name}             [auth]
POST   /v1/policy/evaluate               [auth]
POST   /v1/posture/reset                 [auth]   ← must be before /v1/posture/{posture}
POST   /v1/posture/{posture}             [auth]
GET    /v1/graph/summary
GET    /v1/telemetry/summary
GET    /v1/persistence/summary
GET    /v1/recovered-state
GET    /v1/audit
POST   /v1/mcp/invoke                            (dry-run, unauthenticated)
GET    /v1/mcp/metasploit/capabilities
POST   /v1/mcp/metasploit/evaluate              (dry-run, unauthenticated)
POST   /v1/mcp/metasploit/token          [auth]
GET    /v1/policies
PUT    /v1/policies/{rule_id}            [auth]
DELETE /v1/policies/{rule_id}            [auth]
```
