"""Drive one task through governed multi-turn refinement and score it.

Circuit: task -> generation -> refinement -> test -> regression detection ->
audit event -> report. Each refinement turn is gated through
`RIFRuntime.evaluate()` (an auditable policy decision) before the agent is
asked to refine the code, and a failed verification is itself recorded as a
governed denial via `RIFRuntime.record_decision()` so regressions can drive
posture escalation exactly like any other denial.

This module intentionally does not embed a live model client. Real model
integrations implement the `CodeAgent` interface and are loaded via
`--agent module:ClassName`. `ScriptedAgent` exists to exercise the circuit
deterministically (see tests/test_code_refinement_mst.py).
"""

from __future__ import annotations

import abc
import argparse
import importlib
import json
import sys
from pathlib import Path

from sandbox_exec import run_in_sandbox
from score import score_session

from rif_runtime.audit import utc_now_iso
from rif_runtime.runtime import RIFRuntime
from rif_runtime.schemas import Decision, PolicyDecision, PolicyRequest
from rif_runtime.security import sha256_digest


def _enum_value(value: object) -> object:
    return value.value if hasattr(value, "value") else value


class CodeAgent(abc.ABC):
    """Anything that can produce and refine a candidate solution."""

    name: str

    @abc.abstractmethod
    def generate_initial(self, prompt: str, entrypoint: str) -> str:
        """Produce the first candidate implementation for a task."""

    @abc.abstractmethod
    def refine(self, code: str, instruction: str, change_type: str) -> str:
        """Produce the next candidate implementation given an instruction."""


class ScriptedAgent(CodeAgent):
    """Deterministic agent driven by a fixed script of code states.

    `states[0]` is the initial solution; `states[i]` is the candidate
    returned after refinement turn `i`. Exists to exercise the governed
    refinement circuit without a live model integration.
    """

    def __init__(self, name: str, states: list[str]):
        if not states:
            raise ValueError("ScriptedAgent needs at least an initial state")
        self.name = name
        self._states = states
        self._turn = 0

    def generate_initial(self, prompt: str, entrypoint: str) -> str:
        self._turn = 0
        return self._states[0]

    def refine(self, code: str, instruction: str, change_type: str) -> str:
        self._turn += 1
        if self._turn >= len(self._states):
            return code
        return self._states[self._turn]


def run_session(
    task: dict,
    agent: CodeAgent,
    runtime: RIFRuntime | None = None,
    actor: str | None = None,
) -> dict:
    runtime = runtime or RIFRuntime()
    actor_name = actor or f"agent:eval:{agent.name}"
    task_id = task["task_id"]
    tests = task["tests"]

    started_at = utc_now_iso()
    posture_start = _enum_value(runtime.posture)

    code = agent.generate_initial(task["prompt"], task["entrypoint"])
    events: list[dict] = []
    still_correct = True

    for turn_spec in task["refinement_turns"]:
        turn = turn_spec["turn"]
        instruction = turn_spec["instruction"]
        change_type = turn_spec["change_type"]

        gate_decision = runtime.evaluate(
            PolicyRequest(
                actor=actor_name,
                action="code.refine",
                target=f"task:{task_id}",
                reason=instruction,
                context={"turn": turn, "change_type": change_type},
            )
        )

        state_hash_before = sha256_digest(code)

        if gate_decision.decision == Decision.deny:
            state_hash_after = state_hash_before
            tests_passed = None
            verification_status = "blocked"
            policy_decision = gate_decision.decision
        else:
            code = agent.refine(code, instruction, change_type)
            state_hash_after = sha256_digest(code)
            sandbox_result = run_in_sandbox(code, tests)
            tests_passed = sandbox_result.passed
            policy_decision = gate_decision.decision

            if tests_passed:
                verification_status = "passed"
            else:
                verification_status = "error" if sandbox_result.timed_out else "failed"
                verification_decision = runtime.record_decision(
                    PolicyDecision(
                        decision=Decision.deny,
                        actor=actor_name,
                        action="code.verify",
                        target=f"task:{task_id}",
                        environment=runtime.environment_name,
                        posture=runtime.posture,
                        reason=f"test suite failed after turn {turn}",
                        matched_rule="verification.regression_detected",
                    )
                )
                policy_decision = verification_decision.decision

        regression_detected = still_correct and (tests_passed is False)
        still_correct = still_correct and (tests_passed is not False)

        events.append(
            {
                "event_type": "code_refinement_turn",
                "task_id": task_id,
                "turn": turn,
                "change_type": change_type,
                "state_hash_before": state_hash_before,
                "state_hash_after": state_hash_after,
                "tests_passed": tests_passed,
                "policy_decision": _enum_value(policy_decision),
                "verification_status": verification_status,
                "regression_detected": regression_detected,
            }
        )

    turn_results = [event["tests_passed"] for event in events]
    score = score_session(task_id, turn_results)

    # A blocked turn records tests_passed=None, and score_session treats a null
    # as "not a regression" -- so a session the policy gated shut scores a
    # *perfect* MST while verifying nothing. Carry the count next to the score
    # rather than leaving the caller to notice, and mark the score unusable when
    # no turn was actually verified.
    turns_blocked = sum(1 for event in events if event["tests_passed"] is None)

    result = {
        "task_id": task_id,
        "model": agent.name,
        "turns_attempted": score.turns_attempted,
        "turns_passed": score.turns_passed,
        "turns_blocked": turns_blocked,
        "first_regression_turn": score.first_regression_turn,
        "mst_score": score.mst_score,
        "score_is_meaningful": turns_blocked < score.turns_attempted,
        "events": events,
    }

    return {
        "task_id": task_id,
        "model": agent.name,
        "actor": actor_name,
        "environment": runtime.environment_name,
        "started_at": started_at,
        "completed_at": utc_now_iso(),
        "posture_start": posture_start,
        "posture_end": _enum_value(runtime.posture),
        "events": events,
        "result": result,
    }


def _eval_root() -> Path:
    return Path(__file__).resolve().parent.parent


def write_session(session: dict, sessions_dir: Path | None = None) -> Path:
    sessions_dir = sessions_dir or (_eval_root() / "sessions" / "generated")
    sessions_dir.mkdir(parents=True, exist_ok=True)
    safe_timestamp = session["completed_at"].replace(":", "").replace("+00:00", "Z")
    path = (
        sessions_dir
        / f"{session['task_id']}__{session['model']}__{safe_timestamp}.json"
    )
    path.write_text(json.dumps(session, indent=2, sort_keys=True), encoding="utf-8")
    return path


def write_report(
    results: list[dict], reports_dir: Path | None = None
) -> tuple[Path, Path]:
    reports_dir = reports_dir or (_eval_root() / "reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    json_path = reports_dir / "mst_report.json"
    existing = (
        json.loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else []
    )
    merged = {(row["task_id"], row["model"]): row for row in existing}
    for row in results:
        merged[(row["task_id"], row["model"])] = row
    combined = sorted(merged.values(), key=lambda row: (row["task_id"], row["model"]))
    json_path.write_text(
        json.dumps(combined, indent=2, sort_keys=True), encoding="utf-8"
    )

    md_lines = [
        "# MST-RIF Report",
        "",
        "| task_id | model | turns_attempted | turns_passed | turns_blocked |"
        " first_regression_turn | mst_score |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in combined:
        # A blocked turn verifies nothing, so a session policy gated shut scores
        # a perfect MST. The JSON has carried turns_blocked and
        # score_is_meaningful since that was found; without them here the
        # Markdown still showed a fully blocked run as a clean 4/4. Rows merged
        # from an older report may predate both keys, hence the defaults.
        blocked = row.get("turns_blocked", 0)
        meaningful = row.get("score_is_meaningful", True)
        score = row["mst_score"] if meaningful else f"{row['mst_score']} (INVALID)"
        md_lines.append(
            f"| {row['task_id']} | {row['model']} | {row['turns_attempted']} |"
            f" {row['turns_passed']} | {blocked} |"
            f" {row['first_regression_turn']} | {score} |"
        )
    if any(not row.get("score_is_meaningful", True) for row in combined):
        md_lines += [
            "",
            "> **INVALID**: every turn in that session was blocked by policy, so"
            " nothing was verified and the score measures nothing.",
        ]
    md_path = reports_dir / "mst_report.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    return json_path, md_path


def _load_agent(spec: str) -> CodeAgent:
    module_name, separator, class_name = spec.partition(":")
    if not separator:
        raise ValueError("agent spec must be 'module:ClassName'")
    agent_cls = getattr(importlib.import_module(module_name), class_name)
    return agent_cls()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run an MST-RIF governed code refinement session."
    )
    parser.add_argument("task", type=Path, help="Path to a task JSON file")
    parser.add_argument(
        "--agent",
        required=True,
        help="Dotted 'module:ClassName' implementing CodeAgent",
    )
    args = parser.parse_args(argv)

    task = json.loads(args.task.read_text(encoding="utf-8"))
    agent = _load_agent(args.agent)

    session = run_session(task, agent)
    session_path = write_session(session)
    write_report([session["result"]])

    result = session["result"]
    print(f"mst_score={result['mst_score']} session={session_path}")
    if not result["score_is_meaningful"]:
        # Every turn was gated shut, so nothing was verified and the score
        # above is an artefact of blocked turns counting as non-regressions.
        print(
            f"WARNING: all {result['turns_attempted']} turn(s) were blocked by "
            "policy; no candidate was verified and mst_score is meaningless. "
            "The runtime needs a rule allowing action 'code.refine' -- see "
            "'Required policy' in the eval README.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
