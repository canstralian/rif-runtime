"""Durable job broker with leases and fencing tokens (spec §5.3, §5.4, §8.1).

Modelled in-process for testability (spec OD-1 recommends Postgres in production).
The load-bearing semantics captured here:
  * leased jobs carry a monotonically increasing **fencing token** so a duplicate
    lease produced by a broker partition cannot commit stale work (spec §5.4);
  * queue-depth ceiling sheds UNTRUSTED first, then lowest-priority TRUSTED, and
    never silently (spec §2.5) — shed jobs are dead-lettered with cause.
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from typing import Any

from wfa.shared.enums import Profile


@dataclass(order=True)
class _Queued:
    sort_key: tuple[int, int]
    job: "Job" = field(compare=False)


@dataclass
class Job:
    delivery_id: str
    payload: dict[str, Any]
    profile: Profile = Profile.UNSPECIFIED
    priority: int = 100  # lower = higher priority
    attempts: int = 0


@dataclass(frozen=True)
class Lease:
    job: Job
    fencing_token: int


class QueueFull(Exception):
    pass


class Broker:
    def __init__(self, queue_depth_ceiling: int = 10_000) -> None:
        self._ceiling = queue_depth_ceiling
        self._heap: list[_Queued] = []
        self._counter = itertools.count()
        self._fencing = itertools.count(1)
        self._committed_fence: dict[str, int] = {}

    def depth(self) -> int:
        return len(self._heap)

    def _priority_key(self, job: Job) -> tuple[int, int]:
        # TRUSTED shed last => give UNTRUSTED a *worse* shed rank. For dequeue we want
        # priority then FIFO; profile only matters at shedding time.
        return (job.priority, next(self._counter))

    def enqueue(self, job: Job) -> bool:
        """Durably enqueue. On ceiling, shed one victim to make room (never silent)."""

        if len(self._heap) >= self._ceiling:
            victim = self._select_shed_victim()
            if victim is None:
                return False  # nothing sheddable (should not happen with a victim)
            self._heap.remove(victim)
            heapq.heapify(self._heap)
            # Caller (ingress/classifier) is responsible for dead-lettering the victim
            # with cause; surface it via the exception path.
            raise QueueFull(victim.job.delivery_id)
        heapq.heappush(self._heap, _Queued(self._priority_key(job), job))
        return True

    def _select_shed_victim(self) -> _Queued | None:
        if not self._heap:
            return None
        # Shed UNTRUSTED first, then the lowest-priority TRUSTED (spec §2.5).
        untrusted = [q for q in self._heap if q.job.profile is Profile.UNTRUSTED]
        pool = untrusted or self._heap
        return max(pool, key=lambda q: q.job.priority)

    def lease(self) -> Lease | None:
        if not self._heap:
            return None
        queued = heapq.heappop(self._heap)
        return Lease(queued.job, next(self._fencing))

    def commit(self, lease: Lease) -> bool:
        """Commit work under a lease; rejects a stale fencing token (spec §5.4)."""

        last = self._committed_fence.get(lease.job.delivery_id, 0)
        if lease.fencing_token <= last:
            return False
        self._committed_fence[lease.job.delivery_id] = lease.fencing_token
        return True

    def requeue(self, job: Job) -> None:
        job.attempts += 1
        heapq.heappush(self._heap, _Queued(self._priority_key(job), job))
