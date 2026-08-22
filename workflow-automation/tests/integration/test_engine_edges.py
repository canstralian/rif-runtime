"""Engine edge branches: exhaustively exercise the chokepoint's refusal paths."""

from __future__ import annotations

from pydantic import BaseModel

from wfa.runner.escalation import resolved_action_hash
from wfa.shared.enums import Profile, RunOutcome, Taint
from wfa.shared.errors import HardBlock
from wfa.shared.models import EngineConfig, StepContext
from wfa.steps.base import Step, StepRegistry, StepResult

from tests.conftest import FakeGithub, make_event
from tests.security.steps_for_tests import _Empty, _EchoOut

BASE = """
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
"""


def _with_comment(
    taint="SINK", permission="issues:write", body='"${steps.summarise.output.summary}"'
):
    return (
        BASE
        + f"""  - id: comment
    uses: github.create_comment
    taint: {taint}
    permission: {permission}
    output_schema: c.json
    with:
      repo: "${{event.repo}}"
      issue_number: "${{event.pr.number}}"
      body: {body}
"""
    )


def test_dispatch_selects_matching_workflows(make_engine, fake_github):
    engine = make_engine(_with_comment())
    recs = engine.dispatch(make_event(), Profile.TRUSTED, "trusted")
    assert len(recs) == 1 and recs[0].outcome is RunOutcome.SUCCEEDED
    # A non-matching event kind selects nothing.
    assert engine.dispatch(make_event(kind="push", action=""), Profile.TRUSTED, "t") == []


def test_credential_broker_and_checkpoint_props(make_engine):
    engine = make_engine(_with_comment())
    engine.run_workflow(make_event(), "pr-summary", Profile.TRUSTED, "trusted")
    assert engine.credential_broker.reachable is True
    # SINK step wrote intent+completion, so it is not indeterminate.
    assert not engine.checkpoints.is_indeterminate(list(engine.checkpoints._runs)[0], "comment")


def test_max_steps_ceiling_aborts(make_engine):
    cfg = EngineConfig(
        max_steps_per_run=1,
        untrusted_read_permissions=["contents:read"],
        engine_actor="bot",
    )
    engine = make_engine(_with_comment(), config=cfg)
    rec = engine.run_workflow(make_event(), "pr-summary", Profile.TRUSTED, "t")
    assert rec.outcome is RunOutcome.ABORTED and rec.rule_id == "MAX_STEPS"


def test_taint_mismatch_aborts(make_engine):
    # Declare the SINK step as NEUTRAL: mismatch vs the step type's intrinsic SINK.
    engine = make_engine(_with_comment(taint="NEUTRAL"))
    rec = engine.run_workflow(make_event(), "pr-summary", Profile.TRUSTED, "t")
    assert rec.outcome is RunOutcome.ABORTED and rec.rule_id == "TAINT_MISMATCH"


def test_sink_not_permitted_under_untrusted(make_engine):
    # SINK step whose permission IS in the untrusted read allow-list => passes HB-9,
    # then blocked by the SINK-only-under-TRUSTED rule.
    engine = make_engine(_with_comment(permission="contents:read"))
    rec = engine.run_workflow(make_event(), "pr-summary", Profile.UNTRUSTED, "fork-pr")
    assert rec.outcome is RunOutcome.ABORTED and rec.rule_id == "SINK_NOT_PERMITTED"


def test_input_schema_violation_fails(make_engine):
    # issue_number bound to a non-numeric string => input model validation fails.
    engine = make_engine(
        _with_comment(body='"x"').replace(
            'issue_number: "${event.pr.number}"', 'issue_number: "${event.repo}"'
        )
    )
    rec = engine.run_workflow(make_event(), "pr-summary", Profile.TRUSTED, "t")
    assert rec.outcome is RunOutcome.FAILED and rec.rule_id == "INPUT_SCHEMA"


def test_missing_content_field_then_schema_error(make_engine):
    # Omit the required `body`; the sink-encode loop skips it, input validation fails.
    wf = (
        BASE
        + """  - id: comment
    uses: github.create_comment
    taint: SINK
    permission: issues:write
    output_schema: c.json
    with:
      repo: "${event.repo}"
      issue_number: "${event.pr.number}"
"""
    )
    engine = make_engine(wf)
    rec = engine.run_workflow(make_event(), "pr-summary", Profile.TRUSTED, "t")
    assert rec.outcome is RunOutcome.FAILED and rec.rule_id == "INPUT_SCHEMA"


def test_credential_store_unreachable_refuses(make_engine):
    from wfa.security.credentials import CredentialBroker

    from tests.conftest import MASTER_SECRET

    broker = CredentialBroker(MASTER_SECRET)
    engine = make_engine(_with_comment(), broker=broker)
    broker.set_reachable(False)
    rec = engine.run_workflow(make_event(), "pr-summary", Profile.TRUSTED, "t")
    assert rec.outcome is RunOutcome.ABORTED and rec.rule_id == "HB-4"


# ---- steps that fail inside execute (STEP_ERROR and HardBlock re-raise) -----------
class _BoomStep(Step):
    id = "test.boom"
    version = "1"
    input_model = _Empty
    output_model = _EchoOut
    taint = Taint.SOURCE

    def execute(self, args: BaseModel, ctx: StepContext) -> StepResult:
        raise ValueError("boom")


class _HardBlockStep(Step):
    id = "test.hardblock"
    version = "1"
    input_model = _Empty
    output_model = _EchoOut
    taint = Taint.SOURCE

    def execute(self, args: BaseModel, ctx: StepContext) -> StepResult:
        raise HardBlock("HB-6", "egress from within a step")


def _single_step_wf(uses: str) -> str:
    return f"""
version: "1"
id: solo
on: {{pull_request: [opened]}}
profile_required: UNTRUSTED
permissions: [contents:read]
steps:
  - id: only
    uses: {uses}
    taint: SOURCE
    permission: contents:read
    output_schema: x.json
    with: {{}}
"""


def test_step_runtime_error_fails_run(make_engine):
    reg = StepRegistry()
    reg.register(_BoomStep())
    engine = make_engine(_single_step_wf("test.boom"), registry=reg)
    rec = engine.run_workflow(make_event(), "solo", Profile.TRUSTED, "t")
    assert rec.outcome is RunOutcome.FAILED and rec.rule_id == "STEP_ERROR"


def test_step_hardblock_dead_letters_run(make_engine):
    reg = StepRegistry()
    reg.register(_HardBlockStep())
    engine = make_engine(_single_step_wf("test.hardblock"), registry=reg)
    rec = engine.run_workflow(make_event(), "solo", Profile.TRUSTED, "t")
    assert rec.outcome is RunOutcome.DEAD_LETTERED and rec.rule_id == "HB-6"


def test_escalated_merge_action_hash_uses_describe(make_engine):
    # A non-TRUSTED escalated merge step reaches _require_approval, exercising the
    # describe_action-based action hash. With a stale token it aborts.
    fake = FakeGithub()
    from wfa.steps.registry import default_registry

    reg = default_registry(merge=fake)
    wf = """
version: "1"
id: merge-wf
on: {pull_request: [opened]}
profile_required: UNTRUSTED
permissions: [contents:read]
steps:
  - id: merge
    uses: github.merge_pr
    taint: SINK
    permission: contents:read
    escalates: true
    output_schema: m.json
    with: {repo: "${event.repo}", pr_number: "${event.pr.number}"}
"""
    engine = make_engine(wf, registry=reg)
    tok = engine.escalation_broker.mint("wrong-run", "merge", resolved_action_hash("x"), now=0.0)
    rec = engine.run_workflow(
        make_event(), "merge-wf", Profile.UNTRUSTED, "fork-pr", approvals={"merge": tok}
    )
    assert rec.outcome is RunOutcome.ABORTED and rec.rule_id == "ESCALATION_REQUIRED"
    assert fake.calls == []


def test_escalated_step_under_trusted_runs_per_policy(make_engine):
    # Under TRUSTED an escalated step executes per policy (no T3 token needed).
    fake = FakeGithub()
    from wfa.steps.registry import default_registry

    reg = default_registry(merge=fake)
    wf = """
version: "1"
id: merge-wf
on: {pull_request: [opened]}
profile_required: TRUSTED
permissions: [contents:write]
credentials: [github_token]
steps:
  - id: merge
    uses: github.merge_pr
    taint: SINK
    permission: contents:write
    escalates: true
    output_schema: m.json
    with: {repo: "${event.repo}", pr_number: "${event.pr.number}"}
"""
    engine = make_engine(wf, registry=reg)
    rec = engine.run_workflow(make_event(), "merge-wf", Profile.TRUSTED, "trusted")
    assert rec.outcome is RunOutcome.SUCCEEDED
    assert fake.calls and fake.calls[0].get("merge") is True
