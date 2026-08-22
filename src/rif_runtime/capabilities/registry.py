from __future__ import annotations

from collections.abc import Iterable

from rif_runtime.execution.exceptions import (
    CapabilityNotFoundError,
    PolicyViolationError,
)

from .capability import Capability
from .models import CapabilityEvaluation, CapabilityRecord, CapabilityStatus


class CapabilityRegistry:
    """
    Registry of executable capabilities and their governance records.

    Capability names are unique. Registration and admission are explicit.
    Resolution is deterministic; execution authority is represented separately
    from the executable adapter so provenance/evaluation evidence cannot be
    confused with the Python object that performs the operation.
    """

    def __init__(self, capabilities: Iterable[Capability] | None = None) -> None:
        self._capabilities: dict[str, Capability] = {}
        self._records: dict[str, CapabilityRecord] = {}

        if capabilities is not None:
            for capability in capabilities:
                self.register(capability)

    def register(
        self,
        capability: Capability,
        record: CapabilityRecord | None = None,
    ) -> None:
        if capability.name in self._capabilities:
            raise ValueError(f"Capability already registered: {capability.name}")

        if record is not None and record.id != capability.name:
            raise ValueError(
                "Capability record id must match executable capability name"
            )

        self._capabilities[capability.name] = capability
        if record is not None:
            self._records[capability.name] = record

    def register_record(self, record: CapabilityRecord) -> None:
        """Register governance metadata before an executable adapter exists."""
        if record.id in self._records:
            raise ValueError(f"Capability record already registered: {record.id}")
        self._records[record.id] = record

    def resolve(self, name: str) -> Capability:
        try:
            return self._capabilities[name]
        except KeyError as exc:
            raise CapabilityNotFoundError(f"Unknown capability: {name}") from exc

    def record(self, name: str) -> CapabilityRecord:
        try:
            return self._records[name]
        except KeyError as exc:
            raise CapabilityNotFoundError(
                f"No governance record for capability: {name}"
            ) from exc

    def admit(self, name: str) -> CapabilityRecord:
        """Admit a capability only after integrity and evaluation evidence pass."""
        record = self.record(name)
        if not record.integrity.verified:
            raise PolicyViolationError(
                f"Capability admission denied: integrity not verified: {name}"
            )
        if not any(evaluation.passed for evaluation in record.evaluations):
            raise PolicyViolationError(
                f"Capability admission denied: no passing evaluation: {name}"
            )
        if record.lifecycle.status not in {
            CapabilityStatus.evaluated,
            CapabilityStatus.admitted,
            CapabilityStatus.available,
        }:
            raise PolicyViolationError(
                "Capability admission denied: "
                f"lifecycle={record.lifecycle.status}: {name}"
            )
        record.lifecycle.status = CapabilityStatus.admitted
        return record

    def add_evaluation(self, name: str, evaluation: CapabilityEvaluation) -> None:
        record = self.record(name)
        record.evaluations.append(evaluation)
        if evaluation.passed:
            record.lifecycle.status = CapabilityStatus.evaluated

    def __contains__(self, name: object) -> bool:
        return name in self._capabilities

    def __len__(self) -> int:
        return len(self._capabilities)
