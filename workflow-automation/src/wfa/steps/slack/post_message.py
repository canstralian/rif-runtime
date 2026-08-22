"""slack.post_message — a SINK step targeting the Slack sink.

The channel is a T2-declared identifier; the message text is T4-derived and encoded
for Slack by the runner (``@channel``/``@here`` stripped for UNTRUSTED-derived
content, mentions and markup neutralised).
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from wfa.shared.enums import Taint
from wfa.shared.models import StepContext
from wfa.steps.base import Step, StepResult


class SlackClient(Protocol):
    def post_message(self, token: str, channel: str, text: str) -> str: ...


class PostMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str
    text: str


class PostMessageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ts: str


class SlackPostMessage(Step):
    id = "slack.post_message"
    version = "1"
    input_model = PostMessageIn
    output_model = PostMessageOut
    taint = Taint.SINK
    sink = "slack"
    requires_credentials = ("slack_token",)
    content_fields = ("text",)

    def __init__(self, client: SlackClient) -> None:
        self._client = client

    def execute(self, args: BaseModel, ctx: StepContext) -> StepResult:
        assert isinstance(args, PostMessageIn)
        token = ctx.credentials.get("slack_token")
        ts = self._client.post_message(token, args.channel, args.text)
        return StepResult(PostMessageOut(ts=str(ts)))
