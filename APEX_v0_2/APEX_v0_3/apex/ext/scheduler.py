"""ReservedTierScheduler: P-1 operator reserve, preemption, checkpointing, incubation gating.

Owner's critical review: add a reserved tier. P-1 sits above P0. It is the
operator channel, and its capacity can never be consumed by P0-P3. This makes
"user action must be possible at all times" a resource property and not a
promise.
"""
from __future__ import annotations
import heapq
from dataclasses import dataclass
from typing import Callable
from ..scheduler import ResourceScheduler, Job

P_RESERVED = -1
TIERS = (-1, 0, 1, 2, 3)


@dataclass
class TieredJob(Job):
    cost: float = 1.0
    on_checkpoint: Callable[[], None] | None = None


class ReservedTierScheduler(ResourceScheduler):
    def __init__(self, capacity: float = 10.0, reserve: float = 2.0) -> None:
        super().__init__()
        if not 0 < reserve < capacity:
            raise ValueError("reserve must be positive and below capacity")
        self.capacity, self.reserve = capacity, reserve
        self.running: list[Job] = []
        self.checkpointed: list[str] = []
        self.p3_allowed = True  # set by incubation band (DORMANT -> False)

    @staticmethod
    def _cost(job: Job) -> float:
        return float(getattr(job, "cost", 1.0))

    def in_use(self) -> float:
        return sum(self._cost(j) for j in self.running)

    def available_for(self, job: Job) -> float:
        return self.capacity - self.in_use() - (0.0 if job.priority == P_RESERVED else self.reserve)

    def submit(self, job: Job) -> None:
        if job.priority not in TIERS:
            raise ValueError(f"priority must be one of {TIERS}")
        super().submit(job)

    def _preempt_for(self, job: Job) -> None:
        victims = sorted((j for j in self.running if j.priority >= 2 and j.priority > job.priority),
                         key=lambda j: (-j.priority, j.expected_value))
        for v in victims:
            if self._cost(job) <= self.available_for(job):
                return
            if not v.checkpointable:
                continue
            cb = getattr(v, "on_checkpoint", None)
            if cb:
                cb()
            self.running.remove(v)
            self.checkpointed.append(v.name)
            super().submit(v)

    def dispatch(self) -> list[Job]:
        started, deferred = [], []
        while self._q:
            job = heapq.heappop(self._q)[-1]
            if job.priority == 3 and not self.p3_allowed:
                deferred.append(job)
                continue
            if self._cost(job) > self.available_for(job) and job.priority <= 1:
                self._preempt_for(job)
            if self._cost(job) <= self.available_for(job):
                self.running.append(job)
                started.append(job)
            else:
                deferred.append(job)
                if job.priority <= 1:
                    break
        for j in deferred:
            super().submit(j)
        return started

    def complete(self, job: Job) -> None:
        if job in self.running:
            self.running.remove(job)

    def halt(self) -> list[str]:
        """Operator halt: checkpoint and stop everything except P-1."""
        stopped = []
        for j in list(self.running):
            if j.priority != P_RESERVED:
                cb = getattr(j, "on_checkpoint", None)
                if cb and j.checkpointable:
                    cb()
                self.running.remove(j)
                stopped.append(j.name)
        self._q = [e for e in self._q if e[-1].priority == P_RESERVED]
        heapq.heapify(self._q)
        return stopped

    def reserve_intact(self) -> bool:
        non_reserved = sum(self._cost(j) for j in self.running if j.priority != P_RESERVED)
        return non_reserved <= self.capacity - self.reserve + 1e-9
