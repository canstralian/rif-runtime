import json
from dataclasses import replace
from pathlib import Path

import pytest

from rif_runtime.audit import GENESIS_HASH, append_record, verify_chain
from rif_runtime.configuration.policies import PolicyRule
from rif_runtime.runtime import RIFRuntime
from rif_runtime.schemas import PolicyRequest
from rif_runtime.storage.jsonl import CHAIN_KEY, HashChainedJsonlStore, JsonlStore


def test_empty_chain_is_valid():
    assert verify_chain([])


def test_append_record_links_to_genesis_hash():
    record = append_record(
        [],
        {"decision": "ALLOW"},
        event_id="evt-1",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    assert record.previous_hash == GENESIS_HASH
    assert len(record.current_hash) == 64


def test_multiple_records_form_valid_chain():
    chain = []
    first = append_record(
        chain,
        {"decision": "ALLOW"},
        event_id="evt-1",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    chain.append(first)

    second = append_record(
        chain,
        {"decision": "DENY"},
        event_id="evt-2",
        timestamp="2026-01-01T00:01:00+00:00",
    )
    chain.append(second)

    assert second.previous_hash == first.current_hash
    assert verify_chain(chain)


def test_payload_tampering_breaks_chain():
    chain = []
    first = append_record(
        chain,
        {"decision": "ALLOW"},
        event_id="evt-1",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    chain.append(first)

    second = append_record(
        chain,
        {"decision": "DENY"},
        event_id="evt-2",
        timestamp="2026-01-01T00:01:00+00:00",
    )
    chain.append(second)

    tampered = replace(first, payload={"decision": "DENY"})
    assert not verify_chain([tampered, second])


def test_previous_hash_tampering_breaks_chain():
    chain = []
    first = append_record(
        chain,
        {"decision": "ALLOW"},
        event_id="evt-1",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    chain.append(first)

    second = append_record(
        chain,
        {"decision": "DENY"},
        event_id="evt-2",
        timestamp="2026-01-01T00:01:00+00:00",
    )
    chain.append(second)

    tampered = replace(second, previous_hash="x" * 64)
    assert not verify_chain([first, tampered])


# --- hash-chained decision log -----------------------------------------------
#
# audit.py implemented this chain from the start, but nothing in src/ used it:
# decisions.jsonl was append-only, not tamper-evident. These cover the wiring.


def _decision(target: str = "https://api.anthropic.com") -> PolicyRequest:
    return PolicyRequest(actor="agent:test", action="http.request", target=target)


def _allowing_runtime(tmp_path) -> RIFRuntime:
    runtime = RIFRuntime(data_dir=tmp_path)
    runtime.policy_store.upsert(
        PolicyRule(
            id="allow_test_traffic",
            effect="allow",
            action="http.request",
            target="*",
            reason="chain tests",
        )
    )
    return runtime


def test_appended_rows_carry_a_chain_envelope(tmp_path):
    store = HashChainedJsonlStore(tmp_path / "log.jsonl")
    store.append({"event": "first"})
    store.append({"event": "second"})

    rows = store.read_all()
    assert [row["event"] for row in rows] == ["first", "second"]
    assert rows[0][CHAIN_KEY]["previous_hash"] == GENESIS_HASH
    assert rows[1][CHAIN_KEY]["previous_hash"] == rows[0][CHAIN_KEY]["current_hash"]


def test_untouched_chain_verifies(tmp_path):
    store = HashChainedJsonlStore(tmp_path / "log.jsonl")
    for index in range(5):
        store.append({"event": index})

    result = store.verify()
    assert result.verified is True
    assert result.chained_rows == 5
    assert result.unchained_leading == 0
    assert result.broken_at is None


def test_editing_a_payload_breaks_verification(tmp_path):
    """The whole point: a silently edited row must be detectable."""
    path = tmp_path / "log.jsonl"
    store = HashChainedJsonlStore(path)
    for index in range(4):
        store.append({"event": index, "decision": "deny"})

    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[1]["decision"] = "allow"  # flip a denial to an allow, leave hashes alone
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    result = HashChainedJsonlStore(path).verify()
    assert result.verified is False
    assert result.broken_at == 1


def test_deleting_a_row_breaks_verification(tmp_path):
    path = tmp_path / "log.jsonl"
    store = HashChainedJsonlStore(path)
    for index in range(4):
        store.append({"event": index})

    rows = [json.loads(line) for line in path.read_text().splitlines()]
    del rows[1]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    result = HashChainedJsonlStore(path).verify()
    assert result.verified is False
    assert result.broken_at == 1


def test_reordering_rows_breaks_verification(tmp_path):
    path = tmp_path / "log.jsonl"
    store = HashChainedJsonlStore(path)
    for index in range(4):
        store.append({"event": index})

    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[1], rows[2] = rows[2], rows[1]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    assert HashChainedJsonlStore(path).verify().verified is False


def test_legacy_unchained_rows_are_reported_not_silently_verified(tmp_path):
    """An existing decisions.jsonl predates chaining; it must still load."""
    path = tmp_path / "log.jsonl"
    legacy = JsonlStore(path)
    legacy.append({"event": "old-1"})
    legacy.append({"event": "old-2"})

    store = HashChainedJsonlStore(path)
    store.append({"event": "new-1"})

    result = store.verify()
    assert result.verified is True
    assert result.unchained_leading == 2
    assert result.chained_rows == 1
    assert len(store.read_all()) == 3


def test_unchained_row_appended_after_chaining_is_a_break(tmp_path):
    path = tmp_path / "log.jsonl"
    store = HashChainedJsonlStore(path)
    store.append({"event": "chained"})
    JsonlStore(path).append({"event": "spliced-in-by-hand"})

    result = HashChainedJsonlStore(path).verify()
    assert result.verified is False
    assert result.broken_at == 1


def test_chain_survives_reopening_the_store(tmp_path):
    """The cached tail hash must be recovered from disk, not restarted."""
    path = tmp_path / "log.jsonl"
    HashChainedJsonlStore(path).append({"event": "before-restart"})
    HashChainedJsonlStore(path).append({"event": "after-restart"})

    result = HashChainedJsonlStore(path).verify()
    assert result.verified is True
    assert result.chained_rows == 2


def test_recorded_decisions_produce_a_verifiable_chain(tmp_path):
    """End to end: real decisions, hashed payloads, verified after the fact.

    Guards the serialisation trap specifically -- PolicyDecision carries a
    datetime, and hashing an isoformat string while persisting a str()-formatted
    one would make verification impossible.
    """
    runtime = _allowing_runtime(tmp_path)
    runtime.evaluate(_decision())
    runtime.evaluate(_decision("https://blocked.example.net"))

    result = runtime.verify_decision_chain()
    assert result["verified"] is True
    assert result["chained_rows"] == 2
    assert result["unchained_leading"] == 0


def test_tampering_with_a_recorded_decision_is_detected(tmp_path):
    runtime = _allowing_runtime(tmp_path)
    runtime.evaluate(_decision())

    path = runtime.decisions_path
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["actor"] = "agent:someone-else"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    assert RIFRuntime(data_dir=tmp_path).verify_decision_chain()["verified"] is False


def test_audit_summary_reports_chain_state(tmp_path):
    runtime = _allowing_runtime(tmp_path)
    runtime.evaluate(_decision())

    chain = runtime.audit_summary()["decision_chain"]
    assert chain["verified"] is True
    assert chain["chained_rows"] == 1


# --- concurrent writers ------------------------------------------------------
#
# `rif check` builds its own RIFRuntime against the same RIF_DATA_DIR as a
# running `rif serve`, so two processes appending to one decision log is
# ordinary use. Caching the tail hash for an object's lifetime forked the chain
# the moment that happened, and a forked chain reads as tampering forever.


def test_two_runtimes_interleaving_appends_keep_one_chain(tmp_path):
    """The in-process case: two RIFRuntime objects over the same directory."""
    first = _allowing_runtime(tmp_path)
    second = RIFRuntime(data_dir=tmp_path)

    first.evaluate(_decision("https://a.example.com"))
    second.evaluate(_decision("https://b.example.com"))
    first.evaluate(_decision("https://c.example.com"))
    second.evaluate(_decision("https://d.example.com"))

    result = first.verify_decision_chain()
    assert result["verified"] is True, result
    assert result["chained_rows"] == 4


def test_two_stores_interleaving_appends_keep_one_chain(tmp_path):
    path = tmp_path / "log.jsonl"
    left = HashChainedJsonlStore(path)
    right = HashChainedJsonlStore(path)

    for index in range(5):
        (left if index % 2 == 0 else right).append({"event": index})

    result = left.verify()
    assert result.verified is True
    assert result.chained_rows == 5


def test_separate_processes_appending_concurrently_keep_one_chain(tmp_path):
    """The case the lock exists for: real OS processes, no shared memory.

    Uses flock, so this is a genuine cross-process assertion rather than a
    threading one. Skipped where fcntl is unavailable (Windows), which is the
    platform where the store documents a single-writer assumption.
    """
    import subprocess
    import sys

    pytest.importorskip("fcntl")

    path = tmp_path / "log.jsonl"
    writer = tmp_path / "writer.py"
    writer.write_text(
        "import sys\n"
        "sys.path.insert(0, sys.argv[3])\n"
        "from rif_runtime.storage.jsonl import HashChainedJsonlStore\n"
        "store = HashChainedJsonlStore(sys.argv[1])\n"
        "for i in range(40):\n"
        "    store.append({'writer': sys.argv[2], 'i': i})\n",
        encoding="utf-8",
    )

    src = str(Path(__file__).resolve().parent.parent / "src")
    processes = [
        subprocess.Popen(
            [sys.executable, str(writer), str(path), name, src],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for name in ("alpha", "beta", "gamma")
    ]
    for process in processes:
        _, stderr = process.communicate(timeout=60)
        assert process.returncode == 0, stderr.decode()

    result = HashChainedJsonlStore(path).verify()
    assert result.verified is True, (
        f"chain broke at row {result.broken_at} under concurrent writers"
    )
    assert result.chained_rows == 120


def test_tail_is_read_from_disk_not_from_a_cached_value(tmp_path):
    """A store must not assume it was the last writer."""
    path = tmp_path / "log.jsonl"
    store = HashChainedJsonlStore(path)
    store.append({"event": "mine"})

    HashChainedJsonlStore(path).append({"event": "someone else's"})
    store.append({"event": "mine again"})

    rows = store.read_all()
    assert rows[2][CHAIN_KEY]["previous_hash"] == rows[1][CHAIN_KEY]["current_hash"]
    assert store.verify().verified is True


def test_record_carrying_the_reserved_chain_key_is_rejected(tmp_path):
    """A colliding field name must not produce an unverifiable row.

    The envelope is written over the payload, but the hash was computed
    including the caller's value and verify() strips CHAIN_KEY before
    recomputing -- so the digests could never agree and an untampered record
    reported a broken chain, which is precisely the signal this class exists to
    make trustworthy.
    """
    store = HashChainedJsonlStore(tmp_path / "log.jsonl")
    store.append({"event": "fine"})

    with pytest.raises(ValueError, match="reserved"):
        store.append({"event": "collides", CHAIN_KEY: {"anything": 1}})

    # The rejection must not corrupt the log or the chain.
    result = store.verify()
    assert result.verified is True
    assert result.chained_rows == 1

    store.append({"event": "still works"})
    assert store.verify().chained_rows == 2


def test_deleting_a_middle_row_breaks_the_chain_but_truncation_does_not(tmp_path):
    """Pins the asymmetry SECURITY.md documents.

    Removing a row from the middle orphans everything after it. Removing a
    trailing suffix leaves every remaining record internally consistent, so
    verification cannot see it -- that is the truncation limitation, and the
    docs must not claim otherwise.
    """
    path = tmp_path / "log.jsonl"
    store = HashChainedJsonlStore(path)
    for index in range(5):
        store.append({"i": index})
    rows = [json.loads(line) for line in path.read_text().splitlines()]

    path.write_text("\n".join(json.dumps(r) for r in rows[:3]) + "\n")
    truncated = HashChainedJsonlStore(path).verify()
    assert truncated.verified is True, "truncation is undetectable by design"
    assert truncated.chained_rows == 3

    path.write_text("\n".join(json.dumps(r) for r in rows[:2] + rows[3:]) + "\n")
    gapped = HashChainedJsonlStore(path).verify()
    assert gapped.verified is False
    assert gapped.broken_at == 2


def test_a_row_larger_than_the_tail_window_does_not_fork_the_chain(tmp_path):
    """The tail read must find the record boundary, not a fixed byte count.

    `target` on POST /v1/policy/evaluate is an unbounded string, so a decision
    row can exceed the tail window. Reading a fixed slice back from the end
    then started mid-record; the parse failed, and the next append linked to
    genesis instead of to the oversized row -- a fork reported forever after as
    a break indistinguishable from tampering.
    """
    store = HashChainedJsonlStore(tmp_path / "log.jsonl")
    store.append({"event": "before"})
    store.append({"target": "X" * (HashChainedJsonlStore._TAIL_WINDOW + 4096)})
    store.append({"event": "after"})

    result = store.verify()
    assert result.verified is True
    assert result.chained_rows == 3

    rows = store.read_all()
    assert rows[2][CHAIN_KEY]["previous_hash"] == rows[1][CHAIN_KEY]["current_hash"]


def test_consecutive_oversized_rows_grow_the_window_as_far_as_needed(tmp_path):
    """One doubling is not enough when the final record dwarfs the window."""
    store = HashChainedJsonlStore(tmp_path / "log.jsonl")
    store.append({"event": "first"})
    store.append({"target": "Y" * (HashChainedJsonlStore._TAIL_WINDOW * 5)})
    store.append({"event": "last"})

    assert store.verify().verified is True
    assert store.verify().chained_rows == 3


def test_a_multibyte_payload_at_the_window_boundary_still_links(tmp_path):
    """Byte offsets must not land the reader mid-character.

    A text handle decodes from wherever the seek lands, so a multi-byte
    character straddling the window boundary raised UnicodeDecodeError instead
    of returning the tail. The read is binary and decodes a whole record.
    """
    store = HashChainedJsonlStore(tmp_path / "log.jsonl")
    store.append({"event": "before"})
    # json.dumps escapes non-ASCII by default, so put the multi-byte characters
    # somewhere the bytes on disk are genuinely multi-byte: the raw file is
    # written as UTF-8, and the boundary walk must not care either way.
    store.append({"target": "é" * HashChainedJsonlStore._TAIL_WINDOW})
    store.append({"event": "after"})

    assert store.verify().verified is True
    assert store.read_all()[1]["target"].startswith("é")


def test_a_torn_final_line_is_reported_rather_than_silently_forked(tmp_path):
    """A damaged tail must not quietly start a second chain over the damage."""
    path = tmp_path / "log.jsonl"
    store = HashChainedJsonlStore(path)
    store.append({"event": "one"})
    store.append({"event": "two"})

    # Simulate a write torn by a crash: the final row is cut mid-JSON.
    with path.open("r+", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
        handle.seek(0)
        handle.truncate()
        handle.write(lines[0] + "\n" + lines[1][: len(lines[1]) // 2] + "\n")

    with pytest.raises(ValueError, match="damaged"):
        store.append({"event": "three"})
