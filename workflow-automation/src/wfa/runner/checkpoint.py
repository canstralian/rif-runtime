"""Step checkpointing and SINK intent/completion records (spec §5.3).

Step outputs are checkpointed at boundaries. SINK steps additionally write an intent
record before executing and a completion record after, so a crash between the two is
detectable and resolves to ``INDETERMINATE`` rather than silent duplication.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class _RunCheckpoints:
    outputs: dict[str, Any] = field(default_factory=dict)
    intents: set[str] = field(default_factory=set)
    completions: set[str] = field(default_factory=set)


class CheckpointStore:
    def __init__(self) -> None:
        self._runs: dict[str, _RunCheckpoints] = {}

    def _run(self, run_id: str) -> _RunCheckpoints:
        return self._runs.setdefault(run_id, _RunCheckpoints())

    def record_output(self, run_id: str, step_id: str, output: Any) -> None:
        self._run(run_id).outputs[step_id] = output

    def output(self, run_id: str, step_id: str) -> Any:
        return self._run(run_id).outputs.get(step_id)

    def write_intent(self, run_id: str, step_id: str) -> None:
        self._run(run_id).intents.add(step_id)

    def write_completion(self, run_id: str, step_id: str) -> None:
        self._run(run_id).completions.add(step_id)

    def is_indeterminate(self, run_id: str, step_id: str) -> bool:
        """True if an intent was written but no completion — a crash-in-the-middle."""

        run = self._run(run_id)
        return step_id in run.intents and step_id not in run.completions
