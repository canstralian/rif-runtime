import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

try:  # POSIX only; absent on Windows.
    import fcntl
except ImportError:  # pragma: no cover - platform dependent
    fcntl = None  # type: ignore[assignment]

from ..audit import GENESIS_HASH, AuditRecord, utc_now_iso
from ..security import normalize_for_json

CHAIN_KEY = "_chain"


class JsonlStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def count(self, rows: list[dict[str, Any]] | None = None) -> int:
        return len(self.read_all() if rows is None else rows)

    def count_by(
        self, field: str, rows: list[dict[str, Any]] | None = None
    ) -> dict[str, int]:
        """Tally ``field`` across the log, or across an already-read snapshot.

        Passing ``rows`` lets a caller that needs several summaries derive them
        all from one read. Separate reads of an append-only log that is being
        written concurrently can disagree with each other, so a summary built
        from several of them is not a snapshot of anything.
        """
        out: dict[str, int] = {}
        for row in self.read_all() if rows is None else rows:
            key = row.get(field, "unknown")
            out[key] = out.get(key, 0) + 1
        return out


class ChainVerification:
    """Outcome of verifying a hash-chained log.

    ``verified`` covers the chained portion only. ``unchained_leading`` counts
    rows written before chaining was introduced: they are reported, never
    silently treated as verified.
    """

    def __init__(
        self,
        verified: bool,
        chained_rows: int,
        unchained_leading: int,
        broken_at: int | None = None,
    ) -> None:
        self.verified = verified
        self.chained_rows = chained_rows
        self.unchained_leading = unchained_leading
        self.broken_at = broken_at

    def as_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "chained_rows": self.chained_rows,
            "unchained_leading": self.unchained_leading,
            "broken_at": self.broken_at,
        }


class HashChainedJsonlStore(JsonlStore):
    """Append-only JSONL whose rows are linked by a SHA-256 hash chain.

    Each row carries a ``_chain`` envelope holding the record's ``event_id``,
    ``timestamp``, the ``previous_hash`` it was written against, and its own
    ``current_hash``. Editing any earlier row changes its hash and breaks every
    link after it, which is what makes the log tamper-evident rather than
    merely append-only.

    The payload is normalised (``security.normalize_for_json``) *before* being
    both hashed and written, so the bytes on disk are the bytes that were
    hashed. Writing via ``json.dumps(default=str)`` instead would serialise a
    datetime as ``"... 09:55:37+00:00"`` while the digest covered
    ``"...T09:55:37+00:00"``, and verification could never succeed.

    Concurrent writers are the case this has to get right. ``rif check`` builds
    its own ``RIFRuntime`` against the same ``RIF_DATA_DIR`` as a running
    ``rif serve``, so two processes appending to one log is ordinary use, not an
    edge case. Caching the tail hash for the object's lifetime forked the chain
    the moment that happened, and a forked chain reports ``verified: false``
    forever -- indistinguishable from tampering, which is the one thing this
    class exists to detect.

    So the tail is read back under an exclusive ``flock`` on every append, and
    the link is computed inside that lock. The read seeks from the end rather
    than parsing the file, so it stays cheap as the log grows. Within a process
    ``RIFRuntime`` also serialises appends under its own lock; this covers the
    cross-process case that one cannot.

    ``fcntl`` is POSIX-only. Without it (Windows) the lock degrades to a no-op
    and the single-writer assumption returns; the runtime targets Linux.
    """

    #: Bytes to read back when locating the final line. One row is ~1 KB.
    _TAIL_WINDOW = 65536

    @contextmanager
    def _locked(self) -> Iterator[IO[bytes]]:
        """Open for append with an exclusive advisory lock held throughout.

        Binary, not text. The tail is located by seeking to a byte offset
        counted back from the end, and a text handle decodes from wherever it
        lands: land mid-character and the read raises ``UnicodeDecodeError``.
        Byte offsets are only meaningful on a binary handle, so the decode
        happens explicitly below, on a slice already known to be a whole record.

        The flush before unlocking is load-bearing, not tidiness. Python buffers
        the write, and closing the handle is what flushes it -- which happens
        *after* the lock is released. The next process would then take the lock
        and read a tail that does not yet include the row just written, forking
        the chain exactly as the lifetime cache did. Holding the lock until the
        bytes are in the page cache is what makes the serialisation real.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab+") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield handle
            finally:
                # Not fsync: the page cache is enough for another *process* to
                # read what was written. Surviving a machine crash is a
                # different (and much more expensive) guarantee, and the log
                # does not claim it.
                handle.flush()
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _read_locked(self) -> Iterator[IO[bytes]]:
        """Open for reading with a shared advisory lock held throughout.

        Serialising writers is only half of it. A writer holds ``LOCK_EX``
        across the whole append, but an unlocked reader can still land between
        the write syscalls Python issues for a large row and parse a half-
        written line -- ``json.JSONDecodeError``, surfacing as a 500 from
        ``GET /v1/audit``. The window is negligible for a ~1 KB row, but
        ``target`` on ``POST /v1/policy/evaluate`` is unbounded, which is the
        same reason the tail read cannot assume a fixed size.

        A shared lock excludes writers without excluding other readers.
        """
        with self.path.open("rb") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            try:
                yield handle
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def read_all(self) -> list[dict[str, Any]]:
        """Read every row under a shared lock, so no row is seen half-written."""
        if not self.path.exists():
            return []
        with self._read_locked() as handle:
            text = handle.read().decode("utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def _tail_hash(self, handle: IO[bytes]) -> str:
        """Hash the next row must link to, read from the end of the open file.

        Must be called with the lock held: the value is only true for as long
        as no other writer can append.

        The window is a starting guess, not a bound. Reading a fixed number of
        bytes back from the end and taking the last line assumes the final
        record fits in that many bytes -- and ``target`` on
        ``POST /v1/policy/evaluate`` is an unbounded string, so it need not. A
        record larger than the window left the read starting mid-record, the
        parse failed, and the next append linked to genesis: a forked chain,
        reported forever after as a break indistinguishable from tampering.

        So the window doubles until the slice provably contains a record
        boundary -- a newline before the final record, or the start of the file.
        Ordinary rows are ~1 KB, so the first read almost always suffices; the
        growth costs anything only on the rows that would otherwise be wrong.

        Blank lines are skipped rather than treated as the tail. ``read_all``
        ignores them, so taking one as the tail would leave readers and writers
        disagreeing about where the chain ends: a single whitespace-only line
        appended after a valid row sent the next append back to genesis and
        forked the chain, which is the same failure the window fix removed.
        """
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        if size == 0:
            return GENESIS_HASH

        window = self._TAIL_WINDOW
        last = b""
        while True:
            start = max(0, size - window)
            handle.seek(start)
            lines = handle.read(size - start).split(b"\n")
            # Unless the slice begins at the file start, its first element is
            # the tail of a record that began before the window. Dropping it
            # can only cost an extra doubling, never correctness.
            complete = lines if start == 0 else lines[1:]

            found = next((line for line in reversed(complete) if line.strip()), None)
            if found is not None:
                last = found
                break
            if start == 0:
                # Nothing but blank lines in the whole file.
                return GENESIS_HASH
            window *= 2

        try:
            chain = json.loads(last.decode("utf-8")).get(CHAIN_KEY)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            # `last` is a complete record by construction, so this is a
            # genuinely damaged final line (a torn write), not a short read.
            # Returning genesis would start a second chain over the damage and
            # report it as tampering forever; read_all() cannot parse this row
            # either. Fail loudly rather than silently forking.
            raise ValueError(
                f"final row of {self.path} is not valid JSON; the log is "
                "damaged and appending would fork the chain"
            ) from exc
        if isinstance(chain, dict) and "current_hash" in chain:
            return str(chain["current_hash"])
        # Final row predates chaining: start the chain from genesis. verify()
        # counts those rows as unchained_leading rather than verified.
        return GENESIS_HASH

    def append(self, record: dict[str, Any]) -> None:
        payload = normalize_for_json(record)
        if CHAIN_KEY in payload:
            # The envelope is written over the payload below, but the hash was
            # computed *including* the caller's value -- and verify() strips
            # CHAIN_KEY before recomputing. The digests could never agree, so an
            # untampered record would report a broken chain, which is exactly
            # the signal this class exists to make trustworthy. Reject the
            # collision rather than silently produce an unverifiable row.
            raise ValueError(
                f"{CHAIN_KEY!r} is reserved for chain metadata and cannot "
                "appear in a record"
            )
        with self._locked() as handle:
            entry = AuditRecord(
                event_id=AuditRecord.new_event_id(),
                timestamp=utc_now_iso(),
                payload=payload,
                previous_hash=self._tail_hash(handle),
            )
            row = dict(payload)
            row[CHAIN_KEY] = {
                "event_id": entry.event_id,
                "timestamp": entry.timestamp,
                "previous_hash": entry.previous_hash,
                "current_hash": entry.current_hash,
            }
            handle.seek(0, os.SEEK_END)
            # ensure_ascii=False so the file holds real UTF-8 rather than
            # \uXXXX escapes. The digest is computed over the payload dict, not
            # these bytes, so both forms verify identically and json.loads reads
            # either -- but escaping everything to ASCII meant the binary tail
            # read above could never actually meet a multi-byte character, so
            # the hazard it exists for was untestable through this class.
            handle.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))

    def verify(self, rows: list[dict[str, Any]] | None = None) -> ChainVerification:
        """Recompute every link and report where, if anywhere, it breaks.

        Accepts an already-read snapshot for the same reason ``count_by`` does.
        """
        rows = self.read_all() if rows is None else rows
        previous_hash = GENESIS_HASH
        chained = 0
        unchained_leading = 0
        started = False

        for index, row in enumerate(rows):
            chain = row.get(CHAIN_KEY)
            if not isinstance(chain, dict):
                if started:
                    # An unchained row after chaining began: either a rollback
                    # to the plain store or a row spliced in by hand.
                    return ChainVerification(False, chained, unchained_leading, index)
                unchained_leading += 1
                continue

            started = True
            payload = {key: value for key, value in row.items() if key != CHAIN_KEY}
            recomputed = AuditRecord(
                event_id=str(chain.get("event_id", "")),
                timestamp=str(chain.get("timestamp", "")),
                payload=payload,
                previous_hash=str(chain.get("previous_hash", "")),
            )
            linked = chain.get("previous_hash") == previous_hash
            intact = chain.get("current_hash") == recomputed.current_hash
            if not (linked and intact):
                return ChainVerification(False, chained, unchained_leading, index)

            previous_hash = str(chain["current_hash"])
            chained += 1

        return ChainVerification(True, chained, unchained_leading)
