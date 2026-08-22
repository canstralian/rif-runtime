"""End-to-end runner behaviour through the enforcement chokepoint (spec §8.4)."""

from __future__ import annotations

from wfa.shared.enums import Profile, RunOutcome

from tests.conftest import make_event

PR_SUMMARY = """
version: "1"
id: pr-summary
on:
  pull_request: [opened, synchronize]
profile_required: UNTRUSTED
permissions: [contents:read, issues:write]
credentials: [github_token]
steps:
  - id: summarise
    uses: llm.summarise
    taint: SOURCE
    permission: contents:read
    output_schema: s.json
    with: {content: "${event.pr.diff}"}
  - id: comment
    uses: github.create_comment
    taint: SINK
    permission: issues:write
    output_schema: c.json
    with:
      repo: "${event.repo}"
      issue_number: "${event.pr.number}"
      body: "${steps.summarise.output.summary}"
"""


def test_trusted_run_executes_all_steps(make_engine, fake_github):
    engine = make_engine(PR_SUMMARY)
    event = make_event()
    rec = engine.run_workflow(event, "pr-summary", Profile.TRUSTED, "same-repo-pr-by-write-actor")
    assert rec.outcome is RunOutcome.SUCCEEDED
    assert rec.step_outcomes == {"summarise": "succeeded", "comment": "succeeded"}
    assert len(fake_github.calls) == 1
    assert fake_github.calls[0]["repo"] == "octo/repo"
    assert fake_github.calls[0]["issue_number"] == 7
    assert rec.non_deterministic is True  # LLM step labels the run non-deterministic


def test_untrusted_run_blocks_sink_step(make_engine, fake_github):
    engine = make_engine(PR_SUMMARY)
    event = make_event()
    rec = engine.run_workflow(event, "pr-summary", Profile.UNTRUSTED, "fork-pr")
    # summarise (SOURCE, contents:read) runs; comment (issues:write) is not in the
    # UNTRUSTED read allow-list => HB-9, run aborts, github never called.
    assert rec.outcome is RunOutcome.ABORTED
    assert rec.rule_id == "HB-9"
    assert rec.step_outcomes["summarise"] == "succeeded"
    assert fake_github.calls == []


def test_profile_mismatch_does_not_execute(make_engine):
    wf = PR_SUMMARY.replace("profile_required: UNTRUSTED", "profile_required: TRUSTED")
    engine = make_engine(wf)
    rec = engine.run_workflow(make_event(), "pr-summary", Profile.UNTRUSTED, "fork-pr")
    assert rec.outcome is RunOutcome.FAILED
    assert rec.rule_id == "PROFILE_MISMATCH"
    assert rec.step_outcomes == {}


def test_redelivery_produces_exactly_one_run(make_engine, fake_github):
    engine = make_engine(PR_SUMMARY)
    event = make_event(delivery_id="dup-1")
    r1 = engine.run_workflow(event, "pr-summary", Profile.TRUSTED, "b")
    r2 = engine.run_workflow(event, "pr-summary", Profile.TRUSTED, "b")
    assert r1.run_id == r2.run_id
    assert len(fake_github.calls) == 1  # second call returned the cached record


def test_chain_depth_exceeded_dead_letters(make_engine):
    engine = make_engine(PR_SUMMARY)
    rec = engine.run_workflow(make_event(), "pr-summary", Profile.TRUSTED, "b", chain_depth=99)
    assert rec.outcome is RunOutcome.DEAD_LETTERED
    assert rec.rule_id == "HB-7"


def test_head_ref_workflow_source_rejected(make_engine):
    engine = make_engine(PR_SUMMARY)
    # The resolver only ever consults the protected ref; simulate an attempt to run a
    # definition from the head ref by calling the resolver directly.
    import pytest

    from wfa.shared.errors import HardBlock

    with pytest.raises(HardBlock) as e:
        engine._resolver.resolve("pr-summary", "refs/pull/9/head")
    assert e.value.rule_id == "HB-3"


def test_audit_records_classification_basis(make_engine):
    engine = make_engine(PR_SUMMARY)
    engine.run_workflow(make_event(), "pr-summary", Profile.TRUSTED, "why-trusted")
    assert engine.audit_log.verify()
    text = (engine.audit_log._path).read_text()
    assert "why-trusted" in text
    assert "provenance_profile" in text


def test_sink_body_is_encoded_before_emit(make_engine, fake_github):
    # A summary containing GitHub markup should be HTML-escaped at the sink boundary.
    def evil_model(content: str) -> str:
        return "<script>alert(1)</script> @maintainer"

    from wfa.steps.registry import default_registry

    reg = default_registry(github=fake_github, llm_model=evil_model)
    engine = make_engine(PR_SUMMARY, registry=reg)
    engine.run_workflow(make_event(), "pr-summary", Profile.TRUSTED, "b")
    body = fake_github.calls[0]["body"]
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
