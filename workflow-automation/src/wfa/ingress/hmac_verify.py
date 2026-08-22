"""Per-source HMAC-SHA256 webhook authentication (spec §4.3).

Verification precedes parsing: the raw body is authenticated before any
deserialiser touches it. The comparison is constant-time and the secret is scoped
per source (installation) and never shared across sources.
"""

from __future__ import annotations

import hashlib
import hmac


def compute_signature(secret: bytes, raw_body: bytes) -> str:
    """Return the hex HMAC-SHA256 of ``raw_body`` under ``secret``."""

    return hmac.new(secret, raw_body, hashlib.sha256).hexdigest()


def verify_signature(secret: bytes, raw_body: bytes, provided_signature: str) -> bool:
    """Constant-time verification of a hex (optionally ``sha256=``-prefixed) signature.

    Returns ``False`` for any malformed input rather than raising, so a malformed
    signature is indistinguishable (in control flow and timing) from a wrong one.
    """

    if not isinstance(provided_signature, str):
        return False
    provided = (
        provided_signature.split("=", 1)[1]
        if provided_signature.startswith("sha256=")
        else provided_signature
    )
    expected = compute_signature(secret, raw_body)
    # compare_digest is constant-time for equal-length inputs; feeding it the hex
    # strings (fixed 64 chars) keeps length side-channels out of the comparison.
    return hmac.compare_digest(expected, provided.strip().lower())


class HmacVerifier:
    """Resolves the per-source secret and verifies a delivery.

    An unknown source and a bad signature both return ``False`` with no observable
    difference (spec §1.5: "no ack that distinguishes bad signature from unknown
    repo").
    """

    def __init__(self, secrets_by_source: dict[str, bytes]) -> None:
        self._secrets = dict(secrets_by_source)

    def verify(self, source: str, raw_body: bytes, provided_signature: str) -> bool:
        secret = self._secrets.get(source)
        if secret is None:
            # Still perform a comparison against a dummy secret so an unknown source
            # costs the same as a known one with a bad signature.
            verify_signature(b"\x00" * 32, raw_body, provided_signature)
            return False
        return verify_signature(secret, raw_body, provided_signature)
