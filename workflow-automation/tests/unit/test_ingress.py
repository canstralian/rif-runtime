"""Ingress: HMAC verify, replay window, constant-shape responses (spec §4.3, §8.4)."""

from __future__ import annotations

from wfa.ingress.hmac_verify import HmacVerifier, compute_signature, verify_signature
from wfa.ingress.replay import ReplayWindow
from wfa.ingress.server import WebhookIngress

SECRET = b"per-source-secret"


def test_verify_signature_roundtrip():
    body = b'{"a":1}'
    sig = compute_signature(SECRET, body)
    assert verify_signature(SECRET, body, sig)
    assert verify_signature(SECRET, body, "sha256=" + sig)


def test_verify_signature_rejects_tamper():
    body = b'{"a":1}'
    sig = compute_signature(SECRET, body)
    assert not verify_signature(SECRET, body + b" ", sig)
    assert not verify_signature(SECRET, body, sig[:-1] + "0")


def test_verify_signature_rejects_non_string():
    assert not verify_signature(SECRET, b"x", None)  # type: ignore[arg-type]


def test_hmac_verifier_unknown_source_is_false():
    v = HmacVerifier({"install-1": SECRET})
    body = b"x"
    assert not v.verify("unknown", body, compute_signature(SECRET, body))
    assert v.verify("install-1", body, compute_signature(SECRET, body))


def test_replay_rejects_duplicate_and_skew():
    rw = ReplayWindow(window_s=100, skew_s=10)
    assert rw.check("d1", 1000.0, 1000.0).ok
    # duplicate
    dup = rw.check("d1", 1000.0, 1000.0)
    assert not dup.ok and dup.rule_id == "HB-2"
    # skew
    skew = rw.check("d2", 500.0, 1000.0)
    assert not skew.ok and "skew" in skew.reason


def test_replay_rejects_missing_id():
    rw = ReplayWindow()
    assert not rw.check("", 1.0, 1.0).ok


def test_replay_evicts_stale_entries():
    rw = ReplayWindow(window_s=10, skew_s=1000)
    rw.check("d1", 0.0, 0.0)
    # Far in the future -> d1 evicted, so the same id is accepted again.
    assert rw.check("d1", 1000.0, 1000.0).ok


def _ingress(enqueue, secret_ok=True, clock=lambda: 1000.0):
    v = HmacVerifier({"install-1": SECRET})
    rw = ReplayWindow(window_s=1000, skew_s=300)
    return WebhookIngress(v, rw, enqueue, max_payload_bytes=1000, clock=clock)


def test_ingress_happy_path_enqueues_then_acks():
    seen = []
    ing = _ingress(lambda job: seen.append(job) or True)
    body = b'{"pr":1}'
    sig = compute_signature(SECRET, body)
    res = ing.handle("install-1", body, sig, "d1", 1000.0)
    assert res.accepted and res.status == 202
    assert len(seen) == 1
    assert WebhookIngress.public_body(res) == {"status": "received"}


def test_ingress_bad_signature_is_constant_shape():
    ing = _ingress(lambda job: True)
    res = ing.handle("install-1", b'{"pr":1}', "sha256=bad", "d1", 1000.0)
    assert not res.accepted and res.status == 202
    assert WebhookIngress.public_body(res) == {"status": "received"}


def test_ingress_oversize_rejected_before_parse():
    ing = _ingress(lambda job: True)
    big = b"x" * 2000
    sig = compute_signature(SECRET, big)
    res = ing.handle("install-1", big, sig, "d1", 1000.0)
    assert not res.accepted


def test_ingress_enqueue_failure_returns_503():
    ing = _ingress(lambda job: False)
    body = b'{"pr":1}'
    sig = compute_signature(SECRET, body)
    res = ing.handle("install-1", body, sig, "d1", 1000.0)
    assert res.status == 503 and not res.accepted


def test_ingress_bad_json_rejected():
    ing = _ingress(lambda job: True)
    body = b"not json"
    sig = compute_signature(SECRET, body)
    res = ing.handle("install-1", body, sig, "d1", 1000.0)
    assert not res.accepted and res.rule_id == "PARSE"


def test_ingress_replay_rejected():
    ing = _ingress(lambda job: True)
    body = b'{"pr":1}'
    sig = compute_signature(SECRET, body)
    assert ing.handle("install-1", body, sig, "d1", 1000.0).accepted
    assert not ing.handle("install-1", body, sig, "d1", 1000.0).accepted
