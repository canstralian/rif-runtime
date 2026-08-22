"""Default step registry wiring (spec §8.1 Steps layer).

Steps that talk to external services take an injected client so the registry is
usable in tests with fakes and in production with real connectors.
"""

from __future__ import annotations

from typing import Any

from wfa.steps.base import StepRegistry
from wfa.steps.github.create_comment import GithubClient, GithubCreateComment
from wfa.steps.github.merge_pr import GithubMergePr, MergeClient
from wfa.steps.llm.summarise import LlmSummarise
from wfa.steps.slack.post_message import SlackClient, SlackPostMessage


def default_registry(
    *,
    github: GithubClient | None = None,
    merge: MergeClient | None = None,
    slack: SlackClient | None = None,
    llm_model: Any = None,
) -> StepRegistry:
    reg = StepRegistry()
    reg.register(LlmSummarise(model=llm_model))
    if github is not None:
        reg.register(GithubCreateComment(client=github))
    if merge is not None:
        reg.register(GithubMergePr(client=merge))
    if slack is not None:
        reg.register(SlackPostMessage(client=slack))
    return reg
