from __future__ import annotations
from dataclasses import dataclass
import heapq, itertools


@dataclass
class Job:
    priority: int  # 0=P0, 1=P1, 2=P2, 3=P3
    name: str
    checkpointable: bool = True
    expected_value: float = 0.0


class ResourceScheduler:
    """Foreground-first scheduler. P3 must be checkpointable."""
    def __init__(self):
        self._q = []
        self._counter = itertools.count()

    def submit(self, job: Job) -> None:
        if job.priority == 3 and not job.checkpointable:
            raise ValueError("P3 work must be checkpointable")
        heapq.heappush(self._q,(job.priority,-job.expected_value,next(self._counter),job))

    def next(self) -> Job | None:
        return heapq.heappop(self._q)[-1] if self._q else None
