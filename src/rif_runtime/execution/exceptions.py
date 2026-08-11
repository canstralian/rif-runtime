from __future__ import annotations


class ExecutionError(Exception):
    """
    Base exception for all execution kernel errors.
    """


class PolicyViolationError(ExecutionError):
    """
    Raised when execution is attempted without satisfying policy.
    """


class CapabilityNotFoundError(ExecutionError):
    """
    Raised when the requested capability cannot be resolved.
    """


class AdapterExecutionError(ExecutionError):
    """
    Raised when a capability adapter fails during execution.
    """


class ExecutionTimeoutError(ExecutionError):
    """
    Raised when execution exceeds its permitted runtime.
    """


class EvidenceGenerationError(ExecutionError):
    """
    Raised when execution completes but evidence cannot be recorded.
    """
