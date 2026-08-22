"""Operator console (T3) and health/readiness reporting (spec §4.9, §5.2)."""

from __future__ import annotations

from wfa.console.operator import OperatorConsole
from wfa.observability.health import readiness
from wfa.runner.escalation import EscalationBroker, resolved_action_hash
from wfa.shared.enums import DegradationMode


def test_console_pause_resume_kill():
    console = OperatorConsole(EscalationBroker(b"k"))
    assert console.mode is DegradationMode.FULL
    console.pause()
    assert console.mode is DegradationMode.DRAIN
    console.resume()
    assert console.mode is DegradationMode.FULL
    console.kill("run-1")
    assert console.is_killed("run-1")
    assert not console.is_killed("run-2")


def test_console_approval_mints_verifiable_token():
    broker = EscalationBroker(b"k", ttl_s=600)
    console = OperatorConsole(broker)
    tok = console.approve_step("run-1", "deploy", "deploy prod v2", now=0.0)
    # The minted token verifies for the exact run/step/action it was approved for.
    broker.verify_and_consume(
        tok, "run-1", "deploy", resolved_action_hash("deploy prod v2"), now=10.0
    )


def test_readiness_full():
    r = readiness(
        registry_signature_ok=True,
        engine_signature_ok=True,
        credential_store_reachable=True,
        audit_sink_available=True,
    )
    assert r.mode is DegradationMode.FULL and r.ready
    assert r.to_dict()["mode"] == "full"


def test_readiness_restricted_when_subsystem_degraded():
    r = readiness(
        registry_signature_ok=True,
        engine_signature_ok=True,
        credential_store_reachable=False,
        audit_sink_available=True,
    )
    assert r.mode is DegradationMode.RESTRICTED and r.ready


def test_readiness_minimal_on_signature_failure():
    r = readiness(
        registry_signature_ok=False,
        engine_signature_ok=True,
        credential_store_reachable=True,
        audit_sink_available=True,
    )
    assert r.mode is DegradationMode.MINIMAL and not r.ready


def test_main_entrypoint_roles():
    from wfa.__main__ import main

    assert main(["ingress"]) == 0
    assert main(["worker"]) == 0
    assert main(["help"]) == 0
    assert main(["bogus"]) == 2
