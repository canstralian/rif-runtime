"""Operator console (T3 authority, spec §1.2 tier T3, §4.9).

The on-call human's authenticated surface. T3 can pause/resume/drain the engine,
kill a run, and approve an escalated step. Approval mints a single-use, action-bound
token through the ``EscalationBroker`` — the console is the ONLY minting path, so
there is no ``auto_approve`` and no code path that grants approval without a human.

Escalation notifications go out-of-band (spec OD-3): never to a channel the
triggering event can post to. This module only mints/records approvals; delivery of
the request is the deployment's responsibility.
"""

from __future__ import annotations

from wfa.runner.escalation import ApprovalToken, EscalationBroker, resolved_action_hash
from wfa.shared.enums import DegradationMode


class OperatorConsole:
    def __init__(self, escalation: EscalationBroker) -> None:
        self._escalation = escalation
        self._mode = DegradationMode.FULL
        self._killed: set[str] = set()

    @property
    def mode(self) -> DegradationMode:
        return self._mode

    def pause(self) -> None:
        """Drain mode: accept and enqueue, execute nothing (spec §5.2)."""

        self._mode = DegradationMode.DRAIN

    def resume(self) -> None:
        self._mode = DegradationMode.FULL

    def kill(self, run_id: str) -> None:
        self._killed.add(run_id)

    def is_killed(self, run_id: str) -> bool:
        return run_id in self._killed

    def approve_step(
        self, run_id: str, step_id: str, resolved_action: str, now: float
    ) -> ApprovalToken:
        """T3 approves an escalated step, minting a single-use action-bound token."""

        return self._escalation.mint(run_id, step_id, resolved_action_hash(resolved_action), now)
