"""Input normalisation (spec §4.4, vector E).

Part of the input pipeline: authenticate -> size-bound -> parse -> schema-validate ->
**normalise (NFC, control/bidi strip)** -> classify. Normalisation removes bidi
override and other Unicode format/control characters that are used to smuggle
instructions past human and machine readers, and applies NFC so visually-identical
strings compare identically.

Newlines and tabs are preserved (diffs and code content need them); all other C0/C1
control characters and Unicode ``Cf`` (format) characters — including the bidi
overrides U+202A–202E and isolates U+2066–2069 — are stripped.
"""

from __future__ import annotations

import unicodedata
from typing import Any

_KEEP = {"\n", "\t"}


def normalize_text(value: str) -> str:
    nfc = unicodedata.normalize("NFC", value)
    out_chars = []
    for ch in nfc:
        if ch in _KEEP:
            out_chars.append(ch)
            continue
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf", "Co", "Cs"):
            continue  # strip control / format / private-use / surrogate
        out_chars.append(ch)
    return "".join(out_chars)


def normalize_tree(obj: Any) -> Any:
    """Recursively normalise all strings within a JSON-like object."""

    if isinstance(obj, str):
        return normalize_text(obj)
    if isinstance(obj, dict):
        return {
            normalize_text(k) if isinstance(k, str) else k: normalize_tree(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [normalize_tree(v) for v in obj]
    return obj
