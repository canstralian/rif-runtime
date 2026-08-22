"""Tests for deny-by-default policy engine behavior (issue #40).

Verifies:
- Wildcard rules (action='*' or target='*') are evaluated, not skipped
- Unmatched requests are denied by default (no implicit allow)
"""

import pytest

from rif_runtime.configuration.policies import PolicyRule
from rif_runtime.policy import PolicyEngine, rule_matches
from rif_runtime.schemas import (
    Decision,
    EnvironmentProfile,
    PolicyDecision,
    PolicyRequest,
    Posture,
)


@pytest.fixture
def engine():
    return PolicyEngine()


@pytest.fixture
def open_profile():
    return EnvironmentProfile(networking_type="open", allowed_hosts=[])


@pytest.fixture
def limited_profile():
    return EnvironmentProfile(networking_type="limited", allowed_hosts=[])


# ---------------------------------------------------------------------------
# Deny-by-default: unmatched requests must be denied
# ---------------------------------------------------------------------------


class TestDenyByDefault:
    def test_no_rules_denies_request(self, engine, open_profile):
        """With no policy rules and open networking, requests are denied."""
        req = PolicyRequest(
            actor="agent:test", action="file.read", target="/etc/passwd"
        )
        decision = engine.evaluate(req, "test_env", open_profile, Posture.normal, [])

        assert decision.decision == Decision.deny
        assert decision.matched_rule == "default.deny"
        assert "no matching allow rule" in decision.reason

    def test_no_matching_rule_denies_request(self, engine, open_profile):
        """When rules exist but none match, the request is denied."""
        rule = PolicyRule(
            id="allow_read",
            effect="allow",
            action="file.read",
            target="/tmp",
        )
        req = PolicyRequest(
            actor="agent:test", action="file.write", target="/etc/passwd"
        )
        decision = engine.evaluate(
            req, "test_env", open_profile, Posture.normal, [rule]
        )

        assert decision.decision == Decision.deny
        assert decision.matched_rule == "default.deny"

    def test_unmatched_network_request_denied_open_profile(self, engine, open_profile):
        """Even with open networking, unmatched HTTP requests are denied."""
        req = PolicyRequest(
            actor="agent:test",
            action="http.request",
            target="https://evil.example.com/exfil",
        )
        decision = engine.evaluate(req, "test_env", open_profile, Posture.normal, [])

        assert decision.decision == Decision.deny
        assert decision.matched_rule == "default.deny"


# ---------------------------------------------------------------------------
# Wildcard rules: must be evaluated, not skipped
# ---------------------------------------------------------------------------


class TestWildcardRules:
    def test_wildcard_action_rule_is_evaluated(self, engine, open_profile):
        """A rule with action='*' matches any action."""
        rule = PolicyRule(
            id="deny_all_to_secrets",
            effect="deny",
            action="*",
            target="/secrets",
            reason="secrets are off-limits",
        )
        req = PolicyRequest(
            actor="agent:test", action="file.read", target="/secrets"
        )
        decision = engine.evaluate(
            req, "test_env", open_profile, Posture.normal, [rule]
        )

        assert decision.decision == Decision.deny
        assert decision.matched_rule == "policy.deny_all_to_secrets"
        assert decision.reason == "secrets are off-limits"

    def test_wildcard_target_rule_is_evaluated(self, engine, open_profile):
        """A rule with target='*' matches any target."""
        rule = PolicyRule(
            id="deny_all_http",
            effect="deny",
            action="http.request",
            target="*",
            reason="no outbound HTTP allowed",
        )
        req = PolicyRequest(
            actor="agent:test",
            action="http.request",
            target="https://anywhere.example.com",
        )
        decision = engine.evaluate(
            req, "test_env", open_profile, Posture.normal, [rule]
        )

        assert decision.decision == Decision.deny
        assert decision.matched_rule == "policy.deny_all_http"

    def test_wildcard_action_and_target_catch_all(self, engine, open_profile):
        """A rule with action='*' and target='*' catches all requests."""
        rule = PolicyRule(
            id="deny_everything",
            effect="deny",
            action="*",
            target="*",
            reason="catch-all deny",
        )
        req = PolicyRequest(
            actor="agent:test", action="file.write", target="/any/path"
        )
        decision = engine.evaluate(
            req, "test_env", open_profile, Posture.normal, [rule]
        )

        assert decision.decision == Decision.deny
        assert decision.matched_rule == "policy.deny_everything"

    def test_wildcard_allow_rule_grants_access(self, engine, open_profile):
        """A wildcard allow rule permits access when it matches."""
        rule = PolicyRule(
            id="allow_all_reads",
            effect="allow",
            action="file.read",
            target="*",
            reason="reads are safe",
        )
        req = PolicyRequest(
            actor="agent:test", action="file.read", target="/any/file"
        )
        decision = engine.evaluate(
            req, "test_env", open_profile, Posture.normal, [rule]
        )

        assert decision.decision == Decision.allow
        assert decision.matched_rule == "policy.allow_all_reads"

    def test_rule_order_preserved_with_wildcards(self, engine, open_profile):
        """First matching rule wins, even when wildcards are involved."""
        allow_specific = PolicyRule(
            id="allow_api",
            effect="allow",
            action="http.request",
            target="api.anthropic.com",
            reason="known model API",
        )
        deny_all = PolicyRule(
            id="deny_all",
            effect="deny",
            action="*",
            target="*",
            reason="catch-all deny",
        )
        req = PolicyRequest(
            actor="agent:test",
            action="http.request",
            target="https://api.anthropic.com/v1/messages",
        )
        decision = engine.evaluate(
            req, "test_env", open_profile, Posture.normal, [allow_specific, deny_all]
        )

        assert decision.decision == Decision.allow
        assert decision.matched_rule == "policy.allow_api"

    def test_wildcard_deny_blocks_non_matching_specific_allow(
        self, engine, open_profile
    ):
        """Wildcard deny after a non-matching allow still denies."""
        allow_specific = PolicyRule(
            id="allow_api",
            effect="allow",
            action="http.request",
            target="api.anthropic.com",
        )
        deny_all = PolicyRule(
            id="deny_all",
            effect="deny",
            action="*",
            target="*",
            reason="catch-all",
        )
        req = PolicyRequest(
            actor="agent:test",
            action="http.request",
            target="https://evil.example.com",
        )
        decision = engine.evaluate(
            req, "test_env", open_profile, Posture.normal, [allow_specific, deny_all]
        )

        assert decision.decision == Decision.deny
        assert decision.matched_rule == "policy.deny_all"


# ---------------------------------------------------------------------------
# rule_matches helper: wildcard support
# ---------------------------------------------------------------------------


class TestRuleMatches:
    def test_wildcard_action_matches_any(self):
        rule = PolicyRule(id="r1", effect="deny", action="*", target="foo")
        req = PolicyRequest(actor="a", action="file.write", target="foo")
        assert rule_matches(rule, req) is True

    def test_wildcard_target_matches_any(self):
        rule = PolicyRule(id="r1", effect="deny", action="file.read", target="*")
        req = PolicyRequest(actor="a", action="file.read", target="/anything")
        assert rule_matches(rule, req) is True

    def test_both_wildcards_match_anything(self):
        rule = PolicyRule(id="r1", effect="deny", action="*", target="*")
        req = PolicyRequest(actor="a", action="mcp.invoke", target="some-server")
        assert rule_matches(rule, req) is True

    def test_specific_action_does_not_match_different(self):
        rule = PolicyRule(id="r1", effect="deny", action="file.read", target="*")
        req = PolicyRequest(actor="a", action="file.write", target="/foo")
        assert rule_matches(rule, req) is False
