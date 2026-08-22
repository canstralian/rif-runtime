# RIF Runtime

[![Merge Gate](https://github.com/canstralian/rif-runtime/actions/workflows/merge-gate.yml/badge.svg)](https://github.com/canstralian/rif-runtime/actions/workflows/merge-gate.yml)
[![Coverage](https://github.com/canstralian/rif-runtime/actions/workflows/coverage.yml/badge.svg)](https://github.com/canstralian/rif-runtime/actions/workflows/coverage.yml)
[![Image](https://github.com/canstralian/rif-runtime/actions/workflows/image.yml/badge.svg)](https://github.com/canstralian/rif-runtime/actions/workflows/image.yml)
[![Release](https://github.com/canstralian/rif-runtime/actions/workflows/release.yml/badge.svg)](https://github.com/canstralian/rif-runtime/actions/workflows/release.yml)
[![CodeQL](https://github.com/canstralian/rif-runtime/actions/workflows/codeql.yml/badge.svg)](https://github.com/canstralian/rif-runtime/actions/workflows/codeql.yml)
[![Bandit](https://github.com/canstralian/rif-runtime/actions/workflows/bandit.yml/badge.svg)](https://github.com/canstralian/rif-runtime/actions/workflows/bandit.yml)
[![Gitleaks](https://github.com/canstralian/rif-runtime/actions/workflows/gitleaks.yml/badge.svg)](https://github.com/canstralian/rif-runtime/actions/workflows/gitleaks.yml)
[![License](https://img.shields.io/github/license/canstralian/rif-runtime)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)

**RIF Runtime is a policy and governance runtime for agent-driven systems.** It evaluates proposed actions before they cross a capability boundary, maintains runtime posture, and records decision history for inspection and replay.

The design goal is deliberately simple:

> **A model may propose. RIF decides.**

RIF is not an autonomous-agent framework and does not treat model confidence, possession of a provider credential, or model output as authorization.

## What exists today

The current Python implementation provides:

- policy evaluation with deny-oriented defaults and environment-aware constraints;
- runtime posture management and recovery from persisted state;
- a governance graph and telemetry summaries;
- append-only JSONL persistence for decisions and posture history;
- replay of persisted decision history into runtime state;
- MCP governance surfaces, including a governed Metasploit integration;
- authenticated control-plane operations using `X-API-Key` configuration;
- optional Supabase integration for execution-run/evidence persistence and JWT verification;
- FastAPI and Typer interfaces;
- automated quality and security workflows.

The repository also contains specifications and architectural proposals that are **not all implemented in the default runtime path**. Those documents are intentionally labelled as draft, planned, seeded, or implemented where appropriate.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m pip install -r requirements-dev.txt
rif serve
```

The API is available at `http://127.0.0.1:8000`.

Try a health check:

```bash
curl http://127.0.0.1:8000/health
```

Evaluate and record a policy request. Control-plane authentication is required:

```bash
export RIF_CONTROL_PLANE_API_KEYS='replace-with-a-secret-key'

curl -X POST http://127.0.0.1:8000/v1/policy/evaluate \
  -H 'X-API-Key: replace-with-a-secret-key' \
  -H 'content-type: application/json' \
  -d '{"actor":"agent:orchestrator","action":"http.request","target":"https://api.example.com/resource"}'
```

For the complete API surface, see [`docs/API.md`](docs/API.md) and the live OpenAPI document at `/openapi.json` when the service is running.

## Architecture in one picture

```text
Agent / caller
      |
      v
Policy request
      |
      v
+-------------------+
| Policy evaluation |
+-------------------+
      |
      +---- deny ----> decision + posture + persistence
      |
      +---- allow ---> governed capability / MCP path
                              |
                              v
                       decision history
                              |
                              v
                         replay / audit
```

The larger target architecture is documented separately from the implementation so that proposals do not masquerade as shipped behaviour. Start with [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Documentation map

- [`docs/README.md`](docs/README.md) — documentation index and source-of-truth rules
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — implementation architecture
- [`DEVELOPMENT.md`](DEVELOPMENT.md) — local development and validation
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — contributor workflow
- [`SECURITY.md`](SECURITY.md) — security model, limitations, and reporting
- [`DEPLOYMENT.md`](DEPLOYMENT.md) — supported container deployment paths
- [`TESTING.md`](TESTING.md) — testing strategy
- [`docs/API.md`](docs/API.md) — current HTTP routes
- [`docs/cli-reference.md`](docs/cli-reference.md) — current CLI commands
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — planned work
- [`docs/REFLEXIVE_EVOLUTION.md`](docs/REFLEXIVE_EVOLUTION.md) — reflexive design, explicitly separated from shipped behaviour
- [`spec/README.md`](spec/README.md) — contract/specification status

## Current maturity

RIF Runtime is an actively developed release-candidate project, not a claim of production certification or a completed enterprise control plane. Some enterprise-oriented controls remain future work, including SBOM generation, signed releases, reproducible release builds, and a fully governed remote-inference authorization seam.

Security and CI documentation describe repository controls that are present in source/workflow files; they do not constitute an independent assurance report.

## Contributing

RIF benefits from contributors who enjoy the awkward but important boundary between **what an intelligent system wants to do** and **what a governed system is willing to let it do**.

Good contributions include:

- tightening policy semantics;
- improving replay and evidence contracts;
- adding regression tests for security boundaries;
- making specifications executable and unambiguous;
- improving developer ergonomics and documentation;
- challenging claims that cannot be demonstrated from the repository.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) to get started.

## License

MIT. See [`LICENSE`](LICENSE).
