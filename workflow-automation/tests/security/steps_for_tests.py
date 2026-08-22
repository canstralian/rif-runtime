"""Test-only step types used to probe the engine's guarantees.

These are deliberately adversarial (a credential-reading step, a credential-free
escalated sink) so the security suite can assert the engine refuses or gates them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from wfa.shared.enums import Taint
from wfa.shared.models import StepContext
from wfa.steps.base import Step, StepResult


class _Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _EchoOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool = True


class ReadCredentialStep(Step):
    """Attempts to read a credential — used to prove UNTRUSTED gets zero (acceptance #2)."""

    id = "test.read_credential"
    version = "1"
    input_model = _Empty
    output_model = _EchoOut
    taint = Taint.NEUTRAL
    requires_credentials = ("github_token",)

    def execute(self, args: BaseModel, ctx: StepContext) -> StepResult:
        # If the engine ever let this run under UNTRUSTED, this read still hard-blocks.
        ctx.credentials.get("github_token")
        return StepResult(_EchoOut())


class CredFreeEscalatedSink(Step):
    """A credential-free escalated SINK, so the escalation-approval path is reachable."""

    id = "test.escalated_notify"
    version = "1"
    input_model = _Empty
    output_model = _EchoOut
    taint = Taint.SINK
    sink = None
    escalates_hint = True

    def __init__(self) -> None:
        self.executed = False

    def execute(self, args: BaseModel, ctx: StepContext) -> StepResult:
        self.executed = True
        return StepResult(_EchoOut())
