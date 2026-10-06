"""v0.3 mathematics: the common threads across the parallel design worlds.

Gemini's "three invariants" (DAG causality, information theory, ergodicity)
plus the ChatGPT value-of-computation and developmental-warmth formulas, all
executable and maturity-tagged. Nothing here is a universal truth scalar.
"""
from __future__ import annotations
from math import log, prod
from typing import Callable, Sequence, Any
from ..cognition.math_systems import kl_divergence, entropy, MathSystem, REGISTRY


def js_divergence(p: Sequence[float], q: Sequence[float]) -> float:
    """Symmetric, bounded by ln 2. Useful for comparing peer answer distributions."""
    zp, zq = sum(p), sum(q)
    p = [x / zp for x in p]
    q = [x / zq for x in q]
    m = [(a + b) / 2 for a, b in zip(p, q)]
    return 0.5 * kl_divergence(p, m) + 0.5 * kl_divergence(q, m)


def conditional_entropy(joint: Sequence[Sequence[float]]) -> float:
    """H(S|O) from a joint table joint[s][o]."""
    z = sum(sum(r) for r in joint)
    J = [[x / z for x in r] for r in joint]
    p_o = [sum(J[s][o] for s in range(len(J))) for o in range(len(J[0]))]
    return -sum(J[s][o] * log(J[s][o] / p_o[o]) for s in range(len(J)) for o in range(len(J[0])) if J[s][o] > 0)


def mutual_information(joint: Sequence[Sequence[float]]) -> float:
    z = sum(sum(r) for r in joint)
    return entropy([sum(r) / z for r in joint]) - conditional_entropy(joint)


def time_average_growth(returns: Sequence[float]) -> float:
    if any(r <= -1 for r in returns):
        return float("-inf")
    return sum(log(1 + r) for r in returns) / len(returns)


def ensemble_average(returns: Sequence[float]) -> float:
    return sum(returns) / len(returns)


def ergodicity_gap(returns: Sequence[float]) -> float:
    """Time-average log growth minus log of ensemble-average growth (<= 0; volatility drag)."""
    return time_average_growth(returns) - log(1 + ensemble_average(returns))


def gamblers_ruin(p: float, start: int, target: int) -> float:
    """Probability of hitting 0 before target in a +/-1 walk with up-probability p."""
    if start <= 0:
        return 1.0
    if start >= target:
        return 0.0
    q = 1 - p
    if abs(p - q) < 1e-12:
        return 1 - start / target
    r = q / p
    return (r ** start - r ** target) / (1 - r ** target)


def markov_blanket(parents: dict[str, set[str]], node: str) -> set[str]:
    """Pearl's blanket in a DAG: parents, children, and the children's other parents."""
    children = {n for n, ps in parents.items() if node in ps}
    co = {p for c in children for p in parents.get(c, set())}
    return (parents.get(node, set()) | children | co) - {node}


def value_of_work(dK: float, dC: float, dU: float, dT: float, cost: float, risk: float, latency: float,
                  alpha: float = 1.0, beta: float = 1.0, gamma: float = 1.0, lam: float = 1.0) -> float:
    """V_i = (E[dK] + a E[dC] + b E[dU] + g E[dT]) / (C + R + l L). What computation is worth doing next?"""
    return (dK + alpha * dC + beta * dU + gamma * dT) / max(1e-9, cost + risk + lam * latency)


def developmental_warmth(compute: float, attention: float, data: float, stability: float) -> float:
    """W = C * A * D * S (each in [0,1]). If any factor approaches zero, development slows."""
    return prod(max(0.0, min(1.0, x)) for x in (compute, attention, data, stability))


def governed_action(propose: Callable[[Any], Any], functor: Callable[[Any], Any], delta_obs: Any,
                    certainty: float, e_min: float = 0.95) -> Any:
    """Executable shadow of the Universal Equation  A(t) = F_const(P(t, dO)) gated by E >= E_min.

    The integral and the S(Omega_Divine) projection in the Gemini text are
    notation (E4). What can run is this: no certainty, no action.
    """
    return functor(propose(delta_obs)) if certainty >= e_min else None


REGISTRY_V03_ADDITIONS = [
    MathSystem("Jensen-Shannon divergence", "information theory", "E0", "compare peer answer distributions", "Symmetric; bounded by ln 2."),
    MathSystem("Conditional entropy H(S|O)", "information theory", "E0", "uncertainty about state given observations", "Needs a joint model."),
    MathSystem("Mutual information", "information theory", "E0", "value of an observation channel", "I(S;O)=H(S)-H(S|O)."),
    MathSystem("Ergodicity economics", "long-horizon risk", "E1/E2", "time average vs ensemble average growth", "Motivates floors; does not prove them."),
    MathSystem("Gambler's ruin", "probability", "E0", "absorbing-barrier risk", "Assumes a +/-1 walk."),
    MathSystem("Markov blanket", "graphical models", "E0/E2", "boundary between internal and external states", "Exact in DAGs; interpretive for cyclic flows."),
    MathSystem("Reachability proof", "graph theory", "E0", "no Proposal->Actuation path avoids Authority", "Over declared morphisms only."),
    MathSystem("Partial-order trust lattice", "order theory", "E1", "trust without collapsing to one scalar", "meet/join componentwise."),
    MathSystem("Value of computation V_i", "decision theory", "E2", "choose the next unit of work", "Inputs are estimates."),
    MathSystem("Developmental warmth W=CADS", "cybernetics", "E3", "incubation readiness of the machine", "Product form is a modelling choice."),
    MathSystem("Universal Equation A=F(P(dO)) | E>=Emin", "notation", "E4", "compress the organism into one line", "Executable shadow only."),
]
REGISTRY_V03 = list(REGISTRY) + REGISTRY_V03_ADDITIONS
