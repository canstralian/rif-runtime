"""Audit chain edge branches: blank lines, tail recovery, and prev-hash tampering."""

from __future__ import annotations

from wfa.security.audit import AuditLog


def test_verify_skips_blank_lines(tmp_path):
    path = tmp_path / "a.jsonl"
    log = AuditLog(path)
    log.append({"run_id": "r1"})
    # Inject a blank line; verify must skip it, not fail.
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n")
    log2 = AuditLog(path)  # recover_tail also skips the blank line
    log2.append({"run_id": "r2"})
    assert log2.verify()


def test_verify_detects_prev_hash_break(tmp_path):
    path = tmp_path / "a.jsonl"
    log = AuditLog(path)
    log.append({"run_id": "r1"})
    log.append({"run_id": "r2"})
    lines = path.read_text().splitlines()
    # Delete the first record: the second record's prev_hash no longer matches genesis.
    path.write_text(lines[1] + "\n")
    assert not AuditLog(path).verify()
