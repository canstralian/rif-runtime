from run_session import ScriptedAgent, run_session
from sandbox_exec import run_in_sandbox
from score import score_session

from rif_runtime.configuration.policies import PolicyRule
from rif_runtime.runtime import RIFRuntime


def refinement_runtime(tmp_path) -> RIFRuntime:
    """A runtime that permits the harness's own `code.refine` action.

    The default policy denies by default, so a governed consumer has to
    declare the capability it needs -- the harness is no exception. Without
    this rule every turn is blocked, `tests_passed` is None for all of them,
    and the session scores as if nothing regressed (see `score_session`).
    """
    runtime = RIFRuntime(data_dir=tmp_path)
    runtime.policy_store.upsert(
        PolicyRule(
            id="allow_eval_code_refine",
            effect="allow",
            action="code.refine",
            target="*",
            reason="MST eval harness refinement turns",
        )
    )
    return runtime


def test_score_session_no_regression():
    score = score_session("task_a", [True, True, True])
    assert score.first_regression_turn is None
    assert score.turns_passed == 3
    assert score.mst_score == 3


def test_score_session_first_regression():
    score = score_session("task_b", [True, True, False, False])
    assert score.first_regression_turn == 3
    assert score.turns_passed == 2
    assert score.mst_score == 2
    assert score.turns_attempted == 4


def test_sandbox_exec_pass_and_fail():
    code = "def add_one(x):\n    return x + 1\n"
    tests = ["assert add_one(1) == 2", "assert add_one(2) == 3"]

    passing = run_in_sandbox(code, tests)
    assert passing.passed is True

    broken = run_in_sandbox(code.replace("x + 1", "x + 2"), tests)
    assert broken.passed is False


ADD_ONE_TASK = {
    "task_id": "test_add_one",
    "language": "python",
    "prompt": "Write add_one(x) that returns x + 1.",
    "entrypoint": "add_one",
    "tests": ["assert add_one(1) == 2", "assert add_one(2) == 3"],
    "refinement_turns": [
        {"turn": 1, "instruction": "rename the parameter", "change_type": "style"},
        {"turn": 2, "instruction": "introduce a bug", "change_type": "semantic"},
        {"turn": 3, "instruction": "keep going", "change_type": "style"},
        {"turn": 4, "instruction": "keep going", "change_type": "style"},
    ],
}

CORRECT_V1 = "def add_one(x):\n    return x + 1\n"
CORRECT_V2 = "def add_one(value):\n    return value + 1\n"
BROKEN_V1 = "def add_one(value):\n    return value + 2\n"


def test_run_session_clean_solution_has_no_regression(tmp_path):
    agent = ScriptedAgent(
        name="static-correct",
        states=[CORRECT_V1, CORRECT_V2, CORRECT_V2, CORRECT_V2, CORRECT_V2],
    )
    session = run_session(ADD_ONE_TASK, agent, runtime=refinement_runtime(tmp_path))

    result = session["result"]
    assert result["turns_attempted"] == 4
    assert result["first_regression_turn"] is None
    assert result["mst_score"] == 4
    assert all(not event["regression_detected"] for event in result["events"])


def test_run_session_detects_first_regression_and_escalates_posture(tmp_path):
    agent = ScriptedAgent(
        name="static-regresses",
        states=[CORRECT_V1, CORRECT_V2, BROKEN_V1, BROKEN_V1, BROKEN_V1],
    )
    runtime = refinement_runtime(tmp_path)
    session = run_session(ADD_ONE_TASK, agent, runtime=runtime)

    result = session["result"]
    assert result["turns_attempted"] == 4
    assert result["first_regression_turn"] == 2
    assert result["mst_score"] == 1

    events = result["events"]
    assert events[0]["tests_passed"] is True
    assert events[1]["tests_passed"] is False
    assert events[1]["regression_detected"] is True
    # the regression is only the *first* one; later failing turns aren't
    # re-flagged as new regressions
    assert events[2]["regression_detected"] is False
    assert events[3]["regression_detected"] is False

    # three verification failures (turns 2-4) escalate posture, exactly
    # like any other run of denials would
    assert session["posture_start"] == "normal"
    assert session["posture_end"] == "elevated"
    assert runtime.posture == "elevated"


def test_run_session_blocks_every_turn_without_a_permitting_rule(tmp_path):
    """Under the default deny-by-default policy the harness is gated shut.

    This is the harness's contract with governance, not a quirk: `code.refine`
    has to be allowed explicitly. It is asserted so the day someone widens the
    default policy, the change is visible here rather than silently restoring
    a fallthrough the runtime no longer promises.
    """
    agent = ScriptedAgent(
        name="static-regresses",
        states=[CORRECT_V1, CORRECT_V2, BROKEN_V1, BROKEN_V1, BROKEN_V1],
    )
    session = run_session(ADD_ONE_TASK, agent, runtime=RIFRuntime(data_dir=tmp_path))

    result = session["result"]
    events = result["events"]
    assert [event["verification_status"] for event in events] == ["blocked"] * 4
    assert all(event["policy_decision"] == "deny" for event in events)
    assert all(event["tests_passed"] is None for event in events)

    # score_session counts a null as "not a regression", so a fully blocked
    # session still scores a perfect MST. The result has to say so, or a CI
    # job reads 4/4 and concludes the agent never regressed.
    assert result["mst_score"] == 4
    assert result["turns_blocked"] == 4
    assert result["score_is_meaningful"] is False


def test_a_verified_session_is_marked_meaningful(tmp_path):
    agent = ScriptedAgent(
        name="static-correct",
        states=[CORRECT_V1, CORRECT_V2, CORRECT_V2, CORRECT_V2, CORRECT_V2],
    )
    session = run_session(ADD_ONE_TASK, agent, runtime=refinement_runtime(tmp_path))

    result = session["result"]
    assert result["turns_blocked"] == 0
    assert result["score_is_meaningful"] is True


def test_the_markdown_report_marks_an_unusable_score(tmp_path):
    """A blocked session must not read as a clean run in mst_report.md.

    turns_blocked and score_is_meaningful reached the JSON when it was found
    that a policy-gated session scores a perfect MST while verifying nothing,
    but write_report rendered only the raw MST fields -- so the Markdown, which
    is what a reader actually looks at, still showed a fully blocked run as 4/4.
    """
    from run_session import write_report

    reports = tmp_path / "reports"
    reports.mkdir()
    write_report(
        [
            {
                "task_id": "blocked-task",
                "model": "scripted",
                "turns_attempted": 4,
                "turns_passed": 4,
                "turns_blocked": 4,
                "first_regression_turn": None,
                "mst_score": 1.0,
                "score_is_meaningful": False,
            },
            {
                "task_id": "clean-task",
                "model": "scripted",
                "turns_attempted": 4,
                "turns_passed": 4,
                "turns_blocked": 0,
                "first_regression_turn": None,
                "mst_score": 1.0,
                "score_is_meaningful": True,
            },
        ],
        reports,
    )

    markdown = (reports / "mst_report.md").read_text(encoding="utf-8")
    blocked, clean = (
        next(line for line in markdown.splitlines() if line.startswith(f"| {task}"))
        for task in ("blocked-task", "clean-task")
    )
    assert "INVALID" in blocked, "a fully blocked session still reads as a clean run"
    assert "INVALID" not in clean, "a verified session must not be marked invalid"
    assert "turns_blocked" in markdown
