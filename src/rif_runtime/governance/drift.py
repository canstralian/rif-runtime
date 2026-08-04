"""Drift detection and correction recommendation for the governance loop.

A DriftVector summarises how far an actor's recent behaviour has moved from
acceptable norms across four orthogonal dimensions:

* denial_rate       – fraction of recent decisions that were denials
* adversarial_score – fraction of events containing an adversarial payload
* action_entropy    – Shannon entropy of the action distribution (nats);
                      high = varied actions, low = repetitive probing
* target_entropy    – Shannon entropy of the target distribution (nats);
                      low = hammering a single blocked target

recommend_correction() maps the vector to the mildest Posture that will
contain the risk.  It incorporates:
  - Word-boundary-anchored SQL/shell-keyword detection
  - Shell-chaining operator detection (`;`, `|`, backtick)
  - XSS / path-traversal pattern detection
  - Entropy-based focused-probe heuristic (low target entropy + elevated
    denials is a signal even without adversarial payload)
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from rif_runtime.schemas import PolicyDecision, Posture

# Word-boundary-anchored patterns for detecting adversarial payload in targets
# and reasons.  All keyword alternatives use \b so substrings inside longer
# identifiers (e.g. "elasticsearch", "selectAll", "executor") are not flagged.
_ADVERSARIAL_PATTERNS: list[re.Pattern[str]] = [
    # SQL injection keywords
    re.compile(
        r"\b(select|insert|update|delete|drop|union|exec|execute|truncate)\b",
        re.IGNORECASE,
    ),
    # Timing / blind-injection helpers
    re.compile(r"\b(sleep|benchmark|pg_sleep|waitfor\s+delay)\b", re.IGNORECASE),
    # Path traversal — two or more ../ or ..\ sequences anywhere in the string
    # (consecutive *or* separated by a path segment, e.g. ../segment/../)
    re.compile(r"(\.\.[\\/]).*(\.\.[\\/])"),
    # Shell interpreter references
    re.compile(r"\b(cmd\.exe|powershell|/bin/(sh|bash|zsh))\b", re.IGNORECASE),
    # Shell chaining: semicolon/pipe require whitespace after to avoid false-positives
    # on legitimate query separators like ?a=1;b=2.  Backtick substitution fires
    # without a space because value`cmd` syntax has no delimiter.
    re.compile(r"[|;]\s+\w|`\s*\w"),
    # Cross-site scripting
    re.compile(r"<\s*script\b", re.IGNORECASE),
]


def _extract_payload(target: str) -> str:
    """For URL targets, return path+params+query (not scheme or hostname).

    urlparse splits ';'-delimited path parameters into a separate `params`
    field (RFC 1808), so we re-join them to preserve shell-chaining operators
    like `; ls` that land there.
    """
    parsed = urlparse(target)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        payload = parsed.path or ""
        if parsed.params:
            payload += ";" + parsed.params
        if parsed.query:
            payload += "?" + parsed.query
        return unquote(payload)
    return target


def _adversarial_score(events: Sequence[PolicyDecision]) -> float:
    """Return fraction of events whose target contains an adversarial pattern.

    For URL targets, only path+query is checked — the hostname is excluded to
    avoid false-positives from subdomain labels that happen to match SQL keywords
    (e.g. api.update.service.io).  The reason field is not checked because it is
    system-generated and not a user-controlled injection vector.
    """
    if not events:
        return 0.0
    hits = sum(
        1
        for e in events
        if any(p.search(_extract_payload(e.target)) for p in _ADVERSARIAL_PATTERNS)
    )
    return hits / len(events)


def _entropy(values: Sequence[str]) -> float:
    """Shannon entropy of a string sequence (nats).  Returns 0.0 for empty input."""
    if not values:
        return 0.0
    counts = Counter(values)
    total = len(values)
    return -sum((c / total) * math.log(c / total) for c in counts.values())


@dataclass(frozen=True)
class DriftVector:
    """Multidimensional summary of behavioural drift in a recent event window."""

    denial_rate: float  # [0, 1]
    adversarial_score: float  # [0, 1]
    action_entropy: float  # >= 0
    target_entropy: float  # >= 0

    @classmethod
    def from_events(cls, events: Sequence[PolicyDecision]) -> DriftVector:
        if not events:
            return cls(0.0, 0.0, 0.0, 0.0)
        denial_rate = sum(1 for e in events if e.decision == "deny") / len(events)
        return cls(
            denial_rate=denial_rate,
            adversarial_score=_adversarial_score(events),
            action_entropy=_entropy([e.action for e in events]),
            target_entropy=_entropy([e.target for e in events]),
        )


def recommend_correction(vector: DriftVector) -> Posture:
    """Map a DriftVector to the mildest Posture sufficient to contain the risk.

    Evaluated in order; first matching condition wins:

    locked     – adversarial payload prevalent (>30 %) or denial rate >80 %
    restricted – lighter adversarial signal, high denial rate (>50 %), or a
                 focused-probe pattern (low target entropy + elevated denials)
    elevated   – moderate denial rate (>20 %)
    normal     – no significant drift detected
    """
    if vector.adversarial_score > 0.3 or vector.denial_rate > 0.8:
        return Posture.locked

    focused_probe = vector.target_entropy < 0.5 and vector.denial_rate > 0.3
    if vector.adversarial_score > 0.1 or vector.denial_rate > 0.5 or focused_probe:
        return Posture.restricted

    if vector.denial_rate > 0.2:
        return Posture.elevated

    return Posture.normal
