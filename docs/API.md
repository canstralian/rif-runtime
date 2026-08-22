# HTTP API Reference

The HTTP route definitions in `src/rif_runtime/api.py` are the source of truth. This document is a concise human-readable index; the running service's `/docs` and `/openapi.json` provide the generated schema.

## Public/runtime inspection

| Method | Route | Purpose | Auth |
|---|---|---|---|
| `GET` | `/` | Service/root metadata | None |
| `GET` | `/health` | Health/status information | None |
| `GET` | `/v1/environments` | List configured environments | None |
| `GET` | `/v1/graph/summary` | Governance graph summary | None |
| `GET` | `/v1/telemetry/summary` | Telemetry summary | None |
| `GET` | `/v1/persistence/summary` | Persistence summary | None |
| `GET` | `/v1/recovered-state` | Recovered runtime state | None |
| `GET` | `/v1/audit` | Audit/decision view | None |

## Governance operations

| Method | Route | Purpose | Auth |
|---|---|---|---|
| `POST` | `/v1/policy/evaluate` | Evaluate a policy request and record the decision | `X-API-Key` |
| `POST` | `/v1/mcp/invoke` | Evaluate the governed MCP path in dry-run mode | None |
| `POST` | `/v1/mcp/metasploit/evaluate` | Evaluate a Metasploit capability request in dry-run mode | None |
| `GET` | `/v1/mcp/metasploit/capabilities` | Inspect governed Metasploit capability metadata | None |

## Policy management

| Method | Route | Purpose | Auth |
|---|---|---|---|
| `GET` | `/v1/policies` | List policy rules | None |
| `PUT` | `/v1/policies/{rule_id}` | Create/update a policy rule | `X-API-Key` |
| `DELETE` | `/v1/policies/{rule_id}` | Delete a policy rule | `X-API-Key` |

## Mutable control-plane operations

These routes are guarded by `X-API-Key` through `RIF_CONTROL_PLANE_API_KEYS`.

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/v1/environment/{name}` | Change the active environment |
| `POST` | `/v1/posture/{posture}` | Set runtime posture |
| `POST` | `/v1/posture/reset` | Reset posture |
| `POST` | `/v1/mcp/metasploit/token` | Mint a governed capability token |

## Execution runs

| Method | Route | Purpose | Auth |
|---|---|---|---|
| `POST` | `/v1/runs` | Create a governed execution run | Supabase JWT |

## Authentication

Configure one or more control-plane keys:

```bash
export RIF_CONTROL_PLANE_API_KEYS='replace-with-a-secret-key'
```

Supply the selected key as:

```http
X-API-Key: replace-with-a-secret-key
```

If no control-plane key is configured, guarded operations return `503` rather than silently becoming unauthenticated.

## Example

Evaluate and record a policy request using the configured control-plane key:

```bash
curl -X POST http://127.0.0.1:8000/v1/policy/evaluate \
  -H 'X-API-Key: replace-with-a-secret-key' \
  -H 'content-type: application/json' \
  -d '{"actor":"agent:test","action":"http.request","target":"https://example.com"}'
```

The exact response schema is defined by the Pydantic models in `src/rif_runtime/schemas.py` and exposed through the generated OpenAPI document.

## Important boundary

A successful policy evaluation is not equivalent to an unrestricted external side effect. The current runtime contains governance and capability surfaces, while broader execution/evidence contracts remain under active development. In particular, remote model/provider access must not be treated as authorized merely because credentials are configured.

## Compatibility

The API is currently versioned under `/v1`, but the repository is still a release-candidate project. Consumers should pin a known release/tag and test compatibility rather than assuming enterprise-level backward-compatibility guarantees.
