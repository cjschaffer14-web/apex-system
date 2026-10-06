"""Reference mathematics for APEX.

The purpose of this module is not to claim one universal truth metric.
It provides explicit, inspectable functions plus maturity metadata.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import log, sqrt
from typing import Iterable, Sequence


@dataclass(frozen=True)
class MathSystem:
    name: str
    family: str
    maturity: str
    purpose: str
    notes: str


REGISTRY = [
    MathSystem("Gaussian error propagation","measurement","E0","propagate independent measurement uncertainty","Exact assumptions must be declared."),
    MathSystem("Jacobian covariance propagation","measurement","E0","propagate uncertainty through differentiable transforms","Use covariance matrices in production."),
    MathSystem("Lamport logical clocks","temporal","E0","causal ordering in distributed processes","Logical order is not wall-clock duration."),
    MathSystem("Bayesian updating","epistemic","E0/E1","update belief with evidence","Requires explicit priors and likelihood model."),
    MathSystem("Shannon entropy","information theory","E0","uncertainty/compression accounting","Not identical to semantic uncertainty."),
    MathSystem("KL divergence","information theory","E0","distance-like divergence between distributions","Asymmetric; not a metric."),
    MathSystem("Expected information gain","decision theory","E1","allocate reasoning/search compute","Requires a tractable predictive model."),
    MathSystem("Active inference / variational free-energy proxy","cognition","E2","choose probes/actions that reduce epistemic uncertainty","Implemented only as a proxy in v0.2."),
    MathSystem("Fractional Kelly","capital allocation","E1","scale risky capital under estimated edge","DomainPack only; estimation error can dominate."),
    MathSystem("Risk headroom","risk","E1","combine probability, impact and reversibility constraints","Policy-specific."),
    MathSystem("Viability/homeostasis","cybernetics","E2","keep state inside declared safe bounds","Maps to scheduler/risk feedback loops."),
    MathSystem("Stigmergic graph coordination","multi-agent","E2","coordinate agents via shared graph traces","Graph traces are evidence, not authority."),
    MathSystem("Category/functor contract preservation","formal architecture","E2/E3","check structure-preserving mappings across pipeline stages","Engineering interpretation, not literal category-theoretic proof."),
    MathSystem("Topological invariant boundary","security architecture","E3/E4","treat Proposal→Actuation separation as structural","Implemented as process/API boundary, metaphor at higher level."),
    MathSystem("Counterfactual branch distance","evolution","E2/E3","compare candidate trajectories to failures/champions","Metric must be domain-specific."),
    MathSystem("Pareto dominance","multi-objective optimization","E0/E1","avoid collapsing all values into one scalar","Useful for benchmark vectors."),
    MathSystem("Control feedback / PID-like correction","cybernetics","E0/E1","correct measurable residuals","Only suitable where plant dynamics justify it."),
    MathSystem("Game-theoretic response analysis","social/multi-agent","E1/E2","model strategic interaction and incentives","Do not infer truth from equilibrium."),
    MathSystem("Graph theory","world model","E0","typed relation, dependency and causal projections","Centrality is not importance by itself."),
    MathSystem("Ergodic/ruin-aware objective framing","long-horizon risk","E2/E3","prefer survivable trajectories over one-shot expected value","Needs domain validation."),
    MathSystem("Compression loss accounting","learning","E1","measure information discarded by abstractions","Must preserve raw source for re-opening."),
]


def independent_error(errors: Sequence[float]) -> float:
    return sqrt(sum(e*e for e in errors))


def multiply_error(values: Sequence[float], errors: Sequence[float]) -> float:
    if len(values) != len(errors):
        raise ValueError("values/errors mismatch")
    product = 1.0
    rel2 = 0.0
    for v, e in zip(values, errors):
        product *= v
        if v != 0:
            rel2 += (e / v) ** 2
    return abs(product) * sqrt(rel2)


def entropy(probabilities: Iterable[float], eps: float = 1e-12) -> float:
    ps = [max(eps, float(p)) for p in probabilities]
    z = sum(ps)
    if z <= 0:
        return 0.0
    ps = [p/z for p in ps]
    return -sum(p * log(p) for p in ps)


def kl_divergence(p: Sequence[float], q: Sequence[float], eps: float = 1e-12) -> float:
    if len(p) != len(q):
        raise ValueError("distribution mismatch")
    ps = [max(eps, x) for x in p]
    qs = [max(eps, x) for x in q]
    zp, zq = sum(ps), sum(qs)
    ps, qs = [x/zp for x in ps], [x/zq for x in qs]
    return sum(a * log(a/b) for a,b in zip(ps,qs))


def bayes(prior: float, likelihood_if_true: float, likelihood_if_false: float) -> float:
    numerator = likelihood_if_true * prior
    denominator = numerator + likelihood_if_false * (1-prior)
    return numerator / denominator if denominator else prior


def evidence_certainty(quality: float, independence: float, reproducibility: float,
                       domain_fit: float, staleness: float, contradiction: float = 0.0) -> float:
    """Transparent reference aggregate, not a universal truth score."""
    base = (quality + independence + reproducibility + domain_fit) / 4
    penalty = 0.35*max(0.0, staleness) + 0.45*max(0.0, contradiction)
    return max(0.0, min(1.0, base - penalty))


def expected_information_gain(entropy_before: float, expected_entropy_after: float, cost: float = 0.0) -> float:
    return (entropy_before - expected_entropy_after) - cost


def fractional_kelly(win_probability: float, payoff_ratio: float, fraction: float = 0.25) -> float:
    """Research/reference only. Negative result means no positive Kelly allocation."""
    if payoff_ratio <= 0:
        return 0.0
    q = 1.0 - win_probability
    full = (payoff_ratio * win_probability - q) / payoff_ratio
    return max(0.0, full * max(0.0, min(1.0, fraction)))


def risk_score(probability: float, impact: float, irreversibility: float,
               detectability_penalty: float, blast_radius: float) -> float:
    vals = [probability, impact, irreversibility, detectability_penalty, blast_radius]
    vals = [max(0.0, min(1.0, x)) for x in vals]
    return 0.25*vals[0] + 0.25*vals[1] + 0.2*vals[2] + 0.1*vals[3] + 0.2*vals[4]


def pareto_dominates(a: Sequence[float], b: Sequence[float], maximize: Sequence[bool]) -> bool:
    if not (len(a)==len(b)==len(maximize)):
        raise ValueError("shape mismatch")
    weak = True
    strict = False
    for x,y,mx in zip(a,b,maximize):
        better_eq = x >= y if mx else x <= y
        better = x > y if mx else x < y
        weak &= better_eq
        strict |= better
    return weak and strict


def free_energy_proxy(prediction_error: float, uncertainty: float, action_cost: float) -> float:
    """Simple explicit proxy; not a full variational free-energy implementation."""
    return prediction_error**2 + uncertainty + action_cost


def counterfactual_distance(candidate: Sequence[float], historical_failure: Sequence[float],
                            scales: Sequence[float] | None = None) -> float:
    if len(candidate) != len(historical_failure):
        raise ValueError("shape mismatch")
    if scales is None:
        scales = [1.0]*len(candidate)
    return sqrt(sum(((a-b)/max(1e-12,s))**2 for a,b,s in zip(candidate,historical_failure,scales)))


def compression_loss(original_information: float, retained_information: float) -> float:
    if original_information <= 0:
        return 0.0
    return max(0.0, 1.0 - retained_information/original_information)
