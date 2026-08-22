"""github.create_comment — a SINK step (spec §3.1 example).

Target identifiers (``repo``, ``issue_number``) come from the T2 workflow definition
via template substitution over authenticated event metadata, NOT from any LLM output
(spec §4.6). The comment ``body`` is T4-derived and is encoded for the GitHub sink by
the runner before it reaches this step's client call.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from wfa.shared.enums import Taint
from wfa.shared.models import StepContext
from wfa.steps.base import Step, StepResult


class GithubClient(Protocol):
    def create_comment(self, token: str, repo: str, issue_number: int, body: str) -> str: ...


class CreateCommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo: str
    issue_number: int
    body: str


class CreateCommentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comment_id: str


class GithubCreateComment(Step):
    id = "github.create_comment"
    version = "1"
    input_model = CreateCommentIn
    output_model = CreateCommentOut
    taint = Taint.SINK
    sink = "github"
    requires_credentials = ("github_token",)
    content_fields = ("body",)

    def __init__(self, client: GithubClient) -> None:
        self._client = client

    def execute(self, args: BaseModel, ctx: StepContext) -> StepResult:
        assert isinstance(args, CreateCommentIn)
        token = ctx.credentials.get("github_token")
        comment_id = self._client.create_comment(token, args.repo, args.issue_number, args.body)
        return StepResult(CreateCommentOut(comment_id=str(comment_id)))
