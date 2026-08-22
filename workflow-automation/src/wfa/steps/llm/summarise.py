"""LLM summarisation step (spec §4.6).

An LLM step's output is T4 and is bound by §4.6:
  * it supplies **content only** — never a target identifier, repo, channel, URL,
    recipient, permission, or next-step selector;
  * it validates against a closed JSON Schema;
  * it cannot cause a step the definition did not already declare;
  * it is scanned and sink-encoded like any other T4 content.

The output model here is deliberately just ``{summary: str}`` — there is no field
into which the model could place a target or selector, so a poisoned diff can at most
produce misleading prose (visible, recoverable), never redirection.

The bundled implementation is a deterministic stub (no network) so tests are
reproducible; a real deployment injects an LLM client. ``non_deterministic`` is True
regardless, so the run record labels the content as such (spec §3.3).
"""

from __future__ import annotations

from typing import Callable

from pydantic import BaseModel, ConfigDict

from wfa.shared.enums import Taint
from wfa.shared.models import StepContext
from wfa.steps.base import Step, StepResult


class SummariseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str


class SummariseOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str


def _stub_summarise(content: str) -> str:
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    head = lines[0] if lines else ""
    return f"Summary ({len(lines)} lines): {head[:200]}"


class LlmSummarise(Step):
    id = "llm.summarise"
    version = "1"
    input_model = SummariseIn
    output_model = SummariseOut
    taint = Taint.SOURCE
    sink = None
    non_deterministic = True

    def __init__(self, model: Callable[[str], str] | None = None) -> None:
        self._model = model or _stub_summarise

    def execute(self, args: BaseModel, ctx: StepContext) -> StepResult:
        assert isinstance(args, SummariseIn)
        summary = self._model(args.content)
        # Output is content-only; no identifier/selector fields exist to populate.
        return StepResult(SummariseOut(summary=summary), non_deterministic=True)
