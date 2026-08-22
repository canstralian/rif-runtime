"""Queue: durable enqueue, fencing tokens, shedding, retry, dead-letter (spec §5)."""

from __future__ import annotations

import random

import pytest

from wfa.queue.broker import Broker, Job, QueueFull
from wfa.queue.deadletter import DeadLetterStore
from wfa.queue.retry import RetryPolicy, backoff_delays
from wfa.shared.enums import Profile


def test_enqueue_lease_commit_roundtrip():
    b = Broker()
    assert b.enqueue(Job("d1", {"x": 1}))
    lease = b.lease()
    assert lease is not None and lease.job.delivery_id == "d1"
    assert b.commit(lease)


def test_stale_fencing_token_rejected():
    b = Broker()
    b.enqueue(Job("d1", {}))
    first = b.lease()
    # Simulate a partition producing a duplicate lease with a fresh (higher) token.
    b.requeue(first.job)
    second = b.lease()
    assert b.commit(second)
    # The old lease's fencing token is now stale and cannot commit.
    assert not b.commit(first)


def test_priority_ordering():
    b = Broker()
    b.enqueue(Job("low", {}, priority=200))
    b.enqueue(Job("high", {}, priority=1))
    assert b.lease().job.delivery_id == "high"


def test_ceiling_sheds_untrusted_first():
    b = Broker(queue_depth_ceiling=2)
    b.enqueue(Job("t1", {}, profile=Profile.TRUSTED, priority=10))
    b.enqueue(Job("u1", {}, profile=Profile.UNTRUSTED, priority=10))
    with pytest.raises(QueueFull) as e:
        b.enqueue(Job("t2", {}, profile=Profile.TRUSTED, priority=10))
    # The shed victim is the UNTRUSTED job, surfaced for dead-lettering with cause.
    assert e.value.args[0] == "u1"


def test_backoff_delays_are_bounded():
    delays = backoff_delays(random.Random(0))
    assert len(delays) == 3
    for base, d in zip((2.0, 8.0, 32.0), delays):
        assert 0.8 * base <= d <= 1.2 * base


def test_retry_non_idempotent_uncertain_is_indeterminate():
    p = RetryPolicy()
    d = p.decide(idempotent=False, attempts=0, uncertain_outcome=True)
    assert d.indeterminate and not d.retry


def test_retry_idempotent_retries_until_ceiling():
    p = RetryPolicy(max_attempts=3)
    assert p.decide(idempotent=True, attempts=0, uncertain_outcome=True).retry
    assert not p.decide(idempotent=True, attempts=3, uncertain_outcome=True).retry


def test_dead_letter_store_records_cause():
    dl = DeadLetterStore()
    dl.add("d1", "shed-untrusted", rule_id=None, context={"repo": "r"})
    assert len(dl) == 1
    assert dl.all()[0].cause == "shed-untrusted"
