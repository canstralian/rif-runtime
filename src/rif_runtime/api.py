from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from rif_runtime.agents.auditor import AuditorAgent
from rif_runtime.configuration.policies import PolicyRule
from rif_runtime.mcp.capabilities import capability_catalog
from rif_runtime.mcp.metasploit import (
    CapabilityToken,
    GovernanceMode,
    MetasploitIntent,
)

from .auth import ControlPlaneAuth
from .governance.drift import recommend_correction
from .replay import ReplayEngine
from .runtime import RIFRuntime
from .schemas import PolicyDecision, PolicyRequest, Posture
from .startup import register_config_startup

runtime = RIFRuntime()
app = FastAPI(title="RIF Runtime", version="0.1.0")

# Wire configuration validation into app startup
register_config_startup(app)


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
    runtime.posture = Posture.normal
    return {"posture": runtime.posture.value}


@app.post("/v1/posture/{posture}", dependencies=[ControlPlaneAuth])
def posture(posture: Posture) -> dict[str, Any]:
    runtime.posture = posture
    return {"posture": runtime.posture}


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": "RIF Runtime",
        "status": "online",
        "routes": ["/health", "/docs", "/v1/environments", "/v1/policy/evaluate"],
    }


@app.get("/v1/graph/summary")
def graph_summary() -> dict[str, Any]:
    return runtime.graph_summary()


@app.get("/v1/telemetry/summary")
def telemetry_summary() -> dict[str, Any]:
    return runtime.telemetry_summary()


@app.get("/v1/audit")
def audit() -> dict[str, Any]:
    return AuditorAgent().audit(runtime)


@app.post("/v1/mcp/invoke")
def mcp_invoke(payload: dict[str, Any]) -> PolicyDecision:
    from rif_runtime.schemas import PolicyRequest

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


@app.get("/v1/persistence/summary")
def persistence_summary() -> dict[str, Any]:
    return runtime.persisted_summary()


@app.get("/v1/recovered-state")
def recovered_state() -> dict[str, Any]:
    # Rebuilt from the persisted decision log, not from live runtime state, so
    # the response is meaningful after a restart.
    return asdict(ReplayEngine().recover())


@app.get("/v1/drift/recommend")
def drift_recommend() -> dict[str, Any]:
    vector = runtime.drift_vector()
    correction = recommend_correction(vector)
    return {
        "drift_vector": {
            "denial_rate": vector.denial_rate,
            "adversarial_score": vector.adversarial_score,
            "action_entropy": vector.action_entropy,
            "target_entropy": vector.target_entropy,
        },
        "recommended_correction": correction.value,
    }


@app.get("/v1/policies")
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
