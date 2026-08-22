"""Retry policy (spec §5.1).

Downstream 5xx retries 3x with exponential backoff 2s/8s/32s ±20% jitter, **only if
the step declares ``idempotent: true``**. A non-idempotent step with an uncertain
outcome is NEVER auto-retried — it is marked ``INDETERMINATE``, dead-lettered, and
alerted. Duplicate Jira tickets and duplicate deploys are worse than a stalled run.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

_BASE_DELAYS = (2.0, 8.0, 32.0)


def backoff_delays(rng: random.Random | None = None) -> list[float]:
    r = rng or random.Random()
    return [d * (1.0 + r.uniform(-0.2, 0.2)) for d in _BASE_DELAYS]


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    indeterminate: bool
    reason: str


class RetryPolicy:
    def __init__(self, max_attempts: int = 3) -> None:
        self._max = max_attempts

    def decide(self, *, idempotent: bool, attempts: int, uncertain_outcome: bool) -> RetryDecision:
        """Decide whether to retry after a failure.

        * Non-idempotent step whose outcome is uncertain => never retry; INDETERMINATE.
        * Idempotent step under the attempt ceiling => retry.
        * Otherwise => no retry (dead-letter).
        """

        if not idempotent and uncertain_outcome:
            return RetryDecision(False, True, "non-idempotent-uncertain")
        if idempotent and attempts < self._max:
            return RetryDecision(True, False, "idempotent-retry")
        return RetryDecision(False, False, "exhausted")


# Public alias so callers can import a single policy type name.
RetryPolicyResult = RetryDecision
