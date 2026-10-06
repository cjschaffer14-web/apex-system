from __future__ import annotations
from dataclasses import dataclass, field
from typing import Sequence
from .math_systems import pareto_dominates


@dataclass
class Candidate:
    candidate_id: str
    parent_candidate_id: str | None
    hypothesis: str
    mutation: str
    benchmark_vector: list[float]
    status: str = "isolated"
    failure_reason: str | None = None
    artifacts: list[str] = field(default_factory=list)


class EvolutionaryArchive:
    def __init__(self, maximize: Sequence[bool]):
        self.maximize = list(maximize)
        self.candidates: dict[str, Candidate] = {}
        self.champion_id: str | None = None

    def add(self, candidate: Candidate) -> None:
        self.candidates[candidate.candidate_id] = candidate

    def promote_if_dominant(self, candidate_id: str) -> bool:
        c = self.candidates[candidate_id]
        if self.champion_id is None:
            c.status = "champion"
            self.champion_id = candidate_id
            return True
        champ = self.candidates[self.champion_id]
        if pareto_dominates(c.benchmark_vector, champ.benchmark_vector, self.maximize):
            champ.status = "archived"
            c.status = "champion"
            self.champion_id = candidate_id
            return True
        c.status = "archived"
        return False
