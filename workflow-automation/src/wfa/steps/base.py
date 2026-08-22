"""Step abstract base and registry (spec §8.3).

A step declares its *intrinsic* capabilities as class attributes:
  * ``input_model`` / ``output_model`` — closed Pydantic models;
  * ``taint`` — SOURCE / SINK / NEUTRAL;
  * ``sink`` — the downstream sink its output targets (for boundary encoding), or None;
  * ``requires_credentials`` — credential refs it may read;
  * ``non_deterministic`` — True for LLM-backed steps.

The runner cross-checks the workflow definition's declared ``taint`` against the step
type's intrinsic ``taint``, so a SINK step type cannot be declared NEUTRAL to slip
past profile enforcement.

``execute`` runs only after provenance classification, profile assignment, permission
intersection, template substitution, taint evaluation, and — where applicable —
escalation approval have passed. A step cannot read a credential outside its declared
scope, cannot widen its own permission, and cannot mark its own output trusted.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from wfa.shared.enums import Taint
from wfa.shared.models import StepContext


@dataclass
class StepResult:
    output: BaseModel
    non_deterministic: bool = False


class Step(ABC):
    id: str = "abstract"
    version: str = "0"
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    taint: Taint = Taint.NEUTRAL
    sink: str | None = None
    requires_credentials: tuple[str, ...] = ()
    non_deterministic: bool = False
    # Input fields whose (T4-derived) content must be sink-encoded at the boundary
    # before this step emits them (spec §4.4).
    content_fields: tuple[str, ...] = ()

    @abstractmethod
    def execute(self, args: BaseModel, ctx: StepContext) -> StepResult:
        """Perform the step's effect and return a validated output model."""


class StepRegistry:
    def __init__(self) -> None:
        self._steps: dict[str, Step] = {}

    def register(self, step: Step) -> None:
        self._steps[step.id] = step

    def get(self, step_id: str) -> Step | None:
        return self._steps.get(step_id)

    def types(self) -> set[str]:
        return set(self._steps)

    def as_dict(self) -> dict[str, Step]:
        return dict(self._steps)


def coerce_output(model: type[BaseModel], value: Any) -> BaseModel:
    """Validate a step's output against its declared model (spec §3.2).

    A violation raises; the runner turns it into a failed step and does not propagate
    a partially-valid object to the next step.
    """

    if isinstance(value, model):
        return value
    return model.model_validate(value)
