# RIF Runtime MVP

This page is a concise description of the current runtime path. It is not a claim that every package or specification in the repository is part of the MVP request path.

## Current circuit

```text
Request
  -> PolicyEngine
  -> Decision
  -> Posture / graph / telemetry
  -> JSONL persistence
  -> API inspection / replay
```

## Representative API surface

See [`API.md`](API.md) for the complete current route index. The most useful starting points are:

- `GET /`
- `GET /health`
- `GET /v1/environments`
- `POST /v1/environment/{name}`
- `POST /v1/policy/evaluate`
- `POST /v1/posture/reset`
- `POST /v1/posture/{posture}`
- `GET /v1/graph/summary`
- `GET /v1/telemetry/summary`
- `GET /v1/persistence/summary`
- `GET /v1/recovered-state`
- `GET /v1/audit`
- `POST /v1/mcp/invoke`
- `GET /v1/mcp/metasploit/capabilities`
- `POST /v1/mcp/metasploit/evaluate`
- `POST /v1/mcp/metasploit/token`
- `GET /v1/policies`
- `PUT /v1/policies/{rule_id}`
- `DELETE /v1/policies/{rule_id}`
- `POST /v1/runs`

Mutable control-plane routes require `X-API-Key` authentication.

## Local state

The default data directory contains runtime-generated JSONL state such as:

- `decisions.jsonl`;
- `posture_history.jsonl`;
- `metasploit_evidence.jsonl` when that integration is used.

Use `RIF_DATA_DIR` to isolate experiments and tests.

## Design principle

RIF keeps fast runtime state and durable local history separate. Durable history supports reconstruction and inspection, but local files are not an independently protected immutable ledger.

## Boundary

The MVP is a governance runtime, not an autonomous agent framework. Model output does not become policy authority, and external provider credentials do not by themselves authorize provider egress.
