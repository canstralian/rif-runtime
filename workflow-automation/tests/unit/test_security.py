"""Security primitives: credentials, redactor, encoders, egress, audit (spec §4)."""

from __future__ import annotations

import pytest

from wfa.security.audit import AuditLog
from wfa.security.credentials import CredentialBroker, DeniedCredentials
from wfa.security.egress import EgressGuard
from wfa.security.encode import encode_for_sink
from wfa.security.redactor import Redactor
from wfa.shared.enums import Profile
from wfa.shared.errors import HardBlock

MASTER = b"master-secret"


# --------------------------------------------------------------------- credentials
def test_untrusted_gets_denied_resolver():
    broker = CredentialBroker(MASTER)
    broker.register("wf", "github_token", "ghp_secret")
    resolver = broker.resolver_for("wf", Profile.UNTRUSTED, frozenset({"github_token"}))
    assert isinstance(resolver, DeniedCredentials)
    with pytest.raises(HardBlock) as e:
        resolver.get("github_token")
    assert e.value.rule_id == "HB-4"


def test_trusted_resolver_returns_scoped_credential():
    broker = CredentialBroker(MASTER)
    broker.register("wf", "github_token", "ghp_secret")
    resolver = broker.resolver_for("wf", Profile.TRUSTED, frozenset({"github_token"}))
    assert resolver.get("github_token") == "ghp_secret"


def test_credential_out_of_scope_blocked():
    broker = CredentialBroker(MASTER)
    broker.register("wf", "github_token", "ghp_secret")
    resolver = broker.resolver_for("wf", Profile.TRUSTED, frozenset())
    with pytest.raises(HardBlock):
        resolver.get("github_token")


def test_undeclared_credential_blocked():
    broker = CredentialBroker(MASTER)
    resolver = broker.resolver_for("wf", Profile.TRUSTED, frozenset({"missing"}))
    with pytest.raises(HardBlock):
        resolver.get("missing")


def test_credential_store_unreachable_refuses():
    broker = CredentialBroker(MASTER)
    broker.register("wf", "t", "v")
    broker.set_reachable(False)
    resolver = broker.resolver_for("wf", Profile.TRUSTED, frozenset({"t"}))
    with pytest.raises(HardBlock):
        resolver.get("t")


# ----------------------------------------------------------------------- redactor
def test_redactor_masks_github_token():
    r = Redactor()
    out = r.scrub({"body": "here is ghp_" + "A" * 36})
    assert "ghp_" not in out["body"]
    assert r.redactions_applied >= 1


def test_redactor_masks_high_entropy_string():
    r = Redactor()
    secret = "A1b2C3d4E5f6G7h8I9j0KlMnOpQrStUvWxYz"  # 36 distinct chars, entropy > 4
    out = r.scrub(secret)
    assert out == "***REDACTED***"


def test_redactor_recurses_containers():
    r = Redactor()
    out = r.scrub({"a": ["ghp_" + "B" * 36, {"b": "password: hunter2xxxxxxx"}], "n": 5})
    assert out["n"] == 5
    assert "ghp_" not in out["a"][0]


def test_redactor_leaves_short_low_entropy_text():
    r = Redactor()
    assert r.scrub("hello world") == "hello world"


# ----------------------------------------------------------------------- encoders
def test_slack_strips_broadcast_for_untrusted():
    out = encode_for_sink("slack", "hey @channel look", Profile.UNTRUSTED)
    assert "@channel" not in out


def test_slack_keeps_broadcast_for_trusted():
    out = encode_for_sink("slack", "deploy done @here", Profile.TRUSTED)
    assert "here" in out


def test_slack_escapes_markup_and_mentions():
    out = encode_for_sink("slack", "<@U123> <b>hi</b> & bye", Profile.UNTRUSTED)
    assert "<@U123>" not in out
    assert "&amp;" in out


def test_github_neutralises_mentions_for_untrusted():
    out = encode_for_sink("github", "ping @maintainer <script>", Profile.UNTRUSTED)
    assert "@\u200bmaintainer" in out
    assert "&lt;script&gt;" in out


def test_jira_escapes_markup():
    out = encode_for_sink("jira", "[~admin] {code}x{code}", Profile.UNTRUSTED)
    assert "[~admin]" not in out
    assert "\\{code\\}" in out


def test_unknown_sink_fails_closed():
    with pytest.raises(ValueError):
        encode_for_sink("pagerduty", "x", Profile.TRUSTED)


# ------------------------------------------------------------------------- egress
def test_egress_allows_listed_host():
    g = EgressGuard(["api.github.com"])
    assert g.check("https://api.github.com/repos") == "api.github.com"
    assert g.allows("https://api.github.com/x")


def test_egress_blocks_unlisted_host():
    g = EgressGuard(["api.github.com"])
    with pytest.raises(HardBlock) as e:
        g.check("https://evil.example.com/x")
    assert e.value.rule_id == "HB-6"


def test_egress_blocks_metadata_service():
    g = EgressGuard(["169.254.169.254"])  # even if allow-listed, link-local is blocked
    assert not g.allows("http://169.254.169.254/latest/meta-data/")


def test_egress_blocks_private_and_loopback():
    g = EgressGuard(["10.0.0.5", "127.0.0.1"])
    assert not g.allows("http://10.0.0.5/")
    assert not g.allows("http://127.0.0.1/")


def test_egress_blocks_missing_host():
    g = EgressGuard(["x"])
    assert not g.allows("not-a-url")


# -------------------------------------------------------------------------- audit
def test_audit_chain_verifies(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    log.append({"run_id": "r1", "outcome": "succeeded"})
    log.append({"run_id": "r2", "outcome": "failed"})
    assert log.verify()


def test_audit_chain_detects_tamper(tmp_path):
    path = tmp_path / "a.jsonl"
    log = AuditLog(path)
    log.append({"run_id": "r1", "outcome": "succeeded"})
    log.append({"run_id": "r2", "outcome": "failed"})
    lines = path.read_text().splitlines()
    lines[0] = lines[0].replace("succeeded", "tampered")
    path.write_text("\n".join(lines) + "\n")
    assert not log.verify()


def test_audit_tail_recovery(tmp_path):
    path = tmp_path / "a.jsonl"
    log = AuditLog(path)
    h1 = log.append({"run_id": "r1"})
    reopened = AuditLog(path)
    assert reopened.tail_hash == h1
    reopened.append({"run_id": "r2"})
    assert reopened.verify()


def test_audit_payload_digest_is_salted_hash(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    d = log.payload_digest(b"customer data")
    assert len(d) == 64 and d != "customer data"


def test_audit_empty_verifies(tmp_path):
    assert AuditLog(tmp_path / "none.jsonl").verify()
