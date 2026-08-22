"""Sink-specific output encoding (spec §4.2, §4.4, §7 vector F).

Content bound for Slack, Jira, or GitHub is encoded for that sink at the boundary:
mentions neutralised, markup escaped, and ``@channel``/``@here`` stripped from
UNTRUSTED-derived content. This neutralises "output format hijack" where a PR body
containing Slack/Jira markup or mentions is echoed downstream.
"""

from __future__ import annotations

import html
import re

from wfa.shared.enums import Profile

_BROADCAST = re.compile(r"@(channel|here|everyone)\b", re.IGNORECASE)
# Slack user/group mention tokens like <!subteam^ID> or <@U123> or <!channel>.
_SLACK_MENTION_TOKEN = re.compile(r"<[!@#][^>]*>")
_JIRA_MENTION = re.compile(r"\[~([^\]]+)\]")


def _neutralise_broadcast(text: str) -> str:
    # Insert a zero-width-safe break so the client does not treat it as a broadcast.
    return _BROADCAST.sub(lambda m: "@\u200b" + m.group(1), text)


def _encode_slack(text: str, profile: Profile) -> str:
    # Slack requires &, <, > escaped in message text.
    out = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out = _SLACK_MENTION_TOKEN.sub("", out)
    if profile is not Profile.TRUSTED:
        out = _neutralise_broadcast(out)
    return out


def _encode_jira(text: str, profile: Profile) -> str:
    # Neutralise Jira wiki markup that has active semantics and user mentions.
    out = text.replace("{", "\\{").replace("}", "\\}").replace("[", "\\[").replace("]", "\\]")
    out = _JIRA_MENTION.sub(lambda m: m.group(1), out)
    if profile is not Profile.TRUSTED:
        out = _neutralise_broadcast(out)
    return out


def _encode_github(text: str, profile: Profile) -> str:
    # HTML-escape so raw HTML in a comment cannot render, and neutralise @mentions
    # from untrusted content so a PR body cannot ping arbitrary users/teams.
    out = html.escape(text, quote=False)
    if profile is not Profile.TRUSTED:
        out = re.sub(r"@([A-Za-z0-9_-]+)", "@\u200b\\1", out)
        out = _neutralise_broadcast(out)
    return out


_ENCODERS = {
    "slack": _encode_slack,
    "jira": _encode_jira,
    "github": _encode_github,
}


def encode_for_sink(sink: str, text: str, profile: Profile) -> str:
    """Encode ``text`` for ``sink``. Unknown sinks fail closed (no passthrough)."""

    encoder = _ENCODERS.get(sink)
    if encoder is None:
        raise ValueError(f"no encoder registered for sink {sink!r}")
    return encoder(text, profile)
