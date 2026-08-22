"""Restart semantics: persisted state must survive process reconstruction."""

import json

import pytest

from rif_runtime.config import PostureLevel, reset_settings
from rif_runtime.runtime import RIFRuntime
from rif_runtime.schemas import EnvironmentProfile, PolicyRequest, Posture


def test_locked_runtime_stays_locked_after_restart(tmp_path):
    # A locked posture denies everything, so losing it on restart silently
    # re-opens the runtime.
    first = RIFRuntime(data_dir=tmp_path)
    first.set_posture(Posture.locked)

    restarted = RIFRuntime(data_dir=tmp_path)
    assert restarted.posture == Posture.locked


def test_restart_restores_posture_from_decisions_when_no_history(tmp_path):
    # No posture_history.jsonl (e.g. a log written before transitions were
    # recorded): the decision log's denial count is the fallback source.
    log = tmp_path / "decisions.jsonl"
    row = {
        "decision": "deny",
        "actor": "agent:test",
        "action": "http.request",
        "target": "https://blocked.example.com",
        "environment": "RIF_CI",
        "posture": "normal",
        "reason": "seeded",
        "matched_rule": "network.host.denied",
    }
    log.write_text(
        "\n".join(json.dumps(row) for _ in range(20)) + "\n", encoding="utf-8"
    )

    assert RIFRuntime(data_dir=tmp_path).posture == Posture.locked


def test_restart_honours_a_reset(tmp_path):
    # An operator reset is a recorded transition, so it must win over the
    # earlier escalation rather than being replayed away.
    first = RIFRuntime(data_dir=tmp_path)
    first.set_posture(Posture.locked)
    first.set_posture(Posture.normal)

    assert RIFRuntime(data_dir=tmp_path).posture == Posture.normal


def test_data_dir_owns_every_store(tmp_path):
    runtime = RIFRuntime(data_dir=tmp_path)

    assert runtime.decisions_path == tmp_path / "decisions.jsonl"
    assert runtime.posture_store.path == tmp_path / "posture_history.jsonl"
    assert runtime.evidence_store.path == tmp_path / "metasploit_evidence.jsonl"
    assert runtime.policy_store.store.path == tmp_path / "policies.json"


# --- configured posture floor ------------------------------------------------
#
# RIF_POSTURE / rif.toml [runtime] posture used to be parsed, validated, and
# never read: RIFRuntime took its posture purely from the logs, so a runtime
# configured `locked` started up allowing everything.


@pytest.fixture()
def configured_posture(monkeypatch: pytest.MonkeyPatch):
    """Set RIF_POSTURE and rebuild the cached settings singleton."""

    def _set(value: str) -> None:
        monkeypatch.setenv("RIF_POSTURE", value)
        reset_settings()

    yield _set
    monkeypatch.delenv("RIF_POSTURE", raising=False)
    reset_settings()


def test_configured_posture_applies_on_a_fresh_runtime(tmp_path, configured_posture):
    configured_posture("locked")

    assert RIFRuntime(data_dir=tmp_path).posture == Posture.locked


def test_configured_posture_denies_traffic_a_normal_runtime_would_allow(
    tmp_path, configured_posture
):
    """The floor has to reach the decision path, not just the attribute."""
    configured_posture("locked")
    runtime = RIFRuntime(data_dir=tmp_path)
    runtime.config.environments["open_test"] = EnvironmentProfile(
        networking_type="open", allowed_hosts=[]
    )
    runtime.set_environment("open_test")

    decision = runtime.evaluate(
        PolicyRequest(
            actor="agent:test", action="http.request", target="https://example.com"
        ),
        record=False,
    )

    assert decision.decision == "deny"
    assert decision.matched_rule == "posture.locked"


def test_configured_posture_is_a_floor_not_an_assignment(tmp_path, configured_posture):
    """A runtime that escalated past the floor is not relaxed back down to it."""
    configured_posture("elevated")
    first = RIFRuntime(data_dir=tmp_path)
    first.set_posture(Posture.locked)

    assert RIFRuntime(data_dir=tmp_path).posture == Posture.locked


def test_configured_floor_survives_an_operator_reset_across_restart(
    tmp_path, configured_posture
):
    """A reset relaxes the running process; it cannot lower the configured floor.

    Restarting re-reads configuration, so an operator who wants the reset to
    persist has to change the configured posture too. Documented in
    docs/API.md so the asymmetry is not a surprise.
    """
    configured_posture("restricted")
    first = RIFRuntime(data_dir=tmp_path)
    first.set_posture(Posture.normal)
    assert first.posture == Posture.normal

    assert RIFRuntime(data_dir=tmp_path).posture == Posture.restricted


def test_default_configuration_leaves_restore_behaviour_unchanged(tmp_path):
    """With no RIF_POSTURE set the floor is `normal`, i.e. a no-op."""
    first = RIFRuntime(data_dir=tmp_path)
    first.set_posture(Posture.locked)
    first.set_posture(Posture.normal)

    assert RIFRuntime(data_dir=tmp_path).posture == Posture.normal


def test_posture_level_is_the_runtime_posture_enum():
    """config.PostureLevel and schemas.Posture are one type, not two.

    They were separate identical StrEnums, which let configuration and runtime
    drift apart while looking interchangeable.
    """
    assert PostureLevel is Posture
