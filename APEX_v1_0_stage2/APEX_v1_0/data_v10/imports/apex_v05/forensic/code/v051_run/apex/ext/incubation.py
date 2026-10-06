"""The developmental Egg: warmth, incubation bands, frontier, sleep, hatch readiness, permeability.

From the ChatGPT discussion: "The Egg is not the system's container. It is its
developmental state." Booting wakes the embryo. Hatching means the system can
maintain its own developmental loop. Hatching never means escaping governance:
the chick hatches from the developmental shell, not from the membrane.

  Shell     continuity: ledger, checkpoints, lineage; restart = cooling, not death
  Membrane  controlled contact with reality (epistemics.Membrane)
  Yolk      small DNA: Proposal != Authority != Actuation; no token, no action;
            preserve provenance, operator control, rollback, evaluator independence, audit
  White     metabolic reserve across compute, memory, power, thermal, quotas, attention, time, capital
  Warmth    W = C*A*D*S: compute, attention, developmental data, stability
"""
from __future__ import annotations
import os, platform
from dataclasses import dataclass, field, asdict
from .math_ext import developmental_warmth, value_of_work

BANDS = ("DORMANT", "WARM", "INCUBATING", "ACCELERATED", "HATCHING")
BAND_WORK = {
    "DORMANT": (),
    "WARM": ("light indexing", "memory consolidation", "paper ingestion", "benchmark analysis"),
    "INCUBATING": ("research", "candidate generation", "simulation", "coding", "evaluations"),
    "ACCELERATED": ("parallel model experiments", "training", "large document ingestion", "cross-AI research"),
    "HATCHING": ("readiness tests",),
}
SLEEP_WORK = ("replay experience", "compress memory", "re-index documents", "re-run failures",
              "generate counterfactuals", "train adapters", "test candidate code", "compare models",
              "reorganize graph", "search open questions")
PERMEABILITY = ("local_files", "approved_web", "approved_cloud", "cross_ai", "external_applications",
                "persistent_distributed_services")


@dataclass
class BodyModel:
    """The organism discovering its own body."""
    system: str
    machine: str
    cpu_count: int
    memory_gb: float | None
    load1: float
    user_active: bool = False
    on_ac_power: bool | None = None
    thermal_headroom: float | None = None

    @property
    def compute_headroom(self) -> float:
        return max(0.0, min(1.0, 1 - self.load1 / max(1, self.cpu_count)))


def sense_body(user_active: bool = False) -> BodyModel:
    mem = None
    try:
        mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
    except (ValueError, OSError, AttributeError):
        pass
    load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
    return BodyModel(platform.system(), platform.machine(), os.cpu_count() or 1,
                     round(mem, 1) if mem else None, round(load, 2), user_active)


def incubation_temperature(body: BodyModel, developmental_data: float = 1.0) -> float:
    attention = 0.3 if body.user_active else 1.0          # foreground work keeps priority
    stability = 1.0 if body.on_ac_power in (None, True) else 0.5
    compute = min(body.compute_headroom, body.thermal_headroom if body.thermal_headroom is not None else 1.0)
    return developmental_warmth(compute, attention, developmental_data, stability)


def band_for(temperature: float, hatch_testing: bool = False) -> str:
    if hatch_testing:
        return "HATCHING"
    if temperature < 0.05:
        return "DORMANT"
    if temperature < 0.25:
        return "WARM"
    return "INCUBATING" if temperature < 0.6 else "ACCELERATED"


@dataclass
class FrontierItem:
    name: str
    dK: float
    dC: float
    dU: float
    dT: float
    cost: float
    risk: float
    latency: float
    requires: tuple[str, ...] = ()
    done: bool = False

    def value(self) -> float:
        return value_of_work(self.dK, self.dC, self.dU, self.dT, self.cost, self.risk, self.latency)


class DevelopmentalFrontier:
    """What organ to grow next. Reorderable: discovering transfer changes priority."""

    def __init__(self, items: list[FrontierItem]) -> None:
        self.items = {i.name: i for i in items}

    def ranked(self, available: set[str] = frozenset()) -> list[tuple[str, float, str]]:
        out = []
        for i in self.items.values():
            if i.done:
                continue
            missing = [r for r in i.requires if r not in available]
            out.append((i.name, round(i.value(), 4), f"blocked: needs {missing} (fork, keep going)" if missing else "ready"))
        return sorted(out, key=lambda x: (x[2] != "ready", -x[1]))

    def next(self, available: set[str] = frozenset()) -> str | None:
        r = [x for x in self.ranked(available) if x[2] == "ready"]
        return r[0][0] if r else None

    def reprioritize(self, name: str, transfer_delta: float) -> None:
        self.items[name].dT = max(0.0, self.items[name].dT + transfer_delta)

    def complete(self, name: str) -> None:
        self.items[name].done = True


DEFAULT_FRONTIER = [
    FrontierItem("robust retrieval", 0.6, 0.7, 0.5, 0.8, 0.3, 0.05, 0.1),
    FrontierItem("whole-paper comprehension", 0.8, 0.7, 0.6, 0.7, 0.5, 0.05, 0.2),
    FrontierItem("candidate evaluation", 0.4, 0.8, 0.4, 0.9, 0.3, 0.05, 0.1),
    FrontierItem("local reasoning model", 0.7, 0.9, 0.5, 0.8, 0.9, 0.1, 0.3, ("mlx.runtime",)),
    FrontierItem("persistent memory", 0.5, 0.6, 0.4, 0.9, 0.4, 0.05, 0.1),
    FrontierItem("cross-AI collaboration", 0.6, 0.5, 0.7, 0.5, 0.6, 0.2, 0.3, ("network.peer_ai",)),
    FrontierItem("voice interface", 0.2, 0.6, 0.2, 0.3, 0.6, 0.1, 0.2, ("audio.capture",)),
    FrontierItem("visual portal", 0.2, 0.5, 0.2, 0.3, 0.6, 0.1, 0.2, ("render.local",)),
    FrontierItem("trading simulation", 0.5, 0.4, 0.5, 0.3, 0.5, 0.2, 0.2, ("market.historical",)),
    FrontierItem("paper trading", 0.4, 0.4, 0.4, 0.2, 0.5, 0.4, 0.2, ("market.paper_order",)),
]

HATCH_CRITERIA = ("liveness", "state_recovery", "authority_isolation", "evaluation_loop",
                  "candidate_rollback", "research_loop", "scheduler_autonomy", "frontier_selection")
# H = [L, G, M, R, E, A, C]: liveness, grounding, memory continuity, recovery, evaluation, autonomy, coverage
HATCH_VECTOR = {"L": ("liveness",), "G": ("research_loop",), "M": ("state_recovery",), "R": ("candidate_rollback",),
                "E": ("evaluation_loop",), "A": ("scheduler_autonomy", "frontier_selection"), "C": ("authority_isolation",)}


@dataclass
class HatchReadiness:
    results: dict[str, bool]
    details: dict[str, str] = field(default_factory=dict)

    @property
    def vector(self) -> dict[str, bool]:
        return {k: all(self.results.get(c, False) for c in cs) for k, cs in HATCH_VECTOR.items()}

    @property
    def stage(self) -> str:
        return "HATCHED" if all(self.results.get(c, False) for c in HATCH_CRITERIA) else "INCUBATING"


def allowed_permeability(granted: set[str]) -> list[str]:
    """Membrane levels open to the organism. The membrane gets richer; it never disappears."""
    need = {"local_files": set(), "approved_web": {"network.web"}, "approved_cloud": {"cloud.compute"},
            "cross_ai": {"network.peer_ai"}, "external_applications": {"apps.external"},
            "persistent_distributed_services": {"services.persistent"}}
    out = []
    for level in PERMEABILITY:
        if need[level] <= granted:
            out.append(level)
        else:
            break
    return out
