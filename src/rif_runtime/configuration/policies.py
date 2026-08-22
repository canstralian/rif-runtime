from __future__ import annotations

from pathlib import Path
from typing import Any

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

# First-party rules that must remain present on upgrade. Optional seed rules
# (e.g. allow_known_model_hosts) are intentionally excluded so an operator
# deletion is not undone when loading an existing policies.json.
REQUIRED_FIRST_PARTY_RULE_IDS = frozenset({"allow_run_create"})


def _is_catch_all_rule(rule: dict[str, Any]) -> bool:
    return str(rule.get("action", "*")) == "*" and str(rule.get("target", "*")) == "*"


class PolicyStore:
    def __init__(self, path: str | Path | None = None):
        # RIFRuntime passes its configured data_dir; standalone callers fall
        # back to the same configured directory rather than a literal "data/".
        if path is None:
            path = Path(get_settings().paths.data_dir) / "policies.json"
        self.store = JsonStore(path, DEFAULT_POLICIES)
        self._ensure_required_first_party_rules()

    def _ensure_required_first_party_rules(self) -> None:
        """Insert missing required defaults before any catch-all ``*/*`` rule.

        ``JsonStore`` only seeds when the file is absent, so pre-PR deployments
        keep a policies.json that has deny-by-default but no ``allow_run_create``.
        Only REQUIRED_FIRST_PARTY_RULE_IDS are restored; optional seed rules are
        left as the operator left them.
        """
        data = self.store.read()
        rules = list(data.get("rules") or [])
        present = {rule.get("id") for rule in rules}
        missing = [
            dict(rule)
            for rule in DEFAULT_POLICIES["rules"]
            if rule["id"] in REQUIRED_FIRST_PARTY_RULE_IDS and rule["id"] not in present
        ]
        if not missing:
            return
        insert_at = next(
            (i for i, rule in enumerate(rules) if _is_catch_all_rule(rule)),
            len(rules),
        )
        upgraded = rules[:insert_at] + missing + rules[insert_at:]
        self.store.write({"rules": upgraded})

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
