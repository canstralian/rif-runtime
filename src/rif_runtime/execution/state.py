from __future__ import annotations

from enum import StrEnum


class ExecutionState(StrEnum):
    """
    Lifecycle states for a governed execution.

    States represent where an execution is in the runtime
    lifecycle, independent of its final outcome.

    Status: **seeded, not yet wired.** Nothing in the runtime reads this enum
    today; the shipped run lifecycle uses ``runs.schemas.RunStatus``, whose
    ``created``/``policy_approved``/``denied``/``failed`` members overlap these.

    Reconciling the two is Track B work held by
    ``docs/spec-review-identity-spine-migration.md``, which governs the
    Run/Decision/Execution hierarchy (ADR-0010, ADR-0012) and still has open
    checklist items on re-keying ``execution_id`` to ``run_id``. Do not
    converge them here: two plausible implementations disagreeing at that seam
    is the outcome that review exists to prevent.
    """

    CREATED = "created"
    POLICY_APPROVED = "policy_approved"
    ROUTING = "routing"
    EXECUTING = "executing"
    RECORDING_EVIDENCE = "recording_evidence"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"
