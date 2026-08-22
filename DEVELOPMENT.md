# Development Guide

This guide is intentionally command-first. If a command is not backed by the current repository, it does not belong here.

## Prerequisites

- Python 3.12 or 3.13
- Git
- Docker and Docker Compose, if you want container workflows
- Make, if you want the repository shortcuts

## Local setup

```bash
git clone https://github.com/canstralian/rif-runtime.git
cd rif-runtime
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m pip install -r requirements-dev.txt
```

For the locked CI environment:

```bash
python -m pip install --require-hashes -r requirements/dev.txt
python -m pip install -e . --no-deps
```

## Run the service

Development server:

```bash
rif serve
```

`rif serve` runs a single foreground Uvicorn process. Pass `--reload` while
working on the runtime to restart it when source files change:

```bash
rif serve --reload
```

Reload is a development convenience: it starts a file-watching supervisor and
should not be used for a deployed service.

The service exposes FastAPI documentation at `/docs` and `/redoc`.

## Run with Docker

```bash
docker compose up --build
```

The repository uses `compose.yaml`, not `docker-compose.yml`.

For the production-oriented compose file supplied by the repository:

```bash
docker compose -f docker-compose.prod.yml up -d
```

See [`DEPLOYMENT.md`](DEPLOYMENT.md) before using that configuration as a production baseline.

## Current CLI

The implemented commands are:

```bash
rif serve
rif check <actor> <action> <target>
rif replay [decisions_path]
rif msf-check <capability> <target> [--mode ...] [--actor ...] [--scope-id ...]
```

Do not use the older `rif execute`, `rif evidence`, or `rif telemetry` examples found in historical documentation; those are not current CLI commands.

## Validation

Run the focused checks first:

```bash
ruff check src tests
ruff format --check src tests
mypy src/rif_runtime --ignore-missing-imports
pytest -q
```

Security checks used by the repository include:

```bash
bandit -r src/ -ll
pip-audit --requirement requirements/runtime.txt --disable-pip
pip-audit --requirement requirements/dev.txt --disable-pip
```

Gitleaks, CodeQL, Dependency Review, and the merge gate are configured in GitHub Actions. A configured workflow is not the same thing as a passing run; verify the run when reporting validation status.

## Dependency locks

The canonical generated locks are:

- `requirements/runtime.txt` — runtime dependencies;
- `requirements/dev.txt` — runtime plus development dependencies.

Regenerate them with:

```bash
make lock
```

Deliberately upgrade resolved versions with:

```bash
make lock-upgrade
```

See [`requirements/README.md`](requirements/README.md) for the lock model.

## Runtime state

By default, runtime-generated state lives under `data/`. The `RIF_DATA_DIR` environment variable can point the runtime at an isolated directory, which is useful for tests and experiments.

Common files include:

- `decisions.jsonl`;
- `posture_history.jsonl`;
- `metasploit_evidence.jsonl`.

Avoid using repository state as a test fixture. Tests should use isolated temporary directories where persistence is involved.

## API development

`src/rif_runtime/api.py` is the current HTTP route source of truth.

When changing an endpoint:

1. update the Pydantic request/response models if required;
2. add or update tests;
3. update [`docs/API.md`](docs/API.md) and any CLI/user documentation affected;
4. consider authentication, persistence, replay, and compatibility impact.

The application also exposes OpenAPI at `/openapi.json` while running.

## Policy development

Policy changes should be treated as security-sensitive. Before merging, explain:

- what actor/action/target combinations change;
- whether deny precedence changes;
- whether posture transitions change;
- whether persisted records or replay semantics change;
- what regression tests prove the intended boundary.

## MCP development

MCP integrations are governance boundaries, not an implicit permission to execute tools. Changes should make the authorization decision explicit and should not promote model output into authority.

The Metasploit integration is currently a governed evaluation surface; it should not be described as unrestricted Metasploit execution.

## Documentation development

Documentation has an evidence discipline:

- implemented behaviour is described from code/tests;
- configured controls are described from repository configuration;
- specifications are labelled as specifications;
- future work is labelled planned;
- unknown status is marked unverified.

Avoid stale endpoint lists, invented performance targets, unsupported compliance claims, and examples for commands that do not exist.

See [`docs/README.md`](docs/README.md) for the documentation map.
