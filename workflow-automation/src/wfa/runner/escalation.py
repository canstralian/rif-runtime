"""Escalated-step approval (spec §4.9).

A step marked ``escalates: true`` performs an action whose blast radius exceeds
normal SINK. Under TRUSTED it executes per policy. Under any other condition it
suspends and requires T3 approval, carrying an HMAC token over
``sha256(run_id ‖ step_id ‖ resolved_action_hash ‖ nonce ‖ expiry)``, TTL 600s,
single-use. The dispatcher re-verifies ``resolved_action_hash`` immediately before
execution; drift aborts.

**Approval timeout aborts.** There is no configuration under which a pending
approval proceeds on expiry, and ``auto_approve`` does not exist (there is no code
path here that grants approval without a token minted by the operator console).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

_SEP = "\u2016"


def resolved_action_hash(action_description: str) -> str:
    return hashlib.sha256(action_description.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApprovalToken:
    run_id: str
    step_id: str
    resolved_action_hash: str
    nonce: str
    expiry: float
    hmac: str


class ApprovalError(Exception):
    pass


class EscalationBroker:
    """Mints and verifies single-use, action-bound approval tokens."""

    def __init__(self, signing_key: bytes, ttl_s: int = 600) -> None:
        self._key = signing_key
        self._ttl = ttl_s
        self._consumed: set[str] = set()

    def _mac(self, run_id: str, step_id: str, action_hash: str, nonce: str, expiry: float) -> str:
        material = _SEP.join((run_id, step_id, action_hash, nonce, f"{expiry:.6f}"))
        return hmac.new(self._key, material.encode("utf-8"), hashlib.sha256).hexdigest()

    def mint(self, run_id: str, step_id: str, action_hash: str, now: float) -> ApprovalToken:
        """Mint a token — done by the operator console upon T3 approval only."""

        nonce = secrets.token_hex(16)
        expiry = now + self._ttl
        mac = self._mac(run_id, step_id, action_hash, nonce, expiry)
        return ApprovalToken(run_id, step_id, action_hash, nonce, expiry, mac)

    def verify_and_consume(
        self,
        token: ApprovalToken,
        run_id: str,
        step_id: str,
        current_action_hash: str,
        now: float,
    ) -> None:
        """Verify a token immediately before execution; consume it (single-use).

        Raises ``ApprovalError`` on any of: HMAC mismatch, expiry (timeout => abort),
        replay (already consumed), run/step mismatch, or action-hash drift.
        """

        expected = self._mac(
            token.run_id, token.step_id, token.resolved_action_hash, token.nonce, token.expiry
        )
        if not hmac.compare_digest(expected, token.hmac):
            raise ApprovalError("approval token HMAC mismatch")
        if now > token.expiry:
            # Timeout defaults to deny, never to proceed (spec §1.5, §4.9).
            raise ApprovalError("approval token expired")
        if token.run_id != run_id or token.step_id != step_id:
            raise ApprovalError("approval token run/step mismatch")
        # Re-verify the resolved action immediately before execution; drift aborts.
        if token.resolved_action_hash != current_action_hash:
            raise ApprovalError("resolved action drift")
        if token.nonce in self._consumed:
            raise ApprovalError("approval token already consumed")
        self._consumed.add(token.nonce)
