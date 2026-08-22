"""Runner layer — the enforcement chokepoint (spec §8.1).

``engine.RunEngine`` is the sole place profile, permission, taint, and escalation are
enforced. Steps never reach Ingress, the Classifier, or the credential store
directly.
"""

from wfa.runner.chain import ChainGuard
from wfa.runner.engine import RunEngine
from wfa.runner.escalation import ApprovalToken, EscalationBroker
from wfa.runner.permissions import intersect_permissions
from wfa.runner.resolve import SignedRegistry, WorkflowResolver

__all__ = [
    "ChainGuard",
    "RunEngine",
    "ApprovalToken",
    "EscalationBroker",
    "intersect_permissions",
    "SignedRegistry",
    "WorkflowResolver",
]
