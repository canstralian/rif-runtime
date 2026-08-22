# HTTP API Reference

The HTTP route definitions in `src/rif_runtime/api.py` are the source of truth. This document is a concise human-readable index; the running service's `/docs` and `/openapi.json` provide the generated schema.

## Public/runtime inspection

| Method | Route | Purpose | Auth |
|---|---|---|---|
| `GET` | `/` | Service/root metadata | None |
| `GET` | `/health` | Health/status information | None |
| `GET` | `/v1/environments` | List configured environments | None |
| `GET` | `/v1/graph/summary` | Governance graph summary | `X-API-Key` if `RIF_REQUIRE_READ_AUTH=true` |
| `GET` | `/v1/telemetry/summary` | Telemetry summary | `X-API-Key` if `RIF_REQUIRE_READ_AUTH=true` |
| `GET` | `/v1/persistence/summary` | Persistence summary | `X-API-Key` if `RIF_REQUIRE_READ_AUTH=true` |
| `GET` | `/v1/recovered-state` | Recovered runtime state | `X-API-Key` if `RIF_REQUIRE_READ_AUTH=true` |
| `GET` | `/v1/audit` | Audit/decision view | `X-API-Key` if `RIF_REQUIRE_READ_AUTH=true` |
| `GET` | `/v1/policies` | List policy rules | `X-API-Key` if `RIF_REQUIRE_READ_AUTH=true` |

## Governance operations

| Method | Route | Purpose | Auth |
|---|---|---|---|
| `POST` | `/v1/policy/evaluate` | Evaluate a policy request and record the decision | `X-API-Key` |
| `POST` | `/v1/mcp/invoke` | Evaluate the governed MCP path in dry-run mode | None |
| `POST` | `/v1/mcp/metasploit/evaluate` | Evaluate a Metasploit capability request in dry-run mode | None |
| `GET` | `/v1/mcp/metasploit/capabilities` | Inspect governed Metasploit capability metadata | None |

## Mutable control-plane operations

These routes are guarded by `X-API-Key` through `RIF_CONTROL_PLANE_API_KEYS`.

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/v1/environment/{name}` | Change the active environment |
| `POST` | `/v1/posture/{posture}` | Set runtime posture |
| `POST` | `/v1/posture/reset` | Reset posture |
| `PUT` | `/v1/policies/{rule_id}` | Create/update a policy rule |
| `DELETE` | `/v1/policies/{rule_id}` | Delete a policy rule |
| `POST` | `/v1/mcp/metasploit/token` | Mint a governed capability token |

## Startup posture

The posture a process starts in is the **more restrictive** of:

1. the last entry in `posture_history.jsonl` (or, with no history, the posture
   `ReplayEngine` derives from `decisions.jsonl`); and
2. the configured posture — `RIF_POSTURE`, or `[runtime] posture` in
   `rif.toml`, defaulting to `normal`.

Configuration is a **floor, not an assignment**: it can only tighten a runtime.
A runtime that escalated to `locked` is not relaxed to a configured `elevated`.

One asymmetry follows from this and is deliberate: `POST /v1/posture/reset`
relaxes the *running* process, but the next restart re-applies the configured
floor. To make a reset survive restart, lower the configured posture as well.

## Policy evaluation order

`PolicyEngine.evaluate()` decides in this order, stopping at the first match:

1. **Posture** — a `locked` runtime denies everything (`posture.locked`).
2. **Selective rules** — configured rules that name an action, a target, or
   both. Evaluated most-specific-first: a rule with both selectors concrete
   beats one with a single wildcard. Rules of equal specificity keep their
   order in `policies.json`, so position still breaks ties. A selective rule
   overrides the environment constraints below — naming an action/target pair
   is read as a deliberate operator intent.
3. **Environment constraints** — package-manager egress, MCP egress, and the
   `allowed_hosts` allowlist for `limited` networking.
4. **Catch-all rules** — rules with `action: "*"` *and* `target: "*"`. These
   are the configured fallback for everything not already decided. They run
   last on purpose: a catch-all `allow` evaluated earlier would silently
   disable the host allowlist in step 3.
5. **`default.allow`** — the built-in fallback when no catch-all is configured.

The shipped `data/policies.json` configures a catch-all deny
(`deny_unknown_by_default`), so an unconfigured action is denied rather than
allowed.

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

### Read-scope authentication

These routes disclose governance state — decision history, configured rules,
recovered state, and counters:

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/v1/audit` | Audit summary |
| `GET` | `/v1/policies` | List policy rules |
| `GET` | `/v1/recovered-state` | State rebuilt from the decision log |
| `GET` | `/v1/persistence/summary` | Persisted decision/posture counters |
| `GET` | `/v1/telemetry/summary` | Recent denial counters |
| `GET` | `/v1/graph/summary` | Governance graph summary |

They are **open by default**. Setting `RIF_REQUIRE_READ_AUTH=true` guards them
with the same `X-API-Key` check as the mutable operations, including the same
fail-closed behaviour when no key is configured:

```bash
export RIF_REQUIRE_READ_AUTH=true
export RIF_CONTROL_PLANE_API_KEYS='replace-with-a-secret-key'
```

The flag is opt-in so that upgrading does not break existing read clients. It
is intended to become the default; enable it now if the service is reachable
beyond a trusted network. `/health` and `/` stay open either way so liveness
probes need no credential.

`/openapi.json` and `/docs` also stay open and enumerate the route surface;
disable them in production if that inventory is itself sensitive.

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
