"""Dead-letter store (spec §5.1).

After ``max_delivery_attempts`` (3) a poison message is dead-lettered with full
context; the engine never infinite-retries. Shed events are also dead-lettered with
cause (spec §2.5). Payloads are redacted on the write path (spec §4.5) — the
redactor is applied by the caller before handing a payload here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DeadLetter:
    delivery_id: str
    cause: str
    rule_id: str | None
    context: dict[str, Any] = field(default_factory=dict)


class DeadLetterStore:
    def __init__(self) -> None:
        self._items: list[DeadLetter] = []

    def add(
        self,
        delivery_id: str,
        cause: str,
        rule_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> DeadLetter:
        dl = DeadLetter(delivery_id, cause, rule_id, context or {})
        self._items.append(dl)
        return dl

    def all(self) -> list[DeadLetter]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)
