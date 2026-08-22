"""Shared, cross-cutting types for the engine.

Nothing in here reaches out to Ingress, the Classifier, or the credential store
(spec §8.1): these are pure data/enum definitions consumed by every layer.
"""

from wfa.shared.enums import (
    DegradationMode,
    Profile,
    RunOutcome,
    StepOutcome,
    Taint,
)
from wfa.shared.errors import HardBlock, RegistrationError, WfaError
from wfa.shared.models import (
    Event,
    EngineConfig,
    ProvenanceFacts,
    RunContext,
    RunRecord,
    StepContext,
    StepDefinition,
    WorkflowDefinition,
)
from wfa.shared.rules import RULE_DESCRIPTIONS, HardBlockRule

__all__ = [
    "DegradationMode",
    "Profile",
    "RunOutcome",
    "StepOutcome",
    "Taint",
    "HardBlock",
    "RegistrationError",
    "WfaError",
    "Event",
    "EngineConfig",
    "ProvenanceFacts",
    "RunContext",
    "RunRecord",
    "StepContext",
    "StepDefinition",
    "WorkflowDefinition",
    "RULE_DESCRIPTIONS",
    "HardBlockRule",
]
