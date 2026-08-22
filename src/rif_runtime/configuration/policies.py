from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ..config import get_settings
from ..schemas import Decision
from .store import JsonStore


class PolicyRule(BaseModel):
    id: str
    effect: Decision
    action: str = "*"
    target: str = "*"
    reason: str = "configured policy rule"
    metadata: dict[str, str] = Field(default_factory=dict)


# Deny-by-default means "deny what is not enumerated" -- so the runtime's own
# first-party actions have to be enumerated here. `run.create` backs
# POST /v1/runs, which is separately gated by a Supabase JWT
# (api._require_identity); without this rule that endpoint returns 403 for
# every caller. Operators tightening the default policy should replace this
# rule rather than delete it, or the endpoint stops working.
DEFAULT_POLICIES = {
    "rules": [
        {
            "id": "allow_run_create",
            "effect": "allow",
            "action": "run.create",
            "target": "*",
            "reason": "first-party governed run creation (POST /v1/runs)",
        },
        {
            "id": "allow_known_model_hosts",
            "effect": "allow",
            "action": "http.request",
            "target": "api.anthropic.com",
            "reason": "known model API host",
        },
        {
            "id": "deny_unknown_by_default",
            "effect": "deny",
            "action": "*",
            "target": "*",
            "reason": "deny by default",
        },
    ]
}


class PolicyStore:
    def __init__(self, path: str | Path | None = None):
        # RIFRuntime passes its configured data_dir; standalone callers fall
        # back to the same configured directory rather than a literal "data/".
        if path is None:
            path = Path(get_settings().paths.data_dir) / "policies.json"
        self.store = JsonStore(path, DEFAULT_POLICIES)

    def list(self) -> list[PolicyRule]:
        return [PolicyRule.model_validate(row) for row in self.store.read()["rules"]]

    def upsert(self, rule: PolicyRule) -> PolicyRule:
        rules = [r.model_dump() for r in self.list()]
        kept = [r for r in rules if r["id"] != rule.id]
        kept.append(rule.model_dump())
        self.store.write({"rules": kept})
        return rule

    def delete(self, rule_id: str) -> bool:
        rules = [r.model_dump() for r in self.list()]
        kept = [r for r in rules if r["id"] != rule_id]
        self.store.write({"rules": kept})
        return len(kept) != len(rules)
