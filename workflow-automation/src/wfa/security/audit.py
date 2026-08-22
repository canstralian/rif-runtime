"""Append-only hash-chained audit trail (spec §4.8).

Each record embeds the SHA-256 of the previous record, so any tampering with an
earlier line invalidates every subsequent line. ``classification_basis`` is a
required field on run records: an audit trail that records a run as TRUSTED without
recording *why* cannot support incident review.

Event payload *bodies* are never stored inline: only a salted hash is retained here
(full bodies live under a separate, shorter-retention store — out of scope for this
module, which is the long-lived widely-read artifact).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from pathlib import Path
from typing import Any

_GENESIS = "0" * 64


def _canonical(record: dict[str, Any]) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")


class AuditLog:
    def __init__(self, path: str | os.PathLike[str], payload_salt: bytes = b"wfa-audit") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._salt = payload_salt
        self._lock = threading.Lock()
        self._last_hash = self._recover_tail()

    def _recover_tail(self) -> str:
        if not self._path.exists():
            return _GENESIS
        last = _GENESIS
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    last = json.loads(line)["hash"]
        return last

    def payload_digest(self, raw_body: bytes) -> str:
        """Salted hash of an event body for storage in lieu of the body itself."""

        return hmac.new(self._salt, raw_body, hashlib.sha256).hexdigest()

    def append(self, entry: dict[str, Any]) -> str:
        """Append one record, chaining it to the prior hash. Returns the new hash."""

        with self._lock:
            record = dict(entry)
            record["prev_hash"] = self._last_hash
            digest = hashlib.sha256(self._last_hash.encode() + _canonical(record)).hexdigest()
            record["hash"] = digest
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
            self._last_hash = digest
            return digest

    def verify(self) -> bool:
        """Recompute the chain from genesis; return True iff intact."""

        prev = _GENESIS
        if not self._path.exists():
            return True
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                stored = record.pop("hash")
                if record.get("prev_hash") != prev:
                    return False
                expected = hashlib.sha256(prev.encode() + _canonical(record)).hexdigest()
                if expected != stored:
                    return False
                prev = stored
        return True

    @property
    def tail_hash(self) -> str:
        return self._last_hash
