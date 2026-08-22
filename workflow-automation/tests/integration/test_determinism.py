"""Determinism (spec §3.3, §10, acceptance): identical inputs => identical decisions."""

from __future__ import annotations

from wfa.shared.enums import Profile

from tests.conftest import make_event

WF = """
version: "1"
id: pr-summary
on: {pull_request: [opened]}
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


def test_profile_step_sequence_and_permissions_are_byte_identical(make_engine):
    profiles = []
    sequences = []
    rules = []
    for i in range(10):
        engine = make_engine(WF)
        # Distinct delivery_id each run so idempotency doesn't short-circuit.
        ev = make_event(delivery_id=f"det-{i}")
        rec = engine.run_workflow(ev, "pr-summary", Profile.UNTRUSTED, "fork-pr")
        profiles.append(rec.profile.value)
        sequences.append(tuple(rec.step_outcomes.items()))
        rules.append(rec.rule_id)
    assert len(set(profiles)) == 1
    assert len(set(sequences)) == 1
    assert len(set(rules)) == 1


def test_trusted_sequence_stable(make_engine):
    seqs = set()
    for i in range(10):
        engine = make_engine(WF)
        rec = engine.run_workflow(
            make_event(delivery_id=f"t-{i}"), "pr-summary", Profile.TRUSTED, "b"
        )
        seqs.add(tuple(sorted(rec.step_outcomes.items())))
    assert len(seqs) == 1
