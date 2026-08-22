"""Idempotency keying (spec §3.3, §5.3).

Run IDs are ``sha256(delivery_id ‖ workflow_id ‖ workflow_version)`` so redelivery
is detectable. A repeated key returns the existing run record rather than starting a
second run — at-least-once delivery is guaranteed upstream while exactly-once
execution is not, so idempotency lives here.
"""

from __future__ import annotations

import hashlib

from wfa.shared.models import RunRecord

_SEP = "\u2016"  # ‖ — an explicit separator so field boundaries cannot collide


def run_id(delivery_id: str, workflow_id: str, workflow_version: str) -> str:
    material = _SEP.join((delivery_id, workflow_id, workflow_version)).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


class IdempotencyStore:
    """Maps ``run_id`` -> ``RunRecord``; a repeated key returns the existing record."""

    def __init__(self) -> None:
        self._records: dict[str, RunRecord] = {}

    def existing(self, rid: str) -> RunRecord | None:
        return self._records.get(rid)

    def put(self, record: RunRecord) -> None:
        self._records[record.run_id] = record

    def seen(self, rid: str) -> bool:
        return rid in self._records
