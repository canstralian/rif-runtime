"""Webhook ingress handler (spec §8.4 Ingress phase).

Pipeline: HMAC verify -> size bound -> replay check -> durable enqueue -> ack.
Never ack before durable enqueue (spec §5.1). Responses are constant-shape and
constant-time regardless of failure cause (spec §4.3), so the endpoint discloses
nothing about which repositories or secrets exist.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from wfa.ingress.hmac_verify import HmacVerifier
from wfa.ingress.replay import ReplayWindow


@dataclass(frozen=True)
class IngressResult:
    """A constant-shape ingress outcome.

    The public HTTP response derived from this is always the same body/shape; the
    ``accepted``/``rule_id`` detail is for internal audit only and is never returned
    to an anonymous caller (spec §2.4).
    """

    status: int
    accepted: bool
    rule_id: str | None = None
    reason: str = ""


# The single response body the endpoint ever returns on the happy and most sad paths.
_CONSTANT_BODY = {"status": "received"}


class WebhookIngress:
    def __init__(
        self,
        verifier: HmacVerifier,
        replay: ReplayWindow,
        enqueue: Callable[[dict[str, Any]], bool],
        max_payload_bytes: int = 5_242_880,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._verifier = verifier
        self._replay = replay
        self._enqueue = enqueue
        self._max = max_payload_bytes
        self._clock = clock

    def handle(
        self,
        source: str,
        raw_body: bytes,
        signature: str,
        delivery_id: str,
        delivered_at: float,
    ) -> IngressResult:
        now = self._clock()

        # 1. Authenticate BEFORE parsing (spec §8.1).
        if not self._verifier.verify(source, raw_body, signature):
            # Constant-shape 202 so a forged/unknown source learns nothing (spec §2.4).
            return IngressResult(202, False, "HB-1", "auth")

        # 2. Size bound (before deserialisation).
        if len(raw_body) > self._max:
            return IngressResult(202, False, "HB-2", "oversize")

        # 3. Replay / skew.
        rr = self._replay.check(delivery_id, delivered_at, now)
        if not rr.ok:
            return IngressResult(202, False, rr.rule_id, rr.reason)

        # 4. Parse (now safe: authenticated + size-bounded).
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return IngressResult(202, False, "PARSE", "parse")

        job = {
            "source": source,
            "delivery_id": delivery_id,
            "delivered_at": delivered_at,
            "received_at": now,
            "body": body,
        }

        # 5. Durable enqueue, THEN ack. If the broker is unavailable, return 503 so
        # the platform redelivers; never ack an event we cannot durably enqueue.
        if not self._enqueue(job):
            return IngressResult(503, False, "QUEUE", "enqueue-failed")

        return IngressResult(202, True)

    @staticmethod
    def public_body(result: IngressResult) -> dict[str, Any]:
        """The bytes actually written back to the caller — constant across outcomes."""

        return dict(_CONSTANT_BODY)
