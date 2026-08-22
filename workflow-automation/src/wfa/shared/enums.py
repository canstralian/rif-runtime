"""Enumerations for the engine.

All enums subclass ``str`` so they serialise cleanly into audit JSONL and compare
equal to plain strings in tests, matching the RIF-fleet convention.
"""

from __future__ import annotations

from enum import Enum


class Profile(str, Enum):
    """Event provenance profile (spec §2.1).

    ``UNSPECIFIED`` is the fail-closed literal (spec §0). Absent, malformed, or
    unclassifiable provenance resolves here and never to ``TRUSTED``.
    """

    TRUSTED = "TRUSTED"
    UNTRUSTED = "UNTRUSTED"
    UNSPECIFIED = "UNSPECIFIED"


# Profile ordering for "weakest profile that suffices" comparisons (spec §3.1).
# A run is permitted only when its assigned profile is at least as strong as the
# workflow's declared ``profile_required``.
_PROFILE_STRENGTH = {Profile.UNSPECIFIED: 0, Profile.UNTRUSTED: 1, Profile.TRUSTED: 2}


def profile_satisfies(assigned: Profile, required: Profile) -> bool:
    """Return True when ``assigned`` is strong enough to run a ``required`` workflow.

    ``UNSPECIFIED`` never satisfies anything (fail-closed).
    """

    if assigned is Profile.UNSPECIFIED or required is Profile.UNSPECIFIED:
        return False
    return _PROFILE_STRENGTH[assigned] >= _PROFILE_STRENGTH[required]


class Taint(str, Enum):
    """Step taint classification (spec §3.1)."""

    SOURCE = "SOURCE"
    SINK = "SINK"
    NEUTRAL = "NEUTRAL"


class RunOutcome(str, Enum):
    """The four closed terminal run states (spec §3.2)."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABORTED = "aborted"
    DEAD_LETTERED = "dead_lettered"


class StepOutcome(str, Enum):
    """Per-step outcome recorded in the run record."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    ABORTED = "aborted"
    INDETERMINATE = "indeterminate"


class DegradationMode(str, Enum):
    """Engine operating modes (spec §5.2)."""

    FULL = "full"
    RESTRICTED = "restricted"
    DRAIN = "drain"
    MINIMAL = "minimal"
