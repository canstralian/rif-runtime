"""Runner units: permissions, chain, escalation, resolution (spec §3.4, §4.7, §4.9, §2.2)."""

from __future__ import annotations

import pytest

from wfa.runner.chain import ChainGuard
from wfa.runner.escalation import ApprovalError, EscalationBroker, resolved_action_hash
from wfa.runner.permissions import credential_scope, intersect_permissions
from wfa.runner.resolve import PROTECTED, SignedRegistry, WorkflowResolver
from wfa.shared.enums import Profile, profile_satisfies
from wfa.shared.errors import HardBlock, RegistrationError

WF_YAML = """
version: "1"
id: pr-summary
on:
  pull_request: [opened]
profile_required: UNTRUSTED
permissions: [contents:read, issues:write]
credentials: [github_token]
steps:
  - id: s
    uses: llm.summarise
    taint: SOURCE
    permission: contents:read
    output_schema: x.json
    with: {content: "${event.pr.diff}"}
"""


# ------------------------------------------------------------------- permissions
def test_trusted_gets_full_declared_permissions():
    eff = intersect_permissions(Profile.TRUSTED, ["a:write", "b:read"], ["b:read"])
    assert eff == frozenset({"a:write", "b:read"})


def test_untrusted_limited_to_read_allowlist():
    eff = intersect_permissions(Profile.UNTRUSTED, ["a:write", "b:read"], ["b:read"])
    assert eff == frozenset({"b:read"})


def test_unspecified_profile_gets_nothing():
    assert intersect_permissions(Profile.UNSPECIFIED, ["a"], ["a"]) == frozenset()


def test_credential_scope_zero_for_untrusted():
    assert credential_scope(Profile.UNTRUSTED, ["t"]) == frozenset()
    assert credential_scope(Profile.TRUSTED, ["t"]) == frozenset({"t"})


def test_profile_satisfies():
    assert profile_satisfies(Profile.TRUSTED, Profile.UNTRUSTED)
    assert profile_satisfies(Profile.UNTRUSTED, Profile.UNTRUSTED)
    assert not profile_satisfies(Profile.UNTRUSTED, Profile.TRUSTED)
    assert not profile_satisfies(Profile.UNSPECIFIED, Profile.UNTRUSTED)


# ------------------------------------------------------------------------- chain
def test_chain_depth_guard_raises():
    g = ChainGuard(max_chain_depth=3, engine_actor="bot")
    g.check_depth(3)
    with pytest.raises(HardBlock) as e:
        g.check_depth(4)
    assert e.value.rule_id == "HB-7"


def test_self_actor_dropped_without_optin():
    g = ChainGuard(3, "bot")
    assert not g.admit("bot", 0, workflow_opts_in_self=False).proceed
    assert g.admit("bot", 0, workflow_opts_in_self=True).proceed
    assert g.admit("human", 0, workflow_opts_in_self=False).proceed


def test_admit_respects_depth_even_with_optin():
    g = ChainGuard(1, "bot")
    assert not g.admit("bot", 5, workflow_opts_in_self=True).proceed


# -------------------------------------------------------------------- escalation
def test_escalation_token_roundtrip():
    b = EscalationBroker(b"key", ttl_s=600)
    ah = resolved_action_hash("merge PR octo/repo#7")
    tok = b.mint("run1", "step1", ah, now=1000.0)
    b.verify_and_consume(tok, "run1", "step1", ah, now=1100.0)


def test_escalation_single_use():
    b = EscalationBroker(b"key")
    ah = resolved_action_hash("act")
    tok = b.mint("r", "s", ah, now=0.0)
    b.verify_and_consume(tok, "r", "s", ah, now=1.0)
    with pytest.raises(ApprovalError):
        b.verify_and_consume(tok, "r", "s", ah, now=2.0)


def test_escalation_timeout_aborts():
    b = EscalationBroker(b"key", ttl_s=600)
    ah = resolved_action_hash("act")
    tok = b.mint("r", "s", ah, now=0.0)
    with pytest.raises(ApprovalError):
        b.verify_and_consume(tok, "r", "s", ah, now=1000.0)


def test_escalation_action_drift_aborts():
    b = EscalationBroker(b"key")
    tok = b.mint("r", "s", resolved_action_hash("merge A"), now=0.0)
    with pytest.raises(ApprovalError):
        b.verify_and_consume(tok, "r", "s", resolved_action_hash("merge B"), now=1.0)


def test_escalation_run_step_mismatch_aborts():
    b = EscalationBroker(b"key")
    ah = resolved_action_hash("act")
    tok = b.mint("r", "s", ah, now=0.0)
    with pytest.raises(ApprovalError):
        b.verify_and_consume(tok, "other", "s", ah, now=1.0)


def test_escalation_hmac_mismatch_aborts():
    good = EscalationBroker(b"key")
    ah = resolved_action_hash("act")
    tok = good.mint("r", "s", ah, now=0.0)
    forged = EscalationBroker(b"different-key")
    with pytest.raises(ApprovalError):
        forged.verify_and_consume(tok, "r", "s", ah, now=1.0)


# --------------------------------------------------------------------- resolution
def _registry(step_types=None):
    reg = SignedRegistry(b"k", declared_step_types=step_types or {"llm.summarise"})
    raw = WF_YAML.encode()
    reg.load_signed(raw, sign_registry_with(b"k", raw))
    return reg


def sign_registry_with(key: bytes, raw: bytes) -> str:
    import hashlib
    import hmac

    return hmac.new(key, raw, hashlib.sha256).hexdigest()


def test_resolver_returns_protected_definition():
    reg = _registry()
    wf = WorkflowResolver(reg).resolve("pr-summary", PROTECTED)
    assert wf.id == "pr-summary" and wf.source_ref == "signed-registry"


def test_resolver_rejects_head_ref_source():
    reg = _registry()
    with pytest.raises(HardBlock) as e:
        WorkflowResolver(reg).resolve("pr-summary", "refs/pull/1/head")
    assert e.value.rule_id == "HB-3"


def test_resolver_rejects_unknown_workflow():
    reg = _registry()
    with pytest.raises(HardBlock):
        WorkflowResolver(reg).resolve("nope", PROTECTED)


def test_registry_rejects_bad_signature():
    reg = SignedRegistry(b"k")
    with pytest.raises(HardBlock) as e:
        reg.load_signed(WF_YAML.encode(), "deadbeef")
    assert e.value.rule_id == "HB-8"


def test_registry_rejects_unknown_step_type():
    reg = SignedRegistry(b"k", declared_step_types={"only.this"})
    raw = WF_YAML.encode()
    with pytest.raises(RegistrationError):
        reg.load_signed(raw, sign_registry_with(b"k", raw))


def test_registry_retains_last_good_on_failed_reload():
    reg = _registry()
    assert reg.get("pr-summary") is not None
    with pytest.raises(HardBlock):
        reg.load_signed(WF_YAML.encode(), "bad-sig")
    # Last-good retained.
    assert reg.get("pr-summary") is not None
