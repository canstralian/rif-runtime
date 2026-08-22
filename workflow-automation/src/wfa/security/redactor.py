"""Output redaction (spec §4.4, §4.5).

The redactor sits on the write path of every emitter. Credentials must never enter
logs, metric labels, trace attributes, step outputs, run records, audit fields, or
dead-letter payloads. In addition to known credential *formats*, high-entropy
strings are redacted defensively.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

_REDACTED = "***REDACTED***"

# Known credential formats. Order matters only for readability.
_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub tokens
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),  # PEM keys
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"(?i)\b(?:secret|token|password|passwd|api[_-]?key)\b\s*[:=]\s*\S+"),
]

# Any long unbroken token that looks high-entropy (e.g. a base64/hex secret).
_TOKEN = re.compile(r"[A-Za-z0-9+/=_\-]{24,}")


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


class Redactor:
    def __init__(self, entropy_threshold: float = 4.0, min_token_len: int = 24) -> None:
        self._threshold = entropy_threshold
        self._min_len = min_token_len
        self.redactions_applied = 0

    def _redact_str(self, value: str) -> str:
        redacted = value
        for pat in _PATTERNS:
            redacted, n = pat.subn(_REDACTED, redacted)
            self.redactions_applied += n

        def _maybe(m: re.Match[str]) -> str:
            tok = m.group(0)
            if len(tok) >= self._min_len and _shannon_entropy(tok) >= self._threshold:
                self.redactions_applied += 1
                return _REDACTED
            return tok

        return _TOKEN.sub(_maybe, redacted)

    def scrub(self, obj: Any) -> Any:
        """Recursively redact strings within an arbitrary JSON-like object."""

        if isinstance(obj, str):
            return self._redact_str(obj)
        if isinstance(obj, dict):
            return {k: self.scrub(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self.scrub(v) for v in obj]
        return obj
