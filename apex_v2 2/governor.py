"""PredictiveGovernor v2: an expected-value gate instead of a weighted 'confidence' score.

Decision = hard vetoes (stale data, low survival, high toxicity, thin edge-to-noise)
           AND  EV > threshold, where

  EV = sum over outcomes of P(outcome) * pnl(outcome)
     = P_all_legs_fill * [(1-p_tox)*profit - p_tox*toxic_loss]
       - sum_k P(first failure at leg k) * (k-1) * unwind_cost

Survival uses the *current* taker-event intensity from a real exponential-kernel
Hawkes process (O(n) recursive), applied to each leg's cumulative latency.
All constants are parameters. Calibrate them on recorded data; the defaults are
placeholders, not fitted values.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple


class HawkesIntensity:
    """lambda(t) = mu + sum_i alpha * exp(-beta (t - t_i)); stable iff alpha < beta."""

    def __init__(self, mu: float, alpha: float, beta: float):
        if mu < 0 or alpha < 0 or beta <= 0:
            raise ValueError("need mu>=0, alpha>=0, beta>0")
        if alpha >= beta:
            raise ValueError("branching ratio alpha/beta must be < 1")
        self.mu, self.alpha, self.beta = mu, alpha, beta
        self._s = 0.0
        self._t: Optional[float] = None

    @property
    def branching(self) -> float:
        return self.alpha / self.beta

    @property
    def stationary_rate(self) -> float:
        return self.mu / (1.0 - self.branching)

    def _decayed(self, t: float) -> float:
        if self._t is None:
            return 0.0
        dt = t - self._t
        if dt < 0:
            raise ValueError("time must be non-decreasing")
        return self._s * math.exp(-self.beta * dt)

    def observe(self, t: float) -> None:
        self._s = self._decayed(t) + self.alpha
        self._t = t

    def intensity(self, t: float) -> float:
        return self.mu + self._decayed(t)


def _sigmoid(z: float) -> float:
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


class ToxicityModel:
    """Logistic P(toxic | |OFI|, |reference divergence|). Fit on ex-post labels
    (price moved permanently after the arb window, per Foucault-Kozhan-Tham)."""

    def __init__(self, w: Sequence[float] = (-1.0, 0.0, 0.0)):
        self.w = list(w)

    @staticmethod
    def _x(ofi: float, div_bps: float) -> Tuple[float, float, float]:
        return (1.0, min(abs(ofi), 1.0), min(abs(div_bps) / 10.0, 5.0))

    def predict(self, ofi: float, div_bps: float) -> float:
        x = self._x(ofi, div_bps)
        return _sigmoid(sum(wi * xi for wi, xi in zip(self.w, x)))

    def fit(self, samples: Sequence[Tuple[float, float, bool]],
            lr: float = 0.5, epochs: int = 300, l2: float = 1e-3) -> None:
        n = len(samples)
        if n == 0:
            return
        xs = [self._x(o, d) for o, d, _ in samples]
        ys = [1.0 if y else 0.0 for _, _, y in samples]
        for _ in range(epochs):
            grad = [0.0, 0.0, 0.0]
            for x, y in zip(xs, ys):
                e = _sigmoid(sum(wi * xi for wi, xi in zip(self.w, x))) - y
                for i in range(3):
                    grad[i] += e * x[i]
            for i in range(3):
                self.w[i] -= lr * (grad[i] / n + (l2 * self.w[i] if i else 0.0))


def is_toxic_ex_post(pre_mid: float, post_mid: float, threshold_bps: float = 2.0) -> bool:
    """Label used to fit ToxicityModel: price has not reverted after the window."""
    return abs(post_mid - pre_mid) / pre_mid * 1e4 > threshold_bps


@dataclass
class GovernorConfig:
    max_book_age_ms: float = 250.0      # heartbeat: older data is a ghost
    min_p_survive: float = 0.50
    max_p_toxic: float = 0.50
    min_edge_to_noise: float = 1.0      # profit_bps / (sigma*sqrt(tau)*1e4)
    min_ev_bps: float = 1.0             # EV as bps of notional
    hawkes_beta: float = 5.0            # 1/s excitation decay
    hawkes_branching: float = 0.3
    window_s: float = 3.0               # event window for the rate estimate
    prior_rate: float = 0.5             # events/s assumed when the window is empty
    hit_fraction: float = 1.0           # share of taker events that kill our level
    toxic_loss_mult: float = 1.0        # toxic outcome loses mult*profit ...
    toxic_floor_bps: float = 3.0        # ... plus this many bps of notional


@dataclass
class Observation:
    notional_usd: float
    profit_usd: float                   # net of fees and book-walk slippage (core.simulate_cycle)
    n_legs: int
    latency_per_leg_ms: float           # legs are sent sequentially
    book_age_ms: float                  # worst age across the legs
    sigma_per_sqrt_s: float             # fractional price vol per sqrt(second)
    ofi: float                          # order-flow imbalance in [-1, 1]
    ref_divergence_bps: float           # reference/lead-venue price vs our book mid
    unwind_bps: float                   # cost to flatten one filled leg (half-spread + fee)
    now_s: float
    taker_event_times_s: Sequence[float] = field(default_factory=list)


@dataclass
class Decision:
    approve: bool
    ev_usd: float
    ev_bps: float
    p_survive: float
    p_toxic: float
    rate_per_s: float
    edge_to_noise: float
    reasons: List[str]


class PredictiveGovernor:
    def __init__(self, config: Optional[GovernorConfig] = None,
                 tox_model: Optional[ToxicityModel] = None):
        self.cfg = config or GovernorConfig()
        self.tox = tox_model or ToxicityModel()

    def competitor_rate(self, times: Sequence[float], now: float) -> float:
        c = self.cfg
        ev = sorted(t for t in times if now - c.window_s <= t <= now)
        base = len(ev) / c.window_s
        mu = max(base, c.prior_rate) * (1.0 - c.hawkes_branching)
        h = HawkesIntensity(mu, c.hawkes_branching * c.hawkes_beta, c.hawkes_beta)
        for t in ev:
            h.observe(t)
        # Floor at the prior: a quiet window must not make us optimistic about survival.
        return max(h.intensity(now), c.prior_rate) * c.hit_fraction

    def decide(self, o: Observation) -> Decision:
        c = self.cfg
        rate = self.competitor_rate(o.taker_event_times_s, o.now_s)
        L = o.latency_per_leg_ms / 1000.0
        surv = [1.0] + [math.exp(-rate * L * k) for k in range(1, o.n_legs + 1)]
        p_all = surv[-1]
        p_tox = self.tox.predict(o.ofi, o.ref_divergence_bps)

        tox_loss = c.toxic_loss_mult * max(o.profit_usd, 0.0) + c.toxic_floor_bps / 1e4 * o.notional_usd
        ev_complete = (1 - p_tox) * o.profit_usd - p_tox * tox_loss
        unwind = o.unwind_bps / 1e4 * o.notional_usd
        ev_fail = sum((surv[k - 1] - surv[k]) * (k - 1) * unwind for k in range(1, o.n_legs + 1))
        ev = p_all * ev_complete - ev_fail
        ev_bps = ev / o.notional_usd * 1e4 if o.notional_usd else 0.0

        noise_bps = o.sigma_per_sqrt_s * math.sqrt(o.n_legs * L) * 1e4
        profit_bps = o.profit_usd / o.notional_usd * 1e4 if o.notional_usd else 0.0
        e2n = profit_bps / noise_bps if noise_bps > 0 else math.inf

        reasons = []
        if o.book_age_ms > c.max_book_age_ms:
            reasons.append(f"stale data {o.book_age_ms:.0f}ms")
        if o.profit_usd <= 0:
            reasons.append("no edge after fees")
        if p_all < c.min_p_survive:
            reasons.append(f"P(survive)={p_all:.2f}")
        if p_tox > c.max_p_toxic:
            reasons.append(f"P(toxic)={p_tox:.2f}")
        if e2n < c.min_edge_to_noise:
            reasons.append(f"edge/noise={e2n:.1f}")
        if ev_bps < c.min_ev_bps:
            reasons.append(f"EV={ev_bps:.2f}bps")
        return Decision(not reasons, ev, ev_bps, p_all, p_tox, rate, e2n, reasons)
