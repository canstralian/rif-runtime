"""Tests for governance.drift.

All adversarial-pattern inputs are explicit string literals — no tests/ directory
sweep is performed, which avoids accidental false-positives from SQL/shell
keywords that legitimately appear in test source code.
"""

import math
from datetime import UTC, datetime

import pytest

from rif_runtime.agents.orchestrator import OrchestratorAgent
from rif_runtime.governance.drift import (
    _ADVERSARIAL_PATTERNS,
    DriftVector,
    _adversarial_score,
    _entropy,
    recommend_correction,
)
from rif_runtime.schemas import Decision, PolicyDecision, Posture

# ── helpers ─────────────────────────────────────────────────────────────────


def _decision(
    target: str = "https://api.example.com",
    action: str = "http.request",
    decision: Decision = Decision.allow,
    reason: str = "allowed by constraints",
) -> PolicyDecision:
    return PolicyDecision(
        decision=decision,
        actor="agent:test",
        action=action,
        target=target,
        environment="RIF_CI",
        posture=Posture.normal,
        reason=reason,
        matched_rule="default.allow",
        timestamp=datetime.now(UTC),
    )


# ── _entropy ─────────────────────────────────────────────────────────────────


def test_entropy_empty_returns_zero():
    assert _entropy([]) == 0.0


def test_entropy_single_unique_value_is_zero():
    assert _entropy(["x", "x", "x"]) == 0.0


def test_entropy_two_equally_probable_values():
    assert abs(_entropy(["a", "b"]) - math.log(2)) < 1e-9


def test_entropy_grows_with_diversity():
    h2 = _entropy(["a", "b"])
    h4 = _entropy(["a", "b", "c", "d"])
    assert h4 > h2


# ── _ADVERSARIAL_PATTERNS word-boundary anchoring ────────────────────────────


@pytest.mark.parametrize(
    "safe",
    [
        # 'select' embedded in a longer word — no boundary after 'select'
        "elasticsearch",
        "executor.run()",  # 'exec' is a prefix; 'u' immediately follows
        "selectAll(items)",  # camelCase prefix — no boundary after 'select'
    ],
)
def test_adversarial_patterns_no_false_positive(safe: str):
    assert not any(p.search(safe) for p in _ADVERSARIAL_PATTERNS), (
        f"false positive on: {safe!r}"
    )


@pytest.mark.parametrize(
    "payload",
    [
        "SELECT * FROM users",
        "1; DROP TABLE students",
        "cmd.exe /c whoami",
        "../../etc/passwd",
        "../segment/../etc/passwd",  # non-consecutive traversal
        "<script>alert(1)</script>",
        "1 | cat /etc/shadow",
        "EXEC xp_cmdshell('whoami')",
        "1 UNION SELECT null,null",
    ],
)
def test_adversarial_patterns_detects_payloads(payload: str):
    assert any(p.search(payload) for p in _ADVERSARIAL_PATTERNS), (
        f"missed payload: {payload!r}"
    )


# shell chaining operators: ; and | are explicitly restored
def test_semicolon_pattern_fires():
    assert any(p.search("cmd; ls -la") for p in _ADVERSARIAL_PATTERNS)


def test_pipe_pattern_fires():
    assert any(p.search("fetch | cat /etc/passwd") for p in _ADVERSARIAL_PATTERNS)


def test_backtick_pattern_fires():
    assert any(p.search("value`whoami`") for p in _ADVERSARIAL_PATTERNS)


# ── _adversarial_score ───────────────────────────────────────────────────────


def test_adversarial_score_empty():
    assert _adversarial_score([]) == 0.0


def test_adversarial_score_all_clean():
    events = [_decision(target="https://api.anthropic.com") for _ in range(5)]
    assert _adversarial_score(events) == 0.0


def test_adversarial_score_sql_in_target():
    events = [_decision(target="https://db.internal/q?x=1 UNION SELECT 1,2")]
    assert _adversarial_score(events) == 1.0


def test_adversarial_score_shell_pipe_in_target_query():
    events = [_decision(target="https://host/run?cmd=fetch | cat /etc/passwd")]
    assert _adversarial_score(events) == 1.0


def test_adversarial_score_semicolon_in_target():
    events = [_decision(target="https://host/path; ls -la")]
    assert _adversarial_score(events) == 1.0


def test_adversarial_score_partial_mix():
    clean = _decision(target="https://api.anthropic.com")
    dirty = _decision(target="https://host/?id=1 DROP TABLE users")
    assert _adversarial_score([clean, dirty]) == 0.5


def test_adversarial_score_semicolon_query_param_no_false_positive():
    # ?a=1;b=2 uses ; as a parameter separator with no whitespace — must not fire
    events = [_decision(target="https://api.service.io/items?page=1;limit=10")]
    assert _adversarial_score(events) == 0.0


def test_adversarial_score_matrix_param_no_false_positive():
    # RFC 1808 matrix params like ;version=1 are rejoined by _extract_payload
    # with no whitespace after ';' — must not be scored as shell chaining.
    events = [_decision(target="https://api.service.io/resource;version=1")]
    assert _adversarial_score(events) == 0.0


def test_adversarial_score_semicolon_separators_do_not_escalate_correction():
    # Benign ;-separated query/matrix traffic must keep adversarial_score at 0
    # so recommend_correction is driven only by denial/entropy signals.
    events = [
        _decision(target="https://api.service.io/items?a=1;b=2"),
        _decision(target="https://api.service.io/path;version=1"),
        _decision(target="https://api.service.io/path;version=1?a=1;b=2"),
    ]
    vector = DriftVector.from_events(events)
    assert vector.adversarial_score == 0.0
    assert recommend_correction(vector) == Posture.normal


def test_adversarial_score_encoded_sql_in_target():
    # Percent-encoded SELECT must be decoded before matching
    events = [_decision(target="https://db.internal/q?x=%53ELECT%20*%20FROM%20users")]
    assert _adversarial_score(events) == 1.0


# ── DriftVector.from_events ──────────────────────────────────────────────────


def test_drift_vector_empty():
    assert DriftVector.from_events([]) == DriftVector(0.0, 0.0, 0.0, 0.0)


def test_drift_vector_all_allowed():
    v = DriftVector.from_events([_decision() for _ in range(4)])
    assert v.denial_rate == 0.0
    assert v.adversarial_score == 0.0


def test_drift_vector_denial_rate():
    events = [
        _decision(decision=Decision.deny),
        _decision(decision=Decision.deny),
        _decision(),
        _decision(),
    ]
    assert DriftVector.from_events(events).denial_rate == 0.5


def test_drift_vector_single_target_zero_entropy():
    events = [
        _decision(target="https://blocked.example.com", decision=Decision.deny)
        for _ in range(5)
    ]
    v = DriftVector.from_events(events)
    assert v.target_entropy == 0.0
    assert v.denial_rate == 1.0


def test_drift_vector_action_entropy_grows():
    same = [_decision(action="http.request") for _ in range(4)]
    mixed = [
        _decision(action="http.request"),
        _decision(action="mcp.invoke"),
        _decision(action="package.install"),
        _decision(action="api.call"),
    ]
    assert (
        DriftVector.from_events(same).action_entropy
        < DriftVector.from_events(mixed).action_entropy
    )


# ── recommend_correction ─────────────────────────────────────────────────────


def test_recommend_normal_on_clean():
    v = DriftVector(
        denial_rate=0.0, adversarial_score=0.0, action_entropy=1.0, target_entropy=1.0
    )
    assert recommend_correction(v) == Posture.normal


def test_recommend_elevated_at_moderate_denial():
    v = DriftVector(
        denial_rate=0.25, adversarial_score=0.0, action_entropy=1.0, target_entropy=1.0
    )
    assert recommend_correction(v) == Posture.elevated


def test_recommend_restricted_at_high_denial():
    v = DriftVector(
        denial_rate=0.6, adversarial_score=0.0, action_entropy=1.0, target_entropy=1.0
    )
    assert recommend_correction(v) == Posture.restricted


def test_recommend_locked_at_very_high_denial():
    v = DriftVector(
        denial_rate=0.9, adversarial_score=0.0, action_entropy=1.0, target_entropy=1.0
    )
    assert recommend_correction(v) == Posture.locked


def test_recommend_locked_on_heavy_adversarial():
    v = DriftVector(
        denial_rate=0.1, adversarial_score=0.5, action_entropy=1.0, target_entropy=1.0
    )
    assert recommend_correction(v) == Posture.locked


def test_recommend_restricted_on_light_adversarial():
    v = DriftVector(
        denial_rate=0.1, adversarial_score=0.15, action_entropy=1.0, target_entropy=1.0
    )
    assert recommend_correction(v) == Posture.restricted


def test_recommend_restricted_on_focused_probe():
    # Low target entropy + elevated denials without adversarial content = hammering
    # a single blocked target (entropy-based detector)
    v = DriftVector(
        denial_rate=0.4, adversarial_score=0.0, action_entropy=1.0, target_entropy=0.2
    )
    assert recommend_correction(v) == Posture.restricted


def test_recommend_elevated_not_triggered_without_denial():
    v = DriftVector(
        denial_rate=0.05, adversarial_score=0.0, action_entropy=0.0, target_entropy=0.0
    )
    assert recommend_correction(v) == Posture.normal


# ── OrchestratorAgent integration ────────────────────────────────────────────


def test_orchestrator_choose_correction_locked():
    agent = OrchestratorAgent()
    v = DriftVector(
        denial_rate=0.9, adversarial_score=0.0, action_entropy=0.0, target_entropy=0.0
    )
    assert agent.choose_correction(v) == Posture.locked
    assert agent._choose_correction(v) == Posture.locked


def test_orchestrator_choose_correction_normal():
    agent = OrchestratorAgent()
    v = DriftVector(
        denial_rate=0.0, adversarial_score=0.0, action_entropy=1.0, target_entropy=1.0
    )
    assert agent.choose_correction(v) == Posture.normal


def test_orchestrator_choose_correction_delegates_to_recommend():
    """_choose_correction has no parallel thresholds; it calls recommend_correction."""
    agent = OrchestratorAgent()
    vectors = [
        DriftVector(0.0, 0.0, 1.0, 1.0),
        DriftVector(0.25, 0.0, 1.0, 1.0),
        DriftVector(0.6, 0.0, 1.0, 1.0),
        DriftVector(0.9, 0.0, 1.0, 1.0),
        DriftVector(0.1, 0.5, 1.0, 1.0),
    ]
    for v in vectors:
        assert agent.choose_correction(v) == recommend_correction(v)
