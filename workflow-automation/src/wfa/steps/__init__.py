"""Step plugins (spec §8.1 Steps layer).

Steps are the only place T4 content meets an interpreter (an LLM, an API client, a
downstream formatter). They never reach Ingress, the Classifier, or the credential
store directly — everything they receive is handed to them by the Runner.

Adding a step is: subclass ``Step``, declare its intrinsic capabilities, register it,
sign it.
"""

from wfa.steps.base import Step, StepRegistry, StepResult
from wfa.steps.registry import default_registry

__all__ = ["Step", "StepRegistry", "StepResult", "default_registry"]
