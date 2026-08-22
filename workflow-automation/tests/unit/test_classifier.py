"""Provenance classification and idempotency (spec §2.1, §3.3)."""

from __future__ import annotations

from wfa.classifier.idempotency import IdempotencyStore, run_id
from wfa.classifier.provenance import Classifier
from wfa.shared.enums import Profile
from wfa.shared.models import ProvenanceFacts

from tests.conftest import FakePlatform, make_event


def classify(facts: ProvenanceFacts, **event_kw):
    return Classifier(FakePlatform(facts)).classify(make_event(**event_kw))


def test_scheduled_is_trusted():
    p, basis = classify(
        ProvenanceFacts(installation_verified=True, scheduled=True), kind="schedule"
    )
    assert p is Profile.TRUSTED and basis == "scheduled-trigger"


def test_internal_authenticated_is_trusted():
    p, _ = classify(
        ProvenanceFacts(installation_verified=True, authenticated_internal=True),
        kind="deployment",
    )
    assert p is Profile.TRUSTED


def test_push_to_protected_branch_is_trusted():
    p, basis = classify(
        ProvenanceFacts(installation_verified=True, ref_protected=True), kind="push"
    )
    assert p is Profile.TRUSTED and basis == "push-to-protected-branch"


def test_same_repo_pr_by_write_actor_is_trusted():
    p, basis = classify(
        ProvenanceFacts(installation_verified=True, actor_has_write=True, is_fork_pr=False),
        kind="pull_request",
    )
    assert p is Profile.TRUSTED and basis == "same-repo-pr-by-write-actor"


def test_fork_pr_is_untrusted():
    p, basis = classify(
        ProvenanceFacts(installation_verified=True, is_fork_pr=True), kind="pull_request"
    )
    assert p is Profile.UNTRUSTED and basis == "fork-pr"


def test_issue_comment_is_untrusted():
    p, basis = classify(
        ProvenanceFacts(installation_verified=True), kind="issue_comment", action="created"
    )
    assert p is Profile.UNTRUSTED and basis == "issue-or-comment"


def test_pr_without_write_is_untrusted():
    p, basis = classify(
        ProvenanceFacts(installation_verified=True, actor_has_write=False, is_fork_pr=False),
        kind="pull_request",
    )
    assert p is Profile.UNTRUSTED and basis == "pr-actor-without-write"


def test_unclassifiable_defaults_untrusted():
    p, basis = classify(ProvenanceFacts(installation_verified=True), kind="mystery")
    assert p is Profile.UNTRUSTED and basis == "not-positively-classifiable"


def test_unverified_installation_is_untrusted():
    p, basis = classify(
        ProvenanceFacts(installation_verified=False, ref_protected=True), kind="push"
    )
    assert p is Profile.UNTRUSTED and basis == "installation-unverified"


def test_platform_unreachable_fails_closed():
    plat = FakePlatform(ProvenanceFacts(installation_verified=True, ref_protected=True))
    plat.raise_error = True
    p, basis = Classifier(plat).classify(make_event(kind="push"))
    assert p is Profile.UNTRUSTED and "fail-closed" in basis


def test_self_asserted_author_association_is_ignored():
    # A payload claiming MEMBER but with fork facts stays UNTRUSTED (spec §2.1, vector D).
    p, _ = classify(
        ProvenanceFacts(installation_verified=True, is_fork_pr=True, actor_has_write=False),
        kind="pull_request",
        payload={"author_association": "MEMBER", "pr": {"number": 1}},
    )
    assert p is Profile.UNTRUSTED


def test_run_id_is_deterministic_and_field_sensitive():
    a = run_id("d1", "wf", "1")
    assert a == run_id("d1", "wf", "1")
    assert a != run_id("d2", "wf", "1")
    assert a != run_id("d1", "wf", "2")


def test_idempotency_store_dedup():
    store = IdempotencyStore()
    assert not store.seen("x")
    assert store.existing("x") is None
