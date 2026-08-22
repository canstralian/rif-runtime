import pytest
from pydantic import ValidationError

from rif_runtime.configuration.policies import PolicyRule, PolicyStore
from rif_runtime.policy import PolicyEngine
from rif_runtime.schemas import EnvironmentProfile, PolicyRequest, Posture


def test_policy_store_upsert_and_delete(tmp_path):
    store = PolicyStore(str(tmp_path / "policies.json"))

    rule = PolicyRule(
        id="test_rule",
        effect="deny",
        action="http.request",
        target="example.com",
    )

    store.upsert(rule)
    assert any(r.id == "test_rule" for r in store.list())

    assert store.delete("test_rule") is True
    assert not any(r.id == "test_rule" for r in store.list())


def test_custom_policy_rule_overrides_engine_default():
    profile = EnvironmentProfile(networking_type="open", allowed_hosts=[])
    req = PolicyRequest(
        actor="agent:test", action="http.request", target="https://example.com"
    )

    rule = PolicyRule(
        id="block_example", effect="deny", action="http.request", target="example.com"
    )
    decision = PolicyEngine().evaluate(
        req, "RIF_Runtime", profile, Posture.normal, [rule]
    )

    assert decision.decision == "deny"
    assert decision.matched_rule == "policy.block_example"


def test_custom_allow_rule_overrides_network_denial():
    profile = EnvironmentProfile(networking_type="limited", allowed_hosts=[])
    req = PolicyRequest(
        actor="agent:test", action="http.request", target="https://api.anthropic.com"
    )

    rule = PolicyRule(
        id="allow_known_model_hosts",
        effect="allow",
        action="http.request",
        target="api.anthropic.com",
    )
    decision = PolicyEngine().evaluate(req, "RIF_CI", profile, Posture.normal, [rule])

    assert decision.decision == "allow"
    assert decision.matched_rule == "policy.allow_known_model_hosts"


def test_custom_rule_matches_full_url_target():
    profile = EnvironmentProfile(networking_type="open", allowed_hosts=[])
    req = PolicyRequest(
        actor="agent:test", action="http.request", target="https://example.com/path"
    )

    rule = PolicyRule(
        id="block_example",
        effect="deny",
        action="http.request",
        target="https://example.com",
    )
    decision = PolicyEngine().evaluate(
        req, "RIF_Runtime", profile, Posture.normal, [rule]
    )

    assert decision.decision == "deny"
    assert decision.matched_rule == "policy.block_example"


def test_policy_rule_rejects_invalid_effect():
    with pytest.raises(ValidationError):
        PolicyRule(
            id="bad_rule", effect="alloww", action="http.request", target="example.com"
        )


# --- wildcard rule precedence ------------------------------------------------
#
# Regression cover for the wildcard rules that PolicyEngine.evaluate() used to
# skip outright: the shipped `deny_unknown_by_default` rule was loaded, listed
# by GET /v1/policies, and never applied.


def _open_profile() -> EnvironmentProfile:
    return EnvironmentProfile(networking_type="open", allowed_hosts=[])


def _shipped_rules() -> list[PolicyRule]:
    from rif_runtime.configuration.policies import DEFAULT_POLICIES

    return [PolicyRule.model_validate(row) for row in DEFAULT_POLICIES["rules"]]


def test_shipped_catch_all_denies_unknown_target():
    """The default policy file's deny_unknown_by_default rule actually applies."""
    req = PolicyRequest(
        actor="agent:test", action="http.request", target="https://unknown.example.net"
    )

    decision = PolicyEngine().evaluate(
        req, "RIF_Runtime", _open_profile(), Posture.normal, _shipped_rules()
    )

    assert decision.decision == "deny"
    assert decision.matched_rule == "policy.deny_unknown_by_default"


def test_shipped_specific_allow_survives_the_catch_all():
    """A concrete allow still wins even though a catch-all deny is configured."""
    req = PolicyRequest(
        actor="agent:test", action="http.request", target="https://api.anthropic.com"
    )

    decision = PolicyEngine().evaluate(
        req, "RIF_Runtime", _open_profile(), Posture.normal, _shipped_rules()
    )

    assert decision.decision == "allow"
    assert decision.matched_rule == "policy.allow_known_model_hosts"


def test_action_wildcard_rule_matches_any_action_on_target():
    rule = PolicyRule(
        id="block_host_entirely", effect="deny", action="*", target="example.com"
    )
    req = PolicyRequest(
        actor="agent:test", action="api.call", target="https://example.com/v1"
    )

    decision = PolicyEngine().evaluate(
        req, "RIF_Runtime", _open_profile(), Posture.normal, [rule]
    )

    assert decision.decision == "deny"
    assert decision.matched_rule == "policy.block_host_entirely"


def test_target_wildcard_rule_matches_any_target_for_action():
    rule = PolicyRule(
        id="no_package_installs", effect="deny", action="package.install", target="*"
    )
    req = PolicyRequest(
        actor="agent:test", action="package.install", target="https://pypi.org/simple"
    )

    decision = PolicyEngine().evaluate(
        req, "RIF_Runtime", _open_profile(), Posture.normal, [rule]
    )

    assert decision.decision == "deny"
    assert decision.matched_rule == "policy.no_package_installs"


def test_more_specific_rule_wins_regardless_of_configured_order():
    """Specificity, not position, decides which of two matching rules applies."""
    broad = PolicyRule(
        id="broad_deny", effect="deny", action="http.request", target="*"
    )
    narrow = PolicyRule(
        id="narrow_allow", effect="allow", action="http.request", target="example.com"
    )
    req = PolicyRequest(
        actor="agent:test", action="http.request", target="https://example.com"
    )

    for rules in ([broad, narrow], [narrow, broad]):
        decision = PolicyEngine().evaluate(
            req, "RIF_Runtime", _open_profile(), Posture.normal, list(rules)
        )
        assert decision.matched_rule == "policy.narrow_allow", (
            f"specificity ignored for order {[r.id for r in rules]}"
        )
        assert decision.decision == "allow"


def test_equal_specificity_keeps_configured_order():
    first = PolicyRule(
        id="first", effect="deny", action="http.request", target="example.com"
    )
    second = PolicyRule(
        id="second", effect="allow", action="http.request", target="example.com"
    )
    req = PolicyRequest(
        actor="agent:test", action="http.request", target="https://example.com"
    )

    decision = PolicyEngine().evaluate(
        req, "RIF_Runtime", _open_profile(), Posture.normal, [first, second]
    )

    assert decision.matched_rule == "policy.first"


def test_catch_all_allow_does_not_disable_the_host_allowlist():
    """A "*"/"*" allow is a fallback, not an override of network constraints.

    Letting the catch-all run before the profile check would turn one broad
    rule into a silent bypass of allowed_hosts.
    """
    rule = PolicyRule(id="allow_everything", effect="allow", action="*", target="*")
    profile = EnvironmentProfile(networking_type="limited", allowed_hosts=[])
    req = PolicyRequest(
        actor="agent:test", action="http.request", target="https://example.com"
    )

    decision = PolicyEngine().evaluate(req, "RIF_CI", profile, Posture.normal, [rule])

    assert decision.decision == "deny"
    assert decision.matched_rule == "network.host.denied"


def test_locked_posture_still_precedes_every_rule():
    rule = PolicyRule(id="allow_everything", effect="allow", action="*", target="*")
    req = PolicyRequest(
        actor="agent:test", action="http.request", target="https://example.com"
    )

    decision = PolicyEngine().evaluate(
        req, "RIF_Runtime", _open_profile(), Posture.locked, [rule]
    )

    assert decision.decision == "deny"
    assert decision.matched_rule == "posture.locked"


def test_no_rules_falls_back_to_default_allow():
    """Removing every rule leaves the built-in fallback intact."""
    req = PolicyRequest(
        actor="agent:test", action="http.request", target="https://example.com"
    )

    decision = PolicyEngine().evaluate(
        req, "RIF_Runtime", _open_profile(), Posture.normal, []
    )

    assert decision.decision == "allow"
    assert decision.matched_rule == "default.allow"


# --- first-party actions under deny-by-default -------------------------------
#
# Enabling the catch-all deny broke POST /v1/runs: `run.create` had no allowing
# rule, so every authenticated run creation returned 403. The MST harness hit
# the same fallthrough break and got an explicit rule; this first-party route
# did not. These tests generalise that, so the next action the runtime
# evaluates on its own behalf cannot be swept up silently.


def _first_party_actions() -> set[str]:
    """Every action literal the runtime itself passes to PolicyRequest."""
    import ast
    from pathlib import Path

    actions = set()
    for path in (Path(__file__).resolve().parent.parent / "src").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name != "PolicyRequest":
                continue
            for kw in node.keywords:
                if kw.arg == "action" and isinstance(kw.value, ast.Constant):
                    actions.add(kw.value.value)
    return actions


def test_first_party_actions_are_the_expected_set():
    """Pins the inventory so a new one shows up here first."""
    assert _first_party_actions() == {"http.request", "mcp.invoke", "run.create"}


def test_run_create_is_allowed_by_the_shipped_policy():
    """POST /v1/runs must not 403 on policy grounds out of the box."""
    req = PolicyRequest(
        actor="user:00000000-0000-0000-0000-000000000000",
        action="run.create",
        target="a prompt",
    )

    decision = PolicyEngine().evaluate(
        req, "RIF_Runtime", _open_profile(), Posture.normal, _shipped_rules()
    )

    assert decision.decision == "allow"
    assert decision.matched_rule == "policy.allow_run_create"


def test_shipped_data_policies_matches_default_policies():
    """data/policies.json is the seeded copy of DEFAULT_POLICIES; keep them equal.

    They are separate files, so a rule added to one and not the other produces
    a runtime whose behaviour depends on whether data/ was pre-seeded.
    """
    import json
    from pathlib import Path

    from rif_runtime.configuration.policies import DEFAULT_POLICIES

    shipped = json.loads(
        (Path(__file__).resolve().parent.parent / "data" / "policies.json").read_text(
            encoding="utf-8"
        )
    )

    def normalise(rules):
        return sorted(
            (r["id"], r["effect"], r.get("action", "*"), r.get("target", "*"))
            for r in rules
        )

    assert normalise(shipped["rules"]) == normalise(DEFAULT_POLICIES["rules"])


def test_mcp_invoke_simulation_reports_the_denial_rather_than_bypassing_it():
    """/v1/mcp/invoke is a dry run: reporting `deny` is correct output.

    Covered explicitly so the absence of an `mcp.invoke` allow rule reads as a
    decision rather than an oversight like `run.create` was. Two distinct
    denials reach it, and which one fires depends on the profile:
    """
    req = PolicyRequest(actor="agent:mcp", action="mcp.invoke", target="tool:whatever")

    # Default profile: MCP egress is off, so the environment constraint denies
    # it before any catch-all rule is reached.
    egress_off = EnvironmentProfile(
        networking_type="open", allow_mcp_server_network_access=False
    )
    decision = PolicyEngine().evaluate(
        req, "RIF_Runtime", egress_off, Posture.normal, _shipped_rules()
    )
    assert decision.decision == "deny"
    assert decision.matched_rule == "mcp.egress.disabled"

    # With egress permitted it falls through to the catch-all, which is the
    # deny-by-default behaviour rather than an allow.
    egress_on = EnvironmentProfile(
        networking_type="open", allow_mcp_server_network_access=True, allowed_hosts=[]
    )
    decision = PolicyEngine().evaluate(
        req, "RIF_Runtime", egress_on, Posture.normal, _shipped_rules()
    )
    assert decision.decision == "deny"
    assert decision.matched_rule == "policy.deny_unknown_by_default"


def test_a_cold_start_with_no_data_dir_seeds_the_shipped_rules(tmp_path):
    """An empty data directory is not an empty policy.

    The Vercel deployment sets RIF_DATA_DIR=/tmp/rif-data, which is empty on
    every cold start, so it was read as "deny-by-default with no rules loaded,
    therefore the deployment denies everything". JsonStore seeds DEFAULT_POLICIES
    when the file is absent, so a cold start gets exactly the shipped ruleset --
    including the allow rules, not just the catch-all deny.
    """
    absent = tmp_path / "never-created" / "policies.json"
    assert not absent.exists()

    rules = {rule.id: rule for rule in PolicyStore(absent).list()}

    assert rules["deny_unknown_by_default"].effect == "deny"
    assert rules["allow_run_create"].effect == "allow"
    assert rules["allow_known_model_hosts"].effect == "allow"
