"""Cybernetics: homeostasis, termination, second-order observation, VSM interpretation.

* SecondOrderObserver (von Foerster): the system observes its own observing.
  Every Authority evaluation is recorded with evaluator lineage, input hash
  and latency.
* LivenessMonitor (Timeline C lesson): the Authority path must stay fast.
* HomeostaticRegulator (Beer/Ashby): outcome residuals bias the Proposal
  plane toward deeper deliberation. It holds no reference to Authority and
  cannot loosen any Authority threshold.
* should_continue_reasoning: spec section 7 termination rule.
"""
from __future__ import annotations
import time
from typing import Any, Callable
from ..core import sha256
from .contracts import Extension


class SecondOrderObserver(Extension):
    def __init__(self, base: Any, sink: Callable[[dict], None] | None = None) -> None:
        super().__init__(base)
        self.__dict__.update(records=[], sink=sink)

    def evaluate(self, proposal, bundles, *args, **kwargs):
        t0 = time.perf_counter()
        decision, risk, constraint = self.base.evaluate(proposal, bundles, *args, **kwargs)
        rec = {
            "evaluator": type(self.base).__name__,
            "proposal_id": proposal.id,
            "input_hash": sha256({"p": proposal, "b": [b.id for b in bundles]}),
            "result": decision.result,
            "certainty": decision.epistemic_certainty,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
        }
        self.records.append(rec)
        if self.sink:
            self.sink(rec)
        return decision, risk, constraint


class LivenessMonitor:
    def __init__(self, budget_ms: float = 50.0, window: int = 200) -> None:
        self.budget_ms, self.window, self.samples = budget_ms, window, []

    def observe(self, ms: float) -> None:
        self.samples = (self.samples + [float(ms)])[-self.window:]

    def p95(self) -> float:
        if not self.samples:
            return 0.0
        s = sorted(self.samples)
        return s[min(len(s) - 1, int(0.95 * len(s)))]

    def healthy(self) -> bool:
        return self.p95() <= self.budget_ms


class HomeostaticRegulator:
    """Residual-driven caution bias for the Proposal plane only."""

    def __init__(self, alpha: float = 0.3, setpoint: float = 0.1, gain: float = 1.0, max_bias: float = 0.5) -> None:
        self.alpha, self.setpoint, self.gain, self.max_bias = alpha, setpoint, gain, max_bias
        self.ewma, self.bias = 0.0, 0.0

    def observe_residual(self, residual: float) -> None:
        self.ewma = self.alpha * abs(residual) + (1 - self.alpha) * self.ewma
        self.bias = max(0.0, min(self.max_bias, self.gain * (self.ewma - self.setpoint)))

    def adjust(self, consequence: float, uncertainty: float) -> tuple[float, float]:
        return min(1.0, consequence + self.bias), min(1.0, uncertainty + self.bias)

    def state(self) -> str:
        if self.ewma <= self.setpoint:
            return "viable"
        return "stressed" if self.ewma <= 3 * self.setpoint else "critical"


def should_continue_reasoning(expected_decision_improvement: float, marginal_compute_cost: float,
                              unresolved_high_consequence_constraint: bool = False) -> bool:
    return expected_decision_improvement > marginal_compute_cost or unresolved_high_consequence_constraint


# Viable System Model, as an organizational interpretation (E2/E3). No subsystem gains sovereign authority.
VSM_MAP = {
    "S1 Operations": "DomainPacks + VerifiedRuntime (organs doing the work)",
    "S2 Coordination": "ReservedTierScheduler + StigmergicGraph (damp oscillation between organs)",
    "S3 Control": "ResourceBroker + Authority constraint records",
    "S3* Audit": "SecondOrderObserver + ledger verification",
    "S4 Intelligence": "Proposal plane, active inference, DevelopmentalFrontier",
    "S5 Policy/Identity": "Constitution + RevealedAxioms + Operator (sole principal)",
}
