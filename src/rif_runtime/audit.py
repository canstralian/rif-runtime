from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from rif_runtime.security import sha256_digest

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class AuditRecord:
    event_id: str
    timestamp: str
    payload: dict[str, Any]
    previous_hash: str
    current_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "current_hash", calculate_hash(self))

    @staticmethod
    def new_event_id() -> str:
        """Fresh identifier for a record about to be appended to a chain."""
        return str(uuid4())


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def calculate_hash(record: AuditRecord) -> str:
    return sha256_digest(
        {
            "event_id": record.event_id,
            "timestamp": record.timestamp,
            "payload": record.payload,
            "previous_hash": record.previous_hash,
        }
    )


def append_record(
    chain: list[AuditRecord],
    payload: dict[str, Any],
    *,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> AuditRecord:
    previous_hash = chain[-1].current_hash if chain else GENESIS_HASH
    return AuditRecord(
        event_id=event_id or str(uuid4()),
        timestamp=timestamp or utc_now_iso(),
        payload=payload,
        previous_hash=previous_hash,
    )


def verify_chain(chain: list[AuditRecord]) -> bool:
    previous_hash = GENESIS_HASH
    for record in chain:
        if record.previous_hash != previous_hash:
            return False
        if record.current_hash != calculate_hash(record):
            return False
        previous_hash = record.current_hash
    return True
