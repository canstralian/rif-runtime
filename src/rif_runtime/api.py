import os
from dataclasses import asdict
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from . import __version__
from .agents.auditor import AuditorAgent
from .auth import ControlPlaneAuth, ReadPlaneAuth
from .configuration.policies import PolicyRule
from .integrations import supabase as sb
from .mcp.capabilities import capability_catalog
from .mcp.metasploit import (
    CapabilityToken,
    GovernanceMode,
    MetasploitIntent,
)
from .replay import ReplayEngine
from .runs.schemas import RunRecord, RunRequest, RunStatus
from .runtime import RIFRuntime
from .schemas import Decision, PolicyDecision, PolicyRequest, Posture
from .startup import config_lifespan, configuration_diagnostics, validate_config

# Validate before constructing the runtime: RIFRuntime() loads configuration,
# so an invalid rif.toml raises here, at import, long before config_lifespan
# could report it. Without this the operator gets a bare ConfigError traceback
# out of config.py rather than a message naming the configuration as the cause.
validate_config()

# The context manager covers the second half of configuration validation:
# RIFRuntime checks the parsed values against environments.yaml and raises for
# an unknown name, which validate_config() above cannot see.
with configuration_diagnostics():
    runtime = RIFRuntime()
app = FastAPI(
    title="RIF Runtime",
    lifespan=config_lifespan,
    # Resolved from package metadata (falling back to pyproject.toml in a
    # source checkout), not written out here. The literal was "0.3.0" against
    # a package version of 0.3.0rc2, so /openapi.json advertised a release the
    # installed distribution was not.
    version=__version__,
    # Mount prefix when served behind a reverse proxy at a sub-path. Read from
    # settings rather than left implicit, which made RIF_SERVER_ROOT_PATH inert.
    root_path=validate_config().server.root_path,
    description="Governed execution substrate for intelligent systems.",
)

# CORS — configure allowed origins via RIF_CORS_ORIGINS (comma-separated).
# Default permits only localhost dev; set to your Vercel URL in production.
_cors_origins = [
    o.strip()
    for o in os.environ.get("RIF_CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_bearer = HTTPBearer(auto_error=False)
_BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


def _require_identity(credentials: _BearerCredentials) -> str:
    """Verify a Supabase Bearer JWT and return the user UUID string."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return sb.verify_jwt(credentials.credentials)


IdentityId = Annotated[str, Depends(_require_identity)]


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "environment": runtime.environment_name,
        "posture": runtime.posture,
    }


@app.get("/v1/environments")
def environments() -> dict[str, Any]:
    return {
        "current": runtime.environment_name,
        "environments": runtime.config.environments,
    }


@app.post("/v1/environment/{name}", dependencies=[ControlPlaneAuth])
def set_environment(name: str) -> dict[str, Any]:
    try:
        runtime.set_environment(name)
        return {"current": runtime.environment_name}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/v1/policy/evaluate", dependencies=[ControlPlaneAuth])
def evaluate(req: PolicyRequest) -> PolicyDecision:
    return runtime.evaluate(req)


@app.post("/v1/posture/reset", dependencies=[ControlPlaneAuth])
def reset_posture() -> dict[str, Any]:
    # Must be registered before /v1/posture/{posture}, otherwise "reset" is
    # captured as a Posture path param and FastAPI returns 422.
    # set_posture(), not a bare assignment: the transition has to reach
    # posture_history.jsonl or the next restart restores the old posture.
    return {"posture": runtime.set_posture(Posture.normal).value}


@app.post("/v1/posture/{posture}", dependencies=[ControlPlaneAuth])
def posture(posture: Posture) -> dict[str, Any]:
    return {"posture": runtime.set_posture(posture)}


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": "RIF Runtime",
        "status": "online",
        "routes": ["/health", "/docs", "/v1/environments", "/v1/policy/evaluate"],
    }


@app.get("/v1/graph/summary", dependencies=[ReadPlaneAuth])
def graph_summary() -> dict[str, Any]:
    return runtime.graph_summary()


@app.get("/v1/telemetry/summary", dependencies=[ReadPlaneAuth])
def telemetry_summary() -> dict[str, Any]:
    return runtime.telemetry_summary()


@app.get("/v1/audit", dependencies=[ReadPlaneAuth])
def audit() -> dict[str, Any]:
    return AuditorAgent().audit(runtime)


@app.post("/v1/mcp/invoke")
def mcp_invoke(payload: dict[str, Any]) -> PolicyDecision:
    req = PolicyRequest(
        actor=payload.get("actor", "agent:mcp"),
        action="mcp.invoke",
        target=payload.get("target", "unknown"),
        reason=payload.get("reason"),
    )
    # Unauthenticated simulation route: dry-run so it cannot mutate posture or
    # write to the decision log. The authenticated /v1/policy/evaluate is the
    # recording path. See runtime.evaluate(record=...).
    return runtime.evaluate(req, record=False)


@app.get("/v1/mcp/metasploit/capabilities")
def metasploit_capabilities() -> dict[str, Any]:
    return capability_catalog()


@app.post("/v1/mcp/metasploit/evaluate")
def metasploit_evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        intent = MetasploitIntent.model_validate(payload.get("intent", payload))
        mode = GovernanceMode(
            payload.get("mode", GovernanceMode.read_only_firewall.value)
        )
        token = (
            CapabilityToken.model_validate(payload["token"])
            if payload.get("token")
            else None
        )
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    # Unauthenticated simulation route: dry-run so it cannot mutate posture or
    # write to the stores. Minting a capability token (the actual authorization)
    # goes through the guarded /v1/mcp/metasploit/token.
    outcome = runtime.evaluate_metasploit(intent, mode=mode, token=token, record=False)
    return {
        "decision": outcome.decision,
        "evidence": outcome.evidence,
        "simulated": outcome.simulated,
        "severe": outcome.severe,
        "posture": runtime.posture,
    }


@app.post("/v1/mcp/metasploit/token", dependencies=[ControlPlaneAuth])
def metasploit_token(payload: dict[str, Any]) -> CapabilityToken:
    if "intent" not in payload:
        raise HTTPException(status_code=422, detail="missing 'intent' in payload")
    try:
        intent = MetasploitIntent.model_validate(payload["intent"])
        # TypeError, not just ValueError: int(None) and int({}) raise TypeError,
        # so a null or object ttl_seconds would otherwise escape as a 500 while
        # a non-numeric string correctly returned 422.
        ttl_seconds = int(payload.get("ttl_seconds", 600))
    except (ValidationError, TypeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return runtime.metasploit.mint_token(
        intent,
        approver=payload.get("approver", "human:operator"),
        ttl_seconds=ttl_seconds,
    )


@app.get("/v1/persistence/summary", dependencies=[ReadPlaneAuth])
def persistence_summary() -> dict[str, Any]:
    return runtime.persisted_summary()


@app.get("/v1/recovered-state", dependencies=[ReadPlaneAuth])
def recovered_state() -> dict[str, Any]:
    # Rebuilt from the persisted decision log, not from live runtime state, so
    # the response is meaningful after a restart. Reads the runtime's own
    # configured path so the two can't diverge under RIF_DATA_DIR.
    return asdict(ReplayEngine(runtime.decisions_path).recover())


@app.get("/v1/policies", dependencies=[ReadPlaneAuth])
def list_policies() -> dict[str, Any]:
    return {"rules": [rule.model_dump() for rule in runtime.policy_store.list()]}


@app.put("/v1/policies/{rule_id}", dependencies=[ControlPlaneAuth])
def upsert_policy(rule_id: str, rule: PolicyRule) -> PolicyRule:
    if rule.id != rule_id:
        rule = rule.model_copy(update={"id": rule_id})
    return runtime.policy_store.upsert(rule)


@app.delete("/v1/policies/{rule_id}", dependencies=[ControlPlaneAuth])
def delete_policy(rule_id: str) -> dict[str, Any]:
    return {"deleted": runtime.policy_store.delete(rule_id)}


@app.post("/v1/runs")
def create_run(req: RunRequest, identity_id: IdentityId) -> RunRecord:
    """Create a governed execution run authenticated via Supabase JWT.

    Flow: verify identity → evaluate policy → record evidence → return run.
    The endpoint is deny-safe: a policy denial still writes evidence before
    returning 403 so the decision is always auditable.
    """
    run_id = str(uuid4())

    policy_req = PolicyRequest(
        actor=f"user:{identity_id}",
        action="run.create",
        target=req.prompt[:200],
        reason="vercel-frontend-run",
        context=req.context,
    )
    decision = runtime.evaluate(policy_req)

    run_status = (
        RunStatus.policy_approved
        if decision.decision == Decision.allow
        else RunStatus.denied
    )
    record = RunRecord(
        run_id=run_id,
        identity_id=identity_id,
        status=run_status,
        prompt=req.prompt,
        context=req.context,
        policy_decision=decision.decision.value,
        matched_rule=decision.matched_rule,
    )

    sb.write_run(run_id, identity_id, run_status.value, req.prompt)
    sb.write_evidence(run_id, "policy_decision", decision.model_dump(mode="json"))

    if decision.decision != Decision.allow:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"policy denied: {decision.reason}",
            headers={"X-RIF-Run-Id": run_id},
        )

    return record
