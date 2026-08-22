import pytest

from rif_runtime.capabilities.echo import EchoCapability
from rif_runtime.capabilities.models import (
    CapabilityEvaluation,
    CapabilityIntegrity,
    CapabilityLifecycle,
    CapabilityProvenance,
    CapabilityRecord,
    CapabilityStatus,
)
from rif_runtime.configuration.policies import PolicyRule
from rif_runtime.execution.exceptions import PolicyViolationError
from rif_runtime.execution.manifest import ExecutionManifest
from rif_runtime.execution.result import ExecutionStatus
from rif_runtime.runtime import RIFRuntime
from rif_runtime.schemas import Posture


def admitted_echo_record() -> CapabilityRecord:
    return CapabilityRecord(
        id="echo",
        name="echo",
        provenance=CapabilityProvenance(
            source="builtin:test",
            publisher="rif-runtime",
            version="1.0.0",
        ),
        integrity=CapabilityIntegrity(
            digest="sha256:test",
            signature="sig:test",
            verified=True,
        ),
        lifecycle=CapabilityLifecycle(status=CapabilityStatus.evaluated),
        evaluations=[
            CapabilityEvaluation(
                evaluator="tests",
                suite="capability-admission",
                passed=True,
                score=1.0,
            )
        ],
    )


def _allow(runtime: RIFRuntime, action: str) -> None:
    """Enumerate a capability action so policy admits it.

    execute_capability() evaluates the manifest's own `action` against policy,
    and policy is deny-by-default: a rule with action "*" or target "*" is
    applied rather than skipped, so an action nothing enumerates is denied.
    Admitting the *capability* is necessary but not sufficient -- the action
    has to be allowed too, which is the point of routing execution through
    the policy engine at all.
    """
    runtime.policy_store.upsert(
        PolicyRule(
            id=f"allow_{action.replace('.', '_')}",
            effect="allow",
            action=action,
            target="*",
            reason="capability execution tests",
        )
    )


def test_runtime_executes_only_after_capability_admission(tmp_path) -> None:
    runtime = RIFRuntime(data_dir=tmp_path)
    runtime.register_capability(EchoCapability(), admitted_echo_record())
    _allow(runtime, "ping")

    result = runtime.execute_capability(
        ExecutionManifest(
            actor="agent:test",
            capability="echo",
            action="ping",
        )
    )

    assert result.status is ExecutionStatus.SUCCEEDED
    assert (tmp_path / "capability_evidence.jsonl").exists()


def test_runtime_denies_before_capability_execution_when_posture_locked(
    tmp_path,
) -> None:
    runtime = RIFRuntime(data_dir=tmp_path)
    runtime.register_capability(EchoCapability(), admitted_echo_record())
    runtime.set_posture(Posture.locked)

    result = runtime.execute_capability(
        ExecutionManifest(
            actor="agent:test",
            capability="echo",
            action="ping",
        )
    )

    assert result.status is ExecutionStatus.DENIED
    assert result.output == {}


def test_registry_rejects_unverified_capability(tmp_path) -> None:
    runtime = RIFRuntime(data_dir=tmp_path)
    record = admitted_echo_record()
    record.integrity.verified = False
    runtime.register_capability(EchoCapability(), record)

    with pytest.raises(PolicyViolationError, match="integrity not verified"):
        runtime.capability_registry.admit("echo")


def test_an_unenumerated_capability_action_is_denied(tmp_path) -> None:
    """Deny-by-default reaches the capability path too.

    Registering and admitting a capability does not by itself authorise every
    verb it exposes. With no rule enumerating the action, execution is denied
    before the capability runs -- which is what routing execute_capability()
    through the policy engine is for.
    """
    runtime = RIFRuntime(data_dir=tmp_path)
    runtime.register_capability(EchoCapability(), admitted_echo_record())

    result = runtime.execute_capability(
        ExecutionManifest(actor="agent:test", capability="echo", action="ping")
    )

    assert result.status is ExecutionStatus.DENIED
    assert "deny by default" in result.message
