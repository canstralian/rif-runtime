"""Delivery replay protection (spec §2.3 HB-2, §4.3).

Two independent checks:
  * timestamp skew: the signed delivery timestamp must be within ``skew_s`` of now;
  * uniqueness: a ``delivery_id`` already seen within ``window_s`` is a replay.
"""

from __future__ import annotations

from dataclasses import dataclass

from wfa.shared.rules import HardBlockRule


@dataclass(frozen=True)
class ReplayResult:
    ok: bool
    rule_id: str | None = None
    reason: str = ""


class ReplayWindow:
    """In-memory sliding window of consumed delivery IDs.

    Persistence backend is pluggable in production (spec OD-1 recommends Postgres);
    the semantics — reject on skew or duplicate — are what matters here and are what
    the tests pin.
    """

    def __init__(self, window_s: int = 24 * 3600, skew_s: int = 300) -> None:
        self._window_s = window_s
        self._skew_s = skew_s
        self._seen: dict[str, float] = {}

    def _evict(self, now: float) -> None:
        cutoff = now - self._window_s
        stale = [k for k, t in self._seen.items() if t < cutoff]
        for k in stale:
            del self._seen[k]

    def check(self, delivery_id: str, delivered_at: float, now: float) -> ReplayResult:
        """Validate and, on success, consume ``delivery_id``.

        Fails closed: a missing/empty delivery_id is rejected.
        """

        self._evict(now)
        if not delivery_id:
            return ReplayResult(False, HardBlockRule.HB_2, "missing delivery_id")
        if abs(now - delivered_at) > self._skew_s:
            return ReplayResult(False, HardBlockRule.HB_2, "timestamp skew")
        if delivery_id in self._seen:
            return ReplayResult(False, HardBlockRule.HB_2, "delivery_id already consumed")
        self._seen[delivery_id] = now
        return ReplayResult(True)
