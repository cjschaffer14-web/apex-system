"""Layer 6 risk allocator, Stage 3 guard configuration (owner-ratified Gemini review, 2026-10-05). Revision 3.

Additions only. apex_v10/risk/allocator.py (Stage 2) is not modified: its RiskConfig defaults and
LedoitWolfKellyAllocator stay byte-identical, so the Stage 2 manifest hash is unaffected. This module
adds a new config and allocator that callers opt into explicitly.

Configuration changes (recorded as configuration, not a search; source: "APEX Stage 3 - Reduced Claude
Scope", section "Owner-ratified amendments from Gemini's review (2026-10-05)"):
  * max_condition_number 1e4 -> 1e3 (forces the eigenvalue floor / independent Kelly fallback earlier).
  * Minimum history split by timeframe. Daily (period > 1 h): 60 primary / 20 floor, unchanged.
    Hourly (period <= 1 h): 720 primary (30 days) / 168 floor (7 days)  [owner decision rev2, 2026-10-05;
    rev1 had 168 / 72]. A floor, not a cap: longer estimation windows are allowed. Any change between
    replay runs must be pre-registered as a separate configuration (it counts as a trial).
    "Primary" = min_observations (below it: independent fractional Kelly).
    "Floor"   = min_observations_per_asset (below it: zero exposure).
  * Volatility-spike guard baseline: rolling 252-period window instead of the full window. The guard
    fires when 20-period volatility exceeds 2x the trailing-252 volatility and halves gross, as before.
    rev2: the baseline strictly precedes the current 20-period window (rows [-272:-20]); with fewer rows it
    uses all rows before the current window, and the guard needs at least 2x the spike window in total.
  * gross_cap, net_cap, per_asset_cap 3.0/3.0/2.0 -> 1.0/1.0/1.0. Kelly fraction stays 0.5;
    target_volatility stays None. Leverage above 1.0 needs a fixed target_volatility and a new owner decision.
  * rev2 scaling order: fractional Kelly -> regime/vol-spike gross multiplier -> target volatility
    (provisional, off by default) -> correlation-shock guard -> per-asset cap -> net cap -> gross cap.
    Margin and liquidation buffers are applied in Layer 7.
  * rev2 correlation-shock guard (owner-approved ChatGPT spec): stress cross-asset correlations to 0.95
    (never lowering a higher observed correlation); record a 1.00-correlation diagnostic separately.
    Limit = min(30% annualized volatility, 1.5x unstressed annualized volatility). If the stressed
    volatility exceeds the limit, all risky weights scale down proportionally; reject (zero exposure)
    only if no compliant allocation can be produced. Unstressed, stressed, diagnostic, limit and scaling
    factor are written to guard_events.
  * rev3 (owner decisions 2026-10-05): target_volatility in RiskConfigV2 is ANNUALIZED portfolio volatility
    (the Stage 2 RiskConfig field is per-horizon; V2 converts with 365-day years). Pyramid test mode:
    pyramid_regime_configs() returns five explicit, pre-declared regimes, gross cap 1.0 / 1.5 / 2.0 / 2.5 / 3.0.
    Each regime: net cap = per-asset cap = gross cap, target volatility = 0.40 x cap, absolute stressed-vol
    ceiling = 1.5 x target (0.60 x cap); the relative 1.5x-unstressed ceiling still applies and the lower
    limit operates. The general default RiskConfigV2() stays unlevered (caps 1.0, no target, ceiling 0.30).
    Each regime is a separate trial for the deflation count.
All Stage 2 point-in-time and fail-closed behaviour is inherited unchanged.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Optional, Sequence

import numpy as np

from apex_v10.interfaces import MarketStateDistribution, RiskAllocation, StrategyMixture
from apex_v10.risk.allocator import (LedoitWolfKellyAllocator, PointInTimeViolation, ReturnsWindow, RiskConfig,
                                     _scale_to_cap, cap_gross_exactly, ladder_covariance)

HOURLY_PERIOD_SECONDS_MAX = 3600


@dataclass(frozen=True)
class RiskConfigV2(RiskConfig):
    per_asset_cap: float = 1.0
    gross_cap: float = 1.0
    net_cap: float = 1.0
    max_condition_number: float = 1e3
    hourly_min_observations: int = 720
    hourly_min_observations_per_asset: int = 168
    vol_spike_baseline_window: int = 252
    corr_shock_level: float = 0.95
    corr_shock_diagnostic_level: float = 1.0
    corr_shock_abs_vol_ceiling: float = 0.30          # annualized
    corr_shock_rel_vol_multiple: float = 1.5

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.hourly_min_observations < 2 or self.hourly_min_observations_per_asset < 2:
            raise ValueError("observation minimums must be at least 2")
        if self.hourly_min_observations_per_asset > self.hourly_min_observations:
            raise ValueError("hourly floor must not exceed the hourly primary minimum")
        if self.vol_spike_baseline_window < 2 * self.vol_spike_window:
            raise ValueError("vol_spike_baseline_window must be at least 2x vol_spike_window")
        if not 0.0 < self.corr_shock_level <= 1.0 or not 0.0 < self.corr_shock_diagnostic_level <= 1.0:
            raise ValueError("stressed correlation levels must lie in (0, 1]")
        if not (self.corr_shock_abs_vol_ceiling > 0 and self.corr_shock_rel_vol_multiple >= 1.0):
            raise ValueError("correlation-shock ceilings must be positive; relative multiple at least 1")
        if self.target_volatility is None and max(self.gross_cap, self.net_cap, self.per_asset_cap) > 1.0:
            raise ValueError("caps above 1.0 require a fixed target_volatility (owner decision 2026-10-05)")

    def for_period(self, period_seconds: int) -> "RiskConfigV2":
        """Timeframe-specific minimum history. Hourly windows use the hourly minimums."""
        if period_seconds <= HOURLY_PERIOD_SECONDS_MAX:
            return replace(self, min_observations=self.hourly_min_observations,
                           min_observations_per_asset=self.hourly_min_observations_per_asset)
        return self


SECONDS_PER_YEAR = 365 * 86400


def stressed_covariance(cov: np.ndarray, rho: float) -> np.ndarray:
    """Raise every cross-asset correlation to at least rho; keep variances. PSD-repaired by eigenvalue floor."""
    sd = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = cov / np.outer(sd, sd)
    corr = np.where(np.isfinite(corr), corr, 0.0)
    stressed = np.maximum(corr, rho)
    np.fill_diagonal(stressed, 1.0)
    vals, vecs = np.linalg.eigh(stressed)
    if vals.min() < 0:
        stressed = (vecs * np.maximum(vals, 0.0)) @ vecs.T
        stressed = (stressed + stressed.T) / 2
    return stressed * np.outer(sd, sd)


def correlation_shock(w: np.ndarray, cov_period: np.ndarray, period_seconds: int, cfg: "RiskConfigV2",
                      events: list) -> Optional[np.ndarray]:
    """Scale w so stressed annualized volatility is within the operative limit. None = reject."""
    if not np.any(w):
        return w
    ann = SECONDS_PER_YEAR / period_seconds
    vol = lambda c, v: float(math.sqrt(max(v @ c @ v, 0.0) * ann))
    base = vol(cov_period, w)
    stressed = vol(stressed_covariance(cov_period, cfg.corr_shock_level), w)
    diag = vol(stressed_covariance(cov_period, cfg.corr_shock_diagnostic_level), w)
    limit = min(cfg.corr_shock_abs_vol_ceiling, cfg.corr_shock_rel_vol_multiple * base)
    if not all(math.isfinite(v) for v in (base, stressed, diag)) or limit <= 0:
        events.append("zero_exposure:corr_shock_no_compliant_allocation")
        return None
    scale = 1.0 if stressed <= limit else limit / stressed
    events.append(f"corr_shock:unstressed={base:.6g}:stressed@{cfg.corr_shock_level:g}={stressed:.6g}:"
                  f"diagnostic@{cfg.corr_shock_diagnostic_level:g}={diag:.6g}:limit={limit:.6g}:scale={scale:.6g}")
    w = w * scale
    if vol(stressed_covariance(cov_period, cfg.corr_shock_level), w) > limit * (1 + 1e-12):
        events.append("zero_exposure:corr_shock_no_compliant_allocation")
        return None
    return w


PYRAMID_REGIME_CAPS = (1.0, 1.5, 2.0, 2.5, 3.0)
PYRAMID_TARGET_VOL_PER_UNIT_CAP = 0.40
PYRAMID_CEILING_MULTIPLE_OF_TARGET = 1.5


def pyramid_regime_configs() -> dict:
    """Pre-declared pyramid test regimes (owner decision 2026-10-05). Keys: 'pyramid_1.0x' ... 'pyramid_3.0x'."""
    out = {}
    for cap in PYRAMID_REGIME_CAPS:
        target = PYRAMID_TARGET_VOL_PER_UNIT_CAP * cap
        out[f"pyramid_{cap:.1f}x"] = RiskConfigV2(gross_cap=cap, net_cap=cap, per_asset_cap=cap,
                                                 target_volatility=target,
                                                 corr_shock_abs_vol_ceiling=PYRAMID_CEILING_MULTIPLE_OF_TARGET * target)
    return out


class LedoitWolfKellyAllocatorV2(LedoitWolfKellyAllocator):
    """Stage 2 allocator with the Stage 3 guard configuration. Same contract and fail-closed rules."""

    def __init__(self, config: RiskConfigV2 | None = None):
        cfg = config or RiskConfigV2()
        if not isinstance(cfg, RiskConfigV2):
            raise TypeError("LedoitWolfKellyAllocatorV2 requires a RiskConfigV2")
        self.config = cfg
        self.allocator_id = f"lw_kelly_v2@{cfg.sha256[:12]}"

    def allocate(self, mixture: StrategyMixture, returns_window: ReturnsWindow, assets: Sequence[str],
                 state: Optional[MarketStateDistribution] = None) -> RiskAllocation:
        if not isinstance(returns_window, ReturnsWindow):
            raise TypeError("returns_window must be a ReturnsWindow: an untimestamped matrix cannot be PIT-checked")
        cfg, ts, events = self.config.for_period(returns_window.period_seconds), mixture.decision_ts, []
        events.append(f"timeframe_minimums={cfg.min_observations}/{cfg.min_observations_per_asset}")
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
        f = mu / np.diag(cov_h) if rung == "independent_fractional_kelly" else np.linalg.solve(cov_h, mu)
        if not np.all(np.isfinite(f)):
            events.append("zero_exposure:non_finite_kelly_solution")
            return result(zero, "zero_exposure", cond)
        w = cfg.kelly_fraction * f
        w[[a not in mu_by_asset for a in assets]] = 0.0
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
            prior = x[:-cfg.vol_spike_window]                       # strictly before the current window
            baseline = prior[-cfg.vol_spike_baseline_window:]
            recent = x[-cfg.vol_spike_window:].std(axis=0, ddof=1)
            base = baseline.std(axis=0, ddof=1)
            ratio = float(np.max(recent / base))
            if ratio > cfg.vol_spike_ratio:
                events.append(f"vol_spike_guard:ratio={ratio:.4g}:baseline={len(baseline)}:x{cfg.vol_spike_gross_multiplier:g}")
                mult = min(mult, cfg.vol_spike_gross_multiplier)
        if mult < 1.0:
            gross_cap = gross_cap * mult
            events.append(f"dynamic_gross_cap={gross_cap:g}")
        if mult == 0.0:
            events.append("zero_exposure:guard_multiplier_zero")
            return result(zero, "zero_exposure", cond)

        if cfg.target_volatility is not None:                    # annualized (rev3)
            ann = SECONDS_PER_YEAR / returns_window.period_seconds
            vol = float(math.sqrt(max(w @ cov @ w, 0.0) * ann))
            if vol > cfg.target_volatility:
                events.append(f"vol_target_annualized:{vol:.4g}->{cfg.target_volatility:g}")
                w = w * (cfg.target_volatility / vol)
        w = correlation_shock(w, cov, returns_window.period_seconds, cfg, events)
        if w is None:
            return result(zero, "zero_exposure", cond)
        if np.any(np.abs(w) > cfg.per_asset_cap):
            events.append("per_asset_cap:" + ",".join(a for a, v in zip(assets, w) if abs(v) > cfg.per_asset_cap))
            w = np.clip(w, -cfg.per_asset_cap, cfg.per_asset_cap)
        net_cap = min(cfg.net_cap, gross_cap)
        if abs(float(np.sum(w))) > net_cap:
            events.append(f"net_cap:{float(np.sum(w)):.6g}->{net_cap:g}")
            w = _scale_to_cap(w, lambda v: abs(float(np.sum(v))), net_cap)
        if float(np.sum(np.abs(w))) > gross_cap:
            events.append(f"gross_cap:{float(np.sum(np.abs(w))):.6g}")
            w = cap_gross_exactly(w, gross_cap)
        return result(w, rung, cond)
