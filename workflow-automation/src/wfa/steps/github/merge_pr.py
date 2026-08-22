"""github.merge_pr — an ESCALATED SINK step (spec §4.9).

Merging exceeds normal SINK blast radius, so this step type is meant to be declared
``escalates: true``. Under TRUSTED it runs per policy; under any other condition the
runner suspends it for T3 approval and aborts on timeout.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from wfa.shared.enums import Taint
from wfa.shared.models import StepContext
from wfa.steps.base import Step, StepResult


class MergeClient(Protocol):
    def merge_pr(self, token: str, repo: str, pr_number: int) -> str: ...


class MergePrIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo: str
    pr_number: int


class MergePrOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    merged_sha: str


class GithubMergePr(Step):
    id = "github.merge_pr"
    version = "1"
    input_model = MergePrIn
    output_model = MergePrOut
    taint = Taint.SINK
    sink = None
    requires_credentials = ("github_token",)

    def __init__(self, client: MergeClient) -> None:
        self._client = client

    def describe_action(self, args: MergePrIn) -> str:
        """Human-readable resolved action bound into the approval token (spec §4.9)."""

        return f"merge PR {args.repo}#{args.pr_number}"

    def execute(self, args: BaseModel, ctx: StepContext) -> StepResult:
        assert isinstance(args, MergePrIn)
        token = ctx.credentials.get("github_token")
        sha = self._client.merge_pr(token, args.repo, args.pr_number)
        return StepResult(MergePrOut(merged_sha=str(sha)))
