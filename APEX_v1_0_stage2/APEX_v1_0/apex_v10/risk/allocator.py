"""Layer 6 risk allocator: Ledoit-Wolf covariance, fractional Kelly, volatility targeting, regime and
market-condition guards, and per-asset / net / gross leverage bounds.

Design rules (Stage 2 directives, APEX System Collaboration doc, 4 Oct 2026)
  * No tuning. Every number in RiskConfig is a fixed, documented default carried over from the frozen v0.8/v0.9
    sizing module (gross cap 3.0, per-asset cap 2.0, half Kelly) or a conservative guard constant. Nothing here
    searches parameters or selects strategies.
  * Point-in-time, fail-closed. The returns window carries a `known_at_ts` per row; any row known after the
    mixture's decision_ts raises PointInTimeViolation (a lookahead bug must stop the run, never be absorbed).
    A raw float matrix carries no timestamps, so it is refused rather than trusted.
  * Deterministic fallback ladder (interfaces.COVARIANCE_METHODS, in order):
        ledoit_wolf -> ledoit_wolf+eigen_floor -> independent_fractional_kelly -> zero_exposure
    Every rung change and every cap/guard activation is written to RiskAllocation.guard_events.
  * Caps hold exactly: after scaling, |w| sums are checked in floating point and nudged down if rounding left
    them above the cap (the frozen v0.8 module produced a gross of 3.0000000000000004 against a cap of 3.0).
  * Guards only ever reduce exposure. Volatility targeting scales down, never up.

Units: the mixture's expected returns are LOG returns over the forecast horizon. The covariance is estimated on
per-period log returns and scaled to the horizon by horizon_seconds / period_seconds (i.i.d. assumption,
recorded in guard_events as `horizon_scale=<k>`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

import numpy as np

from apex_v10.interfaces import (MarketStateDistribution, RiskAllocation, StrategyMixture, sha256_of)


class PointInTimeViolation(ValueError):
    """Data known after the decision instant reached the risk layer."""


@dataclass(frozen=True)
class ReturnsWindow:
    """Per-period log returns, one row per period, columns in `assets` order, with the instant each row was known."""
    assets: tuple[str, ...]
    known_at_ts: tuple[int, ...]
    values: tuple[tuple[float, ...], ...]          # NaN allowed for a missing observation; rows with NaN are dropped
    period_seconds: int

    def __post_init__(self) -> None:
        if len(set(self.assets)) != len(self.assets) or not self.assets:
            raise ValueError("assets must be unique and non-empty")
        if len(self.known_at_ts) != len(self.values):
            raise ValueError("one known_at_ts per row")
        if any(not isinstance(t, int) or isinstance(t, bool) or t < 0 for t in self.known_at_ts):
            raise ValueError("known_at_ts must be non-negative integer epoch seconds")
        if any(b <= a for a, b in zip(self.known_at_ts, self.known_at_ts[1:])):
            raise ValueError("known_at_ts must be strictly increasing")
        if any(len(r) != len(self.assets) for r in self.values):
            raise ValueError("every row needs one value per asset")
        if not isinstance(self.period_seconds, int) or self.period_seconds <= 0:
            raise ValueError("period_seconds must be a positive integer")

    def matrix(self) -> np.ndarray:
        return np.asarray(self.values, dtype=float).reshape(len(self.values), len(self.assets))


@dataclass(frozen=True)
class RiskConfig:
    kelly_fraction: float = 0.5                    # half Kelly (frozen v0.8 default)
    per_asset_cap: float = 2.0                     # frozen v0.9 matrix-Kelly settings
    gross_cap: float = 3.0
    net_cap: float = 3.0                           # |sum w|; equals gross_cap for long-only books
    long_only: bool = True                         # shorts belong to a separately tested family (v0.8 docstring)
    min_observations: int = 60                     # below this: no covariance estimate, fall back
    min_observations_per_asset: int = 20           # below this: zero exposure
    max_condition_number: float = 1e4              # above: eigenvalue floor at lambda_max / max_condition_number
    target_volatility: Optional[float] = None      # per-horizon portfolio st.dev. ceiling; None = off
    vol_spike_window: int = 20                     # market-condition guard: recent vs full-window volatility
    vol_spike_ratio: float = 2.0
    vol_spike_gross_multiplier: float = 0.5
    regime_gross_multipliers: Mapping[str, float] = field(default_factory=dict)   # state label -> multiplier <= 1
    max_state_entropy: Optional[float] = None      # uncertain regime -> regime_uncertain_multiplier
    regime_uncertain_multiplier: float = 0.5
    require_state: bool = False                    # fail closed (zero exposure) if no state is supplied

    def __post_init__(self) -> None:
        for n in ("per_asset_cap", "gross_cap", "net_cap", "max_condition_number", "vol_spike_ratio"):
            v = getattr(self, n)
            if not (isinstance(v, (int, float)) and math.isfinite(v) and v > 0):
                raise ValueError(f"{n} must be a positive finite number")
        if not 0.0 < self.kelly_fraction <= 1.0:
            raise ValueError("kelly_fraction must lie in (0, 1]")
        for n in ("vol_spike_gross_multiplier", "regime_uncertain_multiplier"):
            if not 0.0 <= getattr(self, n) <= 1.0:
                raise ValueError(f"{n} must lie in [0, 1]: guards may only reduce exposure")
        if any(not 0.0 <= m <= 1.0 for m in self.regime_gross_multipliers.values()):
            raise ValueError("regime multipliers must lie in [0, 1]: guards may only reduce exposure")
        if self.target_volatility is not None and not self.target_volatility > 0:
            raise ValueError("target_volatility must be positive or None")
        if self.min_observations < 2 or self.min_observations_per_asset < 2 or self.vol_spike_window < 2:
            raise ValueError("observation minimums must be at least 2")

    @property
    def sha256(self) -> str:
        return sha256_of(self)


# ---------------------------------------------------------------------------------------------------------------
# covariance ladder
# ---------------------------------------------------------------------------------------------------------------
def ledoit_wolf_covariance(x: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit & Wolf (2004) shrinkage toward a scaled identity, matching sklearn.covariance.ledoit_wolf
    (assume_centered=False). Returns (covariance, shrinkage in [0, 1])."""
    n, p = x.shape
    xc = x - x.mean(axis=0)
    s = xc.T @ xc / n
    mu = np.trace(s) / p
    delta = np.sum((s - mu * np.eye(p)) ** 2) / p
    x2 = xc ** 2
    beta_bar = np.sum(x2.T @ x2 / n - s ** 2) / (p * n)
    beta = min(beta_bar, delta)
    shrink = 0.0 if delta == 0 else beta / delta
    return (1 - shrink) * s + shrink * mu * np.eye(p), float(shrink)


def ladder_covariance(x: np.ndarray, cfg: RiskConfig, events: list[str]) -> tuple[str, Optional[np.ndarray], Optional[float]]:
    """Walk the fallback ladder. Returns (rung, covariance or None, condition number or None)."""
    n, p = x.shape
    if n < cfg.min_observations_per_asset:
        events.append(f"zero_exposure:observations={n}<{cfg.min_observations_per_asset}")
        return "zero_exposure", None, None
    var = x.var(axis=0)
    if not np.all(np.isfinite(var)) or np.any(var <= 0):
        events.append("zero_exposure:non_positive_or_non_finite_variance")
        return "zero_exposure", None, None
    if n < cfg.min_observations or p == 1:
        events.append(f"fallback:independent_fractional_kelly:observations={n},assets={p}")
        d = np.diag(var)
        return "independent_fractional_kelly", d, float(var.max() / var.min())
    s, shrink = ledoit_wolf_covariance(x)
    events.append(f"ledoit_wolf_shrinkage={shrink:.6g}")
    eig = np.linalg.eigvalsh(s)
    if not np.all(np.isfinite(eig)) or eig.max() <= 0:
        events.append("fallback:independent_fractional_kelly:non_finite_spectrum")
        return "independent_fractional_kelly", np.diag(var), float(var.max() / var.min())
    cond = float(eig.max() / eig.min()) if eig.min() > 0 else math.inf
    if cond <= cfg.max_condition_number:
        return "ledoit_wolf", s, cond
    vals, vecs = np.linalg.eigh(s)
    floor = vals.max() / cfg.max_condition_number
    vals = np.maximum(vals, floor)
    s2 = (vecs * vals) @ vecs.T
    s2 = (s2 + s2.T) / 2
    cond2 = float(vals.max() / vals.min())
    events.append(f"fallback:eigen_floor:condition_number={cond:.6g}->{cond2:.6g}")
    return "ledoit_wolf+eigen_floor", s2, min(max(cond2, 1.0), cfg.max_condition_number)


# ---------------------------------------------------------------------------------------------------------------
# exact caps
# ---------------------------------------------------------------------------------------------------------------
def _scale_to_cap(w: np.ndarray, measure, cap: float) -> np.ndarray:
    m = measure(w)
    if m <= cap:
        return w
    w = w * (cap / m)
    while measure(w) > cap:                        # floating-point rounding: step down one ulp at a time
        w = w * np.nextafter(1.0, 0.0)
    return w


def cap_gross_exactly(w: np.ndarray, cap: float) -> np.ndarray:
    return _scale_to_cap(np.asarray(w, float), lambda v: float(np.sum(np.abs(v))), cap)


# ---------------------------------------------------------------------------------------------------------------
# allocator
# ---------------------------------------------------------------------------------------------------------------
class LedoitWolfKellyAllocator:
    """RiskAllocator (interfaces.RiskAllocator) over a time-stamped ReturnsWindow."""

    def __init__(self, config: RiskConfig | None = None):
        self.config = config or RiskConfig()
        self.allocator_id = f"lw_kelly@{self.config.sha256[:12]}"

    def allocate(self, mixture: StrategyMixture, returns_window: ReturnsWindow, assets: Sequence[str],
                 state: Optional[MarketStateDistribution] = None) -> RiskAllocation:
        cfg, ts, events = self.config, mixture.decision_ts, []
        if not isinstance(returns_window, ReturnsWindow):
            raise TypeError("returns_window must be a ReturnsWindow: an untimestamped matrix cannot be PIT-checked")
        assets = tuple(assets)
        if assets != returns_window.assets:
            raise ValueError("assets must match the returns window's columns, in order")
        late = [t for t in returns_window.known_at_ts if t > ts]
        if late:
            raise PointInTimeViolation(f"{len(late)} return rows known after decision_ts={ts} (first {late[0]})")
        if state is not None and state.decision_ts > ts:
            raise PointInTimeViolation(f"state estimated at {state.decision_ts} > decision_ts={ts}")
        mu_by_asset = mixture.combined_expected_return()
        unknown = set(mu_by_asset) - set(assets)
        if unknown:
            raise ValueError(f"mixture forecasts assets outside the window: {sorted(unknown)}")
        horizons = {f.horizon_seconds for f in mixture.forecasts}
        horizon_seconds = horizons.pop() if horizons else returns_window.period_seconds

        def result(w: np.ndarray, rung: str, cond: Optional[float]) -> RiskAllocation:
            w = np.where(np.abs(w) < 1e-15, 0.0, w)
            return RiskAllocation(ts, self.allocator_id, {a: float(v) for a, v in zip(assets, w)}, cfg.per_asset_cap,
                                  cfg.gross_cap, cfg.kelly_fraction, rung, cond, tuple(events))

        zero = np.zeros(len(assets))
        if cfg.require_state and state is None:
            events.append("zero_exposure:state_required_but_missing")
            return result(zero, "zero_exposure", None)
        if not mu_by_asset:
            events.append("zero_exposure:no_forecasts")
            return result(zero, "zero_exposure", None)

        x = returns_window.matrix()
        x = x[np.all(np.isfinite(x), axis=1)]
        rung, cov, cond = ladder_covariance(x, cfg, events)
        if cov is None:
            return result(zero, "zero_exposure", None)

        k = horizon_seconds / returns_window.period_seconds
        events.append(f"horizon_scale={k:g}")
        cov_h = cov * k
        mu = np.array([mu_by_asset.get(a, 0.0) for a in assets])
        if rung == "independent_fractional_kelly":
            f = mu / np.diag(cov_h)
        else:
            f = np.linalg.solve(cov_h, mu)
        if not np.all(np.isfinite(f)):
            events.append("zero_exposure:non_finite_kelly_solution")
            return result(zero, "zero_exposure", cond)
        w = cfg.kelly_fraction * f
        w[[a not in mu_by_asset for a in assets]] = 0.0         # no forecast, no position
        if cfg.long_only and np.any(w < 0):
            events.append("long_only_clip:" + ",".join(a for a, v in zip(assets, w) if v < 0))
            w = np.maximum(w, 0.0)

        gross_cap = cfg.gross_cap
        mult = 1.0
        if state is not None:
            m = cfg.regime_gross_multipliers.get(state.most_likely, 1.0)
            if m < 1.0:
                events.append(f"regime_guard:{state.most_likely}:x{m:g}")
                mult = min(mult, m)
            if cfg.max_state_entropy is not None and state.entropy > cfg.max_state_entropy:
                events.append(f"regime_uncertain:entropy={state.entropy:.4g}:x{cfg.regime_uncertain_multiplier:g}")
                mult = min(mult, cfg.regime_uncertain_multiplier)
        if len(x) >= 2 * cfg.vol_spike_window:
            recent = x[-cfg.vol_spike_window:].std(axis=0, ddof=1)
            full = x.std(axis=0, ddof=1)
            ratio = float(np.max(recent / full))
            if ratio > cfg.vol_spike_ratio:
                events.append(f"vol_spike_guard:ratio={ratio:.4g}:x{cfg.vol_spike_gross_multiplier:g}")
                mult = min(mult, cfg.vol_spike_gross_multiplier)
        if mult < 1.0:
            gross_cap = gross_cap * mult
            events.append(f"dynamic_gross_cap={gross_cap:g}")
        if mult == 0.0:
            events.append("zero_exposure:guard_multiplier_zero")
            return result(zero, "zero_exposure", cond)

        if np.any(np.abs(w) > cfg.per_asset_cap):
            events.append("per_asset_cap:" + ",".join(a for a, v in zip(assets, w) if abs(v) > cfg.per_asset_cap))
            w = np.clip(w, -cfg.per_asset_cap, cfg.per_asset_cap)
        if cfg.target_volatility is not None:
            vol = float(math.sqrt(max(w @ cov_h @ w, 0.0)))
            if vol > cfg.target_volatility:
                events.append(f"vol_target:{vol:.4g}->{cfg.target_volatility:g}")
                w = w * (cfg.target_volatility / vol)
        net_cap = min(cfg.net_cap, gross_cap)          # a guard that lowers gross lowers the net bound too
        if abs(float(np.sum(w))) > net_cap:
            events.append(f"net_cap:{float(np.sum(w)):.6g}->{net_cap:g}")
            w = _scale_to_cap(w, lambda v: abs(float(np.sum(v))), net_cap)
        if float(np.sum(np.abs(w))) > gross_cap:
            events.append(f"gross_cap:{float(np.sum(np.abs(w))):.6g}")
            w = cap_gross_exactly(w, gross_cap)
        return result(w, rung, cond)
