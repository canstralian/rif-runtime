"""Loop and recurrence control (spec §4.7, §2.5 HB-7).

Every run carries ``chain_depth`` and ``root_delivery_id``. Events attributable to
the engine's own actor are dropped unless a T2 workflow explicitly opts in, and even
then remain subject to ``max_chain_depth``.
"""

from __future__ import annotations

from dataclasses import dataclass

from wfa.shared.errors import HardBlock
from wfa.shared.rules import HardBlockRule


@dataclass(frozen=True)
class ChainDecision:
    proceed: bool
    reason: str = ""


class ChainGuard:
    def __init__(self, max_chain_depth: int, engine_actor: str) -> None:
        self._max = max_chain_depth
        self._engine_actor = engine_actor

    def check_depth(self, chain_depth: int) -> None:
        """Raise HB-7 if the chain would exceed the configured maximum."""

        if chain_depth > self._max:
            raise HardBlock(
                HardBlockRule.HB_7,
                f"chain depth {chain_depth} exceeds max {self._max}",
            )

    def admit(self, actor: str, chain_depth: int, workflow_opts_in_self: bool) -> ChainDecision:
        """Decide whether an inbound event should produce a run.

        Events by the engine's own actor are dropped unless the target workflow
        explicitly opts in (spec §4.7); even then depth still applies.
        """

        if actor and actor == self._engine_actor and not workflow_opts_in_self:
            return ChainDecision(False, "self-actor-drop")
        if chain_depth > self._max:
            return ChainDecision(False, "chain-depth-exceeded")
        return ChainDecision(True)
