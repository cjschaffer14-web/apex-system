"""APEX v1.0 typed DAG interfaces (standard library only).

Stage 0 proposed these contracts; Stage 1 applies the four amendments of the Stage 0 review (3 Oct 2026):
  1. TrialRecord: one record per genuinely evaluated hypothesis/parameterization; identical realized returns are
     marked with `return_equivalence_id`, never merged. Only duplicate artifact rows of the SAME trial collapse
     (they become `artifact_refs` of one record).
  2. Experts read only a `SanitizedFeatureSet`: allowlisted namespaces, provenance and `known_at_ts` on every
     feature. The Stage 0 forbidden-name blacklist is gone (an allowlist fails closed).
  3. Router weights are addressed by (expert_id, asset), so one expert can be weighted differently per asset.
  4. Stricter invariants on geometry, risk and execution objects, with explicit cash-flow sign conventions.
Plus: `availability_quality` is mandatory everywhere (now including `source_timestamp`), and coverage-gate types.

    L1 Data & chronology        ObservationFrame (Bar, Observation)
    L2 Structural operators     StructureState (Pivot, SanitizedFeatureSet), GeometryForecast
    L3 Environmental state      MarketStateDistribution
    L4 Strategy experts         ExpertInput -> ExpertForecast
    L5 Mixture router           StrategyMixture
    L6 Risk allocation          RiskAllocation
    L7 Venue execution          ExecutionEvent
    L8 Evidence                 TrialRecord, EvidenceBundle, CoverageResult

Conventions
  * Timestamps are integer UTC epoch seconds; names end in `_ts`.
  * `decision_ts` is the instant a decision is made. Nothing published after it may be visible to that decision.
  * Expected returns use one unit everywhere: LOG return over `horizon_bars` bars of `bar_seconds` each.
  * Cash flows in ExecutionEvent: `fee_paid` and `rebate_received` are both >= 0; `funding_paid` is signed,
    positive = the account paid, negative = the account received.
  * Research only: EvidenceBundle.authority_request is always False. There is no live-order type in this module.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, fields
from enum import Enum
from types import MappingProxyType
from typing import Any, Literal, Mapping, Optional, Protocol, Sequence, runtime_checkable

INTERFACE_VERSION = "1.0.0-stage1"
RETURN_UNIT = "log_return_per_horizon"
DSR_CONFIDENCE_THRESHOLD = 0.95           # a probability-like quantity in [0, 1]; never ">1.0"
PROB_TOL = 1e-9


# ---------------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------------
def _finite(name: str, x: Any) -> None:
    if not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x):
        raise ValueError(f"{name} must be a finite number, got {x!r}")


def _positive(name: str, x: Any) -> None:
    _finite(name, x)
    if x <= 0:
        raise ValueError(f"{name} must be positive, got {x!r}")


def _ts(name: str, x: Any) -> None:
    if not isinstance(x, int) or isinstance(x, bool) or x < 0:
        raise ValueError(f"{name} must be a non-negative integer UTC epoch second, got {x!r}")


def _sha(name: str, v: Optional[str], required: bool = True) -> None:
    if v is None and not required:
        return
    if not isinstance(v, str) or len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
        raise ValueError(f"{name} must be a lowercase hex SHA-256")


def _freeze(m: Mapping[Any, Any] | None) -> Mapping[Any, Any]:
    return MappingProxyType(dict(m or {}))


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (MappingProxyType, dict)):
        return {(k if isinstance(k, str) else "|".join(map(str, k)) if isinstance(k, tuple) else str(k)): _jsonable(v)
                for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return {f.name: _jsonable(getattr(obj, f.name)) for f in fields(obj)}
    return obj


def canonical_json(obj: Any) -> str:
    """Deterministic JSON (sorted keys, no whitespace) used for every hash in the ledger."""
    return json.dumps(_jsonable(obj), sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_of(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()


# ---------------------------------------------------------------------------------------------------------------
# enumerations
# ---------------------------------------------------------------------------------------------------------------
class AvailabilityQuality(str, Enum):
    EXACT_RELEASE = "exact_release"            # release time from an official calendar/archive
    SOURCE_TIMESTAMP = "source_timestamp"      # the source stamps the event/publication itself
    CONSERVATIVE_LAG = "conservative_lag"      # exact time unprovable; a deliberately late assumption is used
    APPROXIMATE = "approximate"                # best effort; excluded from gate-quality evidence by default


QUALITY_RANK = {AvailabilityQuality.EXACT_RELEASE: 0, AvailabilityQuality.SOURCE_TIMESTAMP: 0,
                AvailabilityQuality.CONSERVATIVE_LAG: 1, AvailabilityQuality.APPROXIMATE: 2}


class Verdict(str, Enum):
    CANDIDATE = "candidate"
    STRUCTURAL_ONLY = "structural_only"
    REJECTED = "rejected"


class FillModel(str, Enum):
    CONSERVATIVE_BAR = "conservative_bar"          # default; ambiguity resolves against the strategy
    RESEARCH_OPTIMISTIC = "research_optimistic"    # sensitivity case only; must be labelled wherever reported


class ExecutionKind(str, Enum):
    FILL = "fill"
    UNFILLED = "unfilled"                  # e.g. passive order touched but not provably filled
    STOP = "stop"
    TARGET = "target"
    GAP_FILL = "gap_fill"                  # stop/target gapped through; filled at the open
    FUNDING = "funding"
    FEE = "fee"
    LIQUIDATION = "liquidation"


PRICED_KINDS = {ExecutionKind.FILL, ExecutionKind.STOP, ExecutionKind.TARGET, ExecutionKind.GAP_FILL,
                ExecutionKind.LIQUIDATION}


class ReturnsStatus(str, Enum):
    STORED = "stored"                      # series saved and hashed
    RECONSTRUCTABLE = "reconstructable"    # frozen code+data regenerate it, not yet saved
    UNAVAILABLE = "unavailable"            # cannot enter CSCV/PBO


class TrialStatus(str, Enum):
    EVALUATED = "evaluated"
    FAILED = "failed"                      # crashed / invalid; still counted if a result was seen
    REJECTED = "rejected"


class TrialKind(str, Enum):
    CANDIDATE = "candidate"                # a strategy/parameterization that could have been selected
    CONTROL = "control"                    # placebo / declared control / benchmark
    SENSITIVITY = "sensitivity"            # the same candidate under another cost/execution assumption
    HYPOTHESIS_TEST = "hypothesis_test"    # a statistical test, not a tradable policy (e.g. a geometry cell)


class CoverageStatus(str, Enum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"


# ---------------------------------------------------------------------------------------------------------------
# L1 Data & chronology
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Provenance:
    provenance_id: str
    source: str                            # e.g. "coinbase", "nyfed", "treasury_fiscaldata", "cboe", "bitmex"
    endpoint: str                          # URL or file path the data came from
    retrieved_ts: int
    raw_payload_sha256: str
    parent_baseline_sha256: str            # hash of the frozen DB this artifact descends from
    third_party: bool = False              # True when not the originating authority

    def __post_init__(self) -> None:
        _ts("retrieved_ts", self.retrieved_ts)
        _sha("raw_payload_sha256", self.raw_payload_sha256)
        _sha("parent_baseline_sha256", self.parent_baseline_sha256)


@dataclass(frozen=True)
class Bar:
    asset: str
    venue: str
    open_ts: int
    close_ts: int                          # the bar is usable only at or after close_ts
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        _ts("open_ts", self.open_ts)
        _ts("close_ts", self.close_ts)
        if self.close_ts <= self.open_ts:
            raise ValueError("close_ts must be after open_ts")
        for n in ("open", "high", "low", "close"):
            _positive(n, getattr(self, n))
        _finite("volume", self.volume)
        if self.volume < 0:
            raise ValueError("volume must be non-negative")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("high/low inconsistent with open/close")


@dataclass(frozen=True)
class Observation:
    """One point-in-time, revision-aware value (macro, funding, attention, on-chain...)."""
    source: str
    series_id: str
    observation_ts: int                    # the period/instant the value describes
    published_ts: int                      # when it first became available (release time)
    retrieved_ts: int
    value: float
    availability_quality: AvailabilityQuality
    raw_payload_sha256: str
    vintage_or_release_id: Optional[str] = None

    def __post_init__(self) -> None:
        for n in ("observation_ts", "published_ts", "retrieved_ts"):
            _ts(n, getattr(self, n))
        _finite("value", self.value)
        if self.published_ts < self.observation_ts:
            raise ValueError("published_ts precedes observation_ts: a value cannot be released before it exists")
        if not isinstance(self.availability_quality, AvailabilityQuality):
            raise ValueError("availability_quality is mandatory and must be an AvailabilityQuality")
        _sha("raw_payload_sha256", self.raw_payload_sha256)


@dataclass(frozen=True)
class ObservationFrame:
    """Everything a decision at `decision_ts` may see. Construction fails if anything is from the future."""
    decision_ts: int
    asset: str
    bars: tuple[Bar, ...]
    observations: tuple[Observation, ...] = ()
    data_sha256: str = ""                  # hash of the database/version the frame was cut from

    def __post_init__(self) -> None:
        _ts("decision_ts", self.decision_ts)
        late_bar = [b for b in self.bars if b.close_ts > self.decision_ts]
        if late_bar:
            raise ValueError(f"{len(late_bar)} bar(s) close after decision_ts (look-ahead)")
        late_obs = [o for o in self.observations if o.published_ts > self.decision_ts]
        if late_obs:
            raise ValueError(f"{len(late_obs)} observation(s) published after decision_ts (look-ahead)")
        ts = [b.open_ts for b in self.bars]
        if ts != sorted(ts) or len(ts) != len(set(ts)):
            raise ValueError("bars must be strictly increasing in time")

    def asof(self, series_id: str) -> Optional[Observation]:
        """Latest observation period visible at decision_ts; for that period, its latest published vintage."""
        best = None
        for o in self.observations:
            if o.series_id == series_id and o.published_ts <= self.decision_ts:
                if best is None or (o.observation_ts, o.published_ts) > (best.observation_ts, best.published_ts):
                    best = o
        return best


# ---------------------------------------------------------------------------------------------------------------
# L2 Structural operators and the sanitized feature boundary
# ---------------------------------------------------------------------------------------------------------------
FEATURE_NAMESPACES = ("price_structure", "geometry", "volatility", "liquidity", "macro", "attention", "onchain",
                      "cross_asset")
_FEATURE_NAME = re.compile(r"^(" + "|".join(FEATURE_NAMESPACES) + r")\.[a-z0-9_]+(\.[a-z0-9_]+)*$")
PROVENANCE_PREFIXES = ("data:", "operator:")   # a v10 DB series, or a registered structural operator's output


@dataclass(frozen=True)
class Feature:
    name: str                              # "<namespace>.<name>", namespace from FEATURE_NAMESPACES
    value: float
    known_at_ts: int                       # the earliest instant this value was knowable
    provenance_id: str                     # "data:<table>/<series>" or "operator:<operator_id>@<version>"
    availability_quality: AvailabilityQuality

    def __post_init__(self) -> None:
        if not _FEATURE_NAME.match(self.name):
            raise ValueError(f"feature {self.name!r} is not in an allowlisted namespace {FEATURE_NAMESPACES}")
        _finite(f"feature {self.name}", self.value)
        _ts("known_at_ts", self.known_at_ts)
        if not self.provenance_id.startswith(PROVENANCE_PREFIXES) or len(self.provenance_id) <= 5:
            raise ValueError(f"feature {self.name!r} needs provenance from {PROVENANCE_PREFIXES}")
        if not isinstance(self.availability_quality, AvailabilityQuality):
            raise ValueError("availability_quality is mandatory")


@dataclass(frozen=True)
class SanitizedFeatureSet:
    """The only feature container an expert can receive. Fails closed: unknown namespace, missing provenance,
    or anything known after decision_ts is rejected at construction."""
    decision_ts: int
    features: tuple[Feature, ...]

    def __post_init__(self) -> None:
        _ts("decision_ts", self.decision_ts)
        names = [f.name for f in self.features]
        if len(names) != len(set(names)):
            raise ValueError("feature names must be unique")
        late = [f.name for f in self.features if f.known_at_ts > self.decision_ts]
        if late:
            raise ValueError(f"features known only after decision_ts: {late}")
        for f in self.features:
            if not isinstance(f, Feature):
                raise ValueError("SanitizedFeatureSet holds Feature objects only")

    def value(self, name: str) -> float:
        for f in self.features:
            if f.name == name:
                return f.value
        raise KeyError(name)

    def names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.features)


@dataclass(frozen=True)
class Pivot:
    pivot_ts: int                          # when the extreme happened
    confirmed_ts: int                      # when it became knowable (after the reversal threshold was met)
    kind: Literal[-1, 1]                   # -1 low, +1 high
    price: float
    scale: str

    def __post_init__(self) -> None:
        _ts("pivot_ts", self.pivot_ts)
        _ts("confirmed_ts", self.confirmed_ts)
        if self.confirmed_ts < self.pivot_ts:
            raise ValueError("a pivot cannot be confirmed before it happens")
        if self.kind not in (-1, 1):
            raise ValueError("kind must be -1 (low) or +1 (high)")
        _positive("price", self.price)


@dataclass(frozen=True)
class StructureState:
    decision_ts: int
    asset: str
    pivots: tuple[Pivot, ...]              # confirmed pivots only
    features: SanitizedFeatureSet
    operator_ids: tuple[str, ...] = ()     # which operators (and versions) produced the features

    def __post_init__(self) -> None:
        _ts("decision_ts", self.decision_ts)
        unconfirmed = [p for p in self.pivots if p.confirmed_ts > self.decision_ts]
        if unconfirmed:
            raise ValueError(f"{len(unconfirmed)} unconfirmed/active pivot(s) leaked into StructureState")
        if not isinstance(self.features, SanitizedFeatureSet) or self.features.decision_ts != self.decision_ts:
            raise ValueError("features must be a SanitizedFeatureSet cut at the same decision_ts")


@dataclass(frozen=True)
class GeometryForecast:
    """P(target at ratio r is reached before invalidation within horizon_bars | features at decision_ts)."""
    decision_ts: int
    asset: str
    direction: Literal[-1, 1]
    reference_price: float                 # price the ratios are measured from (e.g. confirmed wave-4 pivot)
    reference_length: float                # swing length the ratios multiply
    ratio_grid: tuple[float, ...]          # strictly increasing; the same grid builds labels and maps predictions
    horizon_bars: int
    reach_probability: tuple[float, ...]   # non-increasing in ratio (farther targets are no more likely)
    invalidation_price: float
    model_id: str

    def __post_init__(self) -> None:
        _ts("decision_ts", self.decision_ts)
        if self.direction not in (-1, 1):
            raise ValueError("direction must be -1 or +1")
        _positive("reference_price", self.reference_price)
        _positive("reference_length", self.reference_length)
        _positive("invalidation_price", self.invalidation_price)
        if not isinstance(self.horizon_bars, int) or self.horizon_bars <= 0:
            raise ValueError("horizon_bars must be a positive integer")
        if len(self.ratio_grid) != len(self.reach_probability) or not self.ratio_grid:
            raise ValueError("ratio_grid and reach_probability must have the same, non-zero length")
        for r in self.ratio_grid:
            _positive("ratio", r)
        if any(b <= a for a, b in zip(self.ratio_grid, self.ratio_grid[1:])):
            raise ValueError("ratio_grid must be strictly increasing")
        for p in self.reach_probability:
            _finite("probability", p)
            if not 0.0 <= p <= 1.0:
                raise ValueError("probabilities must lie in [0, 1]")
        if any(b > a + PROB_TOL for a, b in zip(self.reach_probability, self.reach_probability[1:])):
            raise ValueError("reach probability must be non-increasing with target distance")
        if self.direction == 1 and self.invalidation_price >= self.reference_price:
            raise ValueError("a long projection's invalidation must lie below the reference price")
        if self.direction == -1 and self.invalidation_price <= self.reference_price:
            raise ValueError("a short projection's invalidation must lie above the reference price")
        if any(t <= 0 for t in self.target_prices()):
            raise ValueError("ratio_grid projects a non-positive target price")

    def target_prices(self) -> tuple[float, ...]:
        return tuple(self.reference_price + self.direction * r * self.reference_length for r in self.ratio_grid)


# ---------------------------------------------------------------------------------------------------------------
# L3 Environmental state (descriptive only)
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MarketStateDistribution:
    decision_ts: int
    scope: str                             # asset or "market"
    estimator_id: str                      # e.g. "v09_deterministic_rules@e3415de6", "gmm_k5@<hash>"
    states: tuple[str, ...]
    probabilities: tuple[float, ...]
    persistence: Optional[float] = None    # estimated P(stay in the most likely state next bar)
    feature_provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ts("decision_ts", self.decision_ts)
        if len(self.states) != len(self.probabilities) or len(set(self.states)) != len(self.states):
            raise ValueError("states must be unique and match probabilities")
        if any(not isinstance(p, (int, float)) or p < 0 or not math.isfinite(p) for p in self.probabilities):
            raise ValueError("probabilities must be finite and non-negative")
        if abs(sum(self.probabilities) - 1.0) > 1e-6:
            raise ValueError("probabilities must sum to 1")
        if self.persistence is not None and not 0.0 <= self.persistence <= 1.0:
            raise ValueError("persistence must lie in [0, 1]")

    @property
    def entropy(self) -> float:
        return -sum(p * math.log(p) for p in self.probabilities if p > 0)

    @property
    def most_likely(self) -> str:
        return self.states[max(range(len(self.states)), key=self.probabilities.__getitem__)]

    @classmethod
    def from_label(cls, decision_ts: int, scope: str, estimator_id: str, label: str,
                   states: Sequence[str]) -> "MarketStateDistribution":
        """The v0.9 deterministic classifier as a one-hot distribution (the preserved baseline)."""
        if label not in states:
            raise ValueError(f"unknown state {label!r}")
        return cls(decision_ts, scope, estimator_id, tuple(states), tuple(1.0 if s == label else 0.0 for s in states))


# ---------------------------------------------------------------------------------------------------------------
# L4 Strategy experts
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ExpertInput:
    """Everything an expert may read: sanitized features, confirmed pivots and its own past forecasts.
    There is no field through which account, position, leverage, router, execution or label data could arrive."""
    decision_ts: int
    features: SanitizedFeatureSet
    pivots: tuple[Pivot, ...] = ()
    own_history: tuple["ExpertForecast", ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.features, SanitizedFeatureSet) or self.features.decision_ts != self.decision_ts:
            raise ValueError("features must be a SanitizedFeatureSet cut at the same decision_ts")
        if any(p.confirmed_ts > self.decision_ts for p in self.pivots):
            raise ValueError("experts may see confirmed pivots only")
        if any(f.decision_ts >= self.decision_ts for f in self.own_history):
            raise ValueError("own_history may contain only earlier forecasts")

    @classmethod
    def from_structure(cls, s: StructureState, own_history: tuple["ExpertForecast", ...] = ()) -> "ExpertInput":
        return cls(s.decision_ts, s.features, s.pivots, own_history)


@dataclass(frozen=True)
class ExpertForecast:
    expert_id: str
    asset: str
    decision_ts: int
    horizon_bars: int
    bar_seconds: int
    expected_return: float                 # LOG return over the horizon (RETURN_UNIT)
    expected_volatility: Optional[float]   # st.dev. of that same horizon log return
    confidence: float                      # [0, 1]
    direction_score: float                 # [-1, 1], diagnostic only
    capacity_hint: Optional[float] = None  # notional the expert believes it can absorb, if known
    metadata: Mapping[str, Any] = field(default_factory=dict)
    return_unit: str = RETURN_UNIT

    def __post_init__(self) -> None:
        _ts("decision_ts", self.decision_ts)
        if not isinstance(self.horizon_bars, int) or not isinstance(self.bar_seconds, int) \
                or self.horizon_bars <= 0 or self.bar_seconds <= 0:
            raise ValueError("horizon_bars and bar_seconds must be positive integers")
        _finite("expected_return", self.expected_return)
        if self.expected_volatility is not None:
            _finite("expected_volatility", self.expected_volatility)
            if self.expected_volatility < 0:
                raise ValueError("expected_volatility must be non-negative")
        _finite("confidence", self.confidence)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must lie in [0, 1]")
        _finite("direction_score", self.direction_score)
        if not -1.0 <= self.direction_score <= 1.0:
            raise ValueError("direction_score must lie in [-1, 1]")
        if self.capacity_hint is not None:
            _positive("capacity_hint", self.capacity_hint)
        if self.return_unit != RETURN_UNIT:
            raise ValueError(f"return_unit must be {RETURN_UNIT!r}")
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    @property
    def horizon_seconds(self) -> int:
        return self.horizon_bars * self.bar_seconds

    @property
    def key(self) -> tuple[str, str]:
        """The router addresses forecasts by (expert_id, asset)."""
        return (self.expert_id, self.asset)


# ---------------------------------------------------------------------------------------------------------------
# L5 Mixture router
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class StrategyMixture:
    decision_ts: int
    router_id: str
    state_estimator_id: str
    weights: Mapping[tuple[str, str], float]   # (expert_id, asset) -> relevance; per asset the sum is <= 1
    forecasts: tuple[ExpertForecast, ...]

    def __post_init__(self) -> None:
        _ts("decision_ts", self.decision_ts)
        keys = [f.key for f in self.forecasts]
        if len(keys) != len(set(keys)):
            raise ValueError("one forecast per (expert_id, asset) in a mixture")
        w = dict(self.weights)
        for k, v in w.items():
            if not (isinstance(k, tuple) and len(k) == 2 and all(isinstance(x, str) for x in k)):
                raise ValueError("weights are keyed by (expert_id, asset)")
            _finite(f"weight{k}", v)
            if v < 0:
                raise ValueError("weights must be non-negative")
        if set(w) - set(keys):
            raise ValueError(f"weights for forecasts that do not exist: {sorted(set(w) - set(keys))}")
        per_asset: dict[str, float] = {}
        for (e, a), v in w.items():
            per_asset[a] = per_asset.get(a, 0.0) + v
        over = {a: s for a, s in per_asset.items() if s > 1 + 1e-9}
        if over:
            raise ValueError(f"per-asset weights must sum to at most 1: {over}")
        if len({f.horizon_seconds for f in self.forecasts}) > 1:
            raise ValueError("all forecasts in one mixture must share one horizon (common units for Kelly)")
        if any(f.decision_ts != self.decision_ts for f in self.forecasts):
            raise ValueError("forecasts must be made at the mixture's decision_ts")
        object.__setattr__(self, "weights", _freeze(w))

    def combined_expected_return(self) -> dict[str, float]:
        """Per asset: sum over experts of weight(expert, asset) x expected log return over the common horizon."""
        out: dict[str, float] = {}
        for f in self.forecasts:
            out[f.asset] = out.get(f.asset, 0.0) + self.weights.get(f.key, 0.0) * f.expected_return
        return out


# ---------------------------------------------------------------------------------------------------------------
# L6 Risk allocation
# ---------------------------------------------------------------------------------------------------------------
COVARIANCE_METHODS = ("ledoit_wolf", "ledoit_wolf+eigen_floor", "independent_fractional_kelly", "zero_exposure")


@dataclass(frozen=True)
class RiskAllocation:
    decision_ts: int
    allocator_id: str
    weights: Mapping[str, float]           # fraction of equity per asset (negative = short, if the policy allows)
    per_asset_cap: float
    gross_cap: float
    kelly_fraction: float
    covariance_method: str                 # rung reached on the deterministic fallback ladder
    condition_number: Optional[float]
    guard_events: tuple[str, ...] = ()     # every cap/fallback activation, in order

    def __post_init__(self) -> None:
        _ts("decision_ts", self.decision_ts)
        _positive("per_asset_cap", self.per_asset_cap)
        _positive("gross_cap", self.gross_cap)
        if self.covariance_method not in COVARIANCE_METHODS:
            raise ValueError(f"covariance_method must be one of {COVARIANCE_METHODS}")
        if self.condition_number is not None:
            _finite("condition_number", self.condition_number)
            if self.condition_number < 1.0:
                raise ValueError("a condition number is >= 1")
        for k, v in self.weights.items():
            _finite(f"weights[{k}]", v)
            if abs(v) > self.per_asset_cap + 1e-9:
                raise ValueError(f"{k} weight {v} exceeds the per-asset cap {self.per_asset_cap}")
        if sum(abs(v) for v in self.weights.values()) > self.gross_cap + 1e-9:
            raise ValueError(f"gross exposure exceeds the cap {self.gross_cap}")
        _finite("kelly_fraction", self.kelly_fraction)
        if not 0.0 < self.kelly_fraction <= 1.0:
            raise ValueError("kelly_fraction must lie in (0, 1]")
        if self.covariance_method == "zero_exposure" and any(v != 0 for v in self.weights.values()):
            raise ValueError("the zero-exposure rung must hold no position")
        object.__setattr__(self, "weights", _freeze(self.weights))

    @property
    def gross(self) -> float:
        return sum(abs(v) for v in self.weights.values())


# ---------------------------------------------------------------------------------------------------------------
# L7 Venue execution (simulation records; no live orders exist in this package)
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ExecutionEvent:
    ts: int
    venue: str
    symbol: str
    kind: ExecutionKind
    quantity: float                        # signed base units (+ buy / - sell); 0 for funding/fee rows
    price: Optional[float]                 # required and > 0 for priced kinds; limit price for UNFILLED
    schedule_id: str                       # versioned fee/margin/funding schedule used
    fill_model: FillModel
    fee_paid: float = 0.0                  # >= 0, quote currency
    rebate_received: float = 0.0           # >= 0, quote currency (maker rebates)
    funding_paid: Optional[float] = None   # signed, quote currency: + account paid, - account received
    funding_rate: Optional[float] = None
    funding_event_ts: Optional[int] = None # the venue's recorded settlement time (never a synthetic grid)
    same_bar_ambiguous: bool = False
    ambiguity_resolution: Optional[Literal["pessimistic", "finer_data", "optimistic"]] = None
    mark_price_available: bool = False
    liquidation_approximate: bool = False

    def __post_init__(self) -> None:
        _ts("ts", self.ts)
        if not isinstance(self.kind, ExecutionKind) or not isinstance(self.fill_model, FillModel):
            raise ValueError("kind and fill_model must be enum members")
        _finite("quantity", self.quantity)
        for n in ("fee_paid", "rebate_received"):
            _finite(n, getattr(self, n))
            if getattr(self, n) < 0:
                raise ValueError(f"{n} is a non-negative amount; direction is carried by the field name")
        if self.kind in PRICED_KINDS or self.kind == ExecutionKind.UNFILLED:
            if self.price is None:
                raise ValueError(f"a {self.kind.value} event needs a price")
            _positive("price", self.price)
            if self.kind in PRICED_KINDS and self.quantity == 0:
                raise ValueError(f"a {self.kind.value} event needs a non-zero quantity")
        elif self.price is not None:
            _positive("price", self.price)
        if self.kind == ExecutionKind.UNFILLED and (self.fee_paid or self.rebate_received):
            raise ValueError("an unfilled order pays no fee and earns no rebate")
        if self.kind == ExecutionKind.FUNDING:
            if self.funding_rate is None or self.funding_event_ts is None or self.funding_paid is None:
                raise ValueError("a funding event needs the recorded rate, settlement timestamp and signed payment")
            _finite("funding_rate", self.funding_rate)
            _finite("funding_paid", self.funding_paid)
            _ts("funding_event_ts", self.funding_event_ts)
        elif any(v is not None for v in (self.funding_rate, self.funding_event_ts, self.funding_paid)):
            raise ValueError("funding fields belong to funding events only")
        if self.ambiguity_resolution not in (None, "pessimistic", "finer_data", "optimistic"):
            raise ValueError("ambiguity_resolution must be pessimistic, finer_data or optimistic")
        if self.same_bar_ambiguous and self.ambiguity_resolution is None:
            raise ValueError("an ambiguous same-bar event must state how it was resolved")
        if self.fill_model == FillModel.CONSERVATIVE_BAR and self.ambiguity_resolution == "optimistic":
            raise ValueError("conservative_bar resolves ambiguity pessimistically unless finer data decides")
        if self.kind == ExecutionKind.LIQUIDATION and not self.mark_price_available and not self.liquidation_approximate:
            raise ValueError("liquidation without mark-price data must be flagged approximate")


# ---------------------------------------------------------------------------------------------------------------
# L8 Evidence
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TrialRecord:
    """One genuinely evaluated hypothesis or parameterization (one ledger line).

    Two different hypotheses that happen to produce the same returns stay two records and share a
    `return_equivalence_id`. Only duplicate artifact rows of the same trial collapse into `artifact_refs`."""
    trial_id: str
    source_version: str                    # "v0.5", "v0.5.1", "v0.6", "v0.8", "v0.9", "owner_ideas_2026-10-03", ...
    family: str                            # e.g. "v06.signal_elliott", "v09.long_only_mixture"
    name: str                              # the name the artifact used
    kind: TrialKind
    parameters: Mapping[str, Any]
    asset: str
    venue: str
    product: str                           # "spot", "perp", "pair", "universe", ...
    code_sha256: str
    spec_sha256: Optional[str]
    data_sha256: str
    window: Mapping[str, Any]              # e.g. {"full_sample": [ts0, ts1]} or train/validation/test spans
    cost_model_id: str
    metrics: Mapping[str, Any]             # nominal, as computed at the time
    returns_status: ReturnsStatus
    returns_frequency: Literal["daily", "event", "weekly", "hourly", "none"] = "none"
    returns_ref: Optional[str] = None      # path to the series
    returns_sha256: Optional[str] = None   # hash of the stored file
    return_equivalence_id: Optional[str] = None   # hash of the realized return values (shared by identical paths)
    status: TrialStatus = TrialStatus.EVALUATED
    parent_trial_id: Optional[str] = None  # e.g. the 25 bps trial a 6/85 bps sensitivity belongs to
    viewed_before_later_choice: bool = True    # conservative default: assume it influenced later work
    real_data: bool = True
    artifact_refs: tuple[str, ...] = ()    # every artifact row that records this same trial
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TrialKind) or not isinstance(self.returns_status, ReturnsStatus) \
                or not isinstance(self.status, TrialStatus):
            raise ValueError("kind, returns_status and status must be enum members")
        _sha("code_sha256", self.code_sha256)
        _sha("data_sha256", self.data_sha256)
        _sha("spec_sha256", self.spec_sha256, required=False)
        if self.returns_status == ReturnsStatus.STORED:
            if not self.returns_ref:
                raise ValueError("a stored return series needs a path")
            _sha("returns_sha256", self.returns_sha256)
            _sha("return_equivalence_id", self.return_equivalence_id)
            if self.returns_frequency == "none":
                raise ValueError("a stored return series needs its frequency")
        if self.returns_status == ReturnsStatus.UNAVAILABLE and (self.returns_sha256 or self.return_equivalence_id):
            raise ValueError("an unavailable series cannot carry a hash")
        if self.kind == TrialKind.SENSITIVITY and not self.parent_trial_id:
            raise ValueError("a sensitivity trial must name the trial it varies")
        object.__setattr__(self, "parameters", _freeze(self.parameters))
        object.__setattr__(self, "window", _freeze(self.window))
        object.__setattr__(self, "metrics", _freeze(self.metrics))

    def identity_sha256(self) -> str:
        """What defines the trial. Same identity = the same trial recorded twice (collapse into artifact_refs)."""
        ident = {k: getattr(self, k) for k in ("source_version", "family", "name", "parameters", "asset", "venue",
                                               "product", "code_sha256", "spec_sha256", "data_sha256", "window",
                                               "cost_model_id")}
        return sha256_of(ident)


@dataclass(frozen=True)
class EvidenceBundle:
    schema_version: str
    bundle_id: str
    created_ts: int
    source_ai: str
    role: str
    trial_ids: tuple[str, ...]
    n_trials_counted: int                  # conservative: every viewed trial in the ledger at evaluation time
    verdict: Verdict
    dsr: Optional[float]                   # computed with n_trials_counted
    pbo: Optional[float]
    pbo_matrix_sha256: Optional[str]       # PBO is allowed only with an aligned per-period return matrix
    holdout_accessed: bool
    code_sha256: str
    data_sha256: str
    spec_sha256: Optional[str]
    execution_model_id: str
    n_trials_effective: Optional[float] = None       # dependence-adjusted, reported alongside, never instead
    n_return_equivalence_classes: Optional[int] = None
    observations: tuple[str, ...] = ()
    falsifiers: tuple[str, ...] = ()
    dsr_threshold: float = DSR_CONFIDENCE_THRESHOLD
    authority_request: bool = False

    def __post_init__(self) -> None:
        _ts("created_ts", self.created_ts)
        _sha("code_sha256", self.code_sha256)
        _sha("data_sha256", self.data_sha256)
        _sha("spec_sha256", self.spec_sha256, required=False)
        if self.authority_request is not False:
            raise ValueError("research evidence can never request authority")
        if self.dsr_threshold != DSR_CONFIDENCE_THRESHOLD:
            raise ValueError(f"the DSR gate is fixed at {DSR_CONFIDENCE_THRESHOLD}")
        if self.dsr is not None and not 0.0 <= self.dsr <= 1.0:
            raise ValueError("DSR is a probability-like quantity in [0, 1]")
        if self.pbo is not None:
            if not 0.0 <= self.pbo <= 1.0:
                raise ValueError("PBO must lie in [0, 1]")
            _sha("pbo_matrix_sha256", self.pbo_matrix_sha256)
        if self.n_trials_counted < len(set(self.trial_ids)):
            raise ValueError("n_trials_counted cannot be smaller than the trials cited")
        if self.n_trials_effective is not None and not 0 < self.n_trials_effective <= self.n_trials_counted:
            raise ValueError("the effective trial count lies in (0, n_trials_counted]")
        if self.verdict == Verdict.CANDIDATE and (self.dsr is None or self.dsr < self.dsr_threshold):
            raise ValueError("'candidate' requires DSR >= 0.95 (otherwise structural_only or rejected)")
        if self.verdict == Verdict.CANDIDATE and self.holdout_accessed:
            raise ValueError("a result that touched the protected holdout during selection cannot be a candidate")

    def sha256(self) -> str:
        return sha256_of(self)


@dataclass(frozen=True)
class CoverageResult:
    """Data-sufficiency verdict for one data family over one requested window."""
    family: str
    requested_start_ts: int
    requested_end_ts: int
    available_start_ts: Optional[int]
    available_end_ts: Optional[int]
    coverage_fraction: float               # share of expected observations present inside the requested window
    worst_quality: AvailabilityQuality
    status: CoverageStatus
    reason: str = ""

    def __post_init__(self) -> None:
        _ts("requested_start_ts", self.requested_start_ts)
        _ts("requested_end_ts", self.requested_end_ts)
        if self.requested_end_ts < self.requested_start_ts:
            raise ValueError("requested window is reversed")
        _finite("coverage_fraction", self.coverage_fraction)
        if not 0.0 <= self.coverage_fraction <= 1.0:
            raise ValueError("coverage_fraction must lie in [0, 1]")
        if not isinstance(self.status, CoverageStatus) or not isinstance(self.worst_quality, AvailabilityQuality):
            raise ValueError("status and worst_quality must be enum members")


# ---------------------------------------------------------------------------------------------------------------
# Layer component protocols (implementations arrive in Stages 2-4)
# ---------------------------------------------------------------------------------------------------------------
@runtime_checkable
class DataSource(Protocol):
    source_id: str
    def frame(self, asset: str, decision_ts: int) -> ObservationFrame: ...


@runtime_checkable
class StructuralOperator(Protocol):
    operator_id: str
    def transform(self, frame: ObservationFrame) -> StructureState: ...


@runtime_checkable
class StateEstimator(Protocol):
    estimator_id: str
    def estimate(self, structure: StructureState) -> MarketStateDistribution: ...


@runtime_checkable
class StrategyExpert(Protocol):
    expert_id: str
    def forecast(self, inp: ExpertInput) -> Sequence[ExpertForecast]: ...


@runtime_checkable
class Router(Protocol):
    router_id: str
    def route(self, state: MarketStateDistribution, forecasts: Sequence[ExpertForecast]) -> StrategyMixture: ...


@runtime_checkable
class RiskAllocator(Protocol):
    allocator_id: str
    def allocate(self, mixture: StrategyMixture, returns_window: Sequence[Sequence[float]],
                 assets: Sequence[str]) -> RiskAllocation: ...


@runtime_checkable
class ExecutionModel(Protocol):
    model_id: str
    fill_model: FillModel
    def simulate(self, allocation: RiskAllocation, bars: Sequence[Bar],
                 funding: Sequence[Observation]) -> Sequence[ExecutionEvent]: ...


def expert_reachable_fields() -> set[str]:
    """Field names an expert can reach through its input (tests prove no account/router/label channel exists)."""
    return ({f.name for f in fields(ExpertInput)} | {f.name for f in fields(SanitizedFeatureSet)}
            | {f.name for f in fields(Feature)} | {f.name for f in fields(Pivot)} | {f.name for f in fields(ExpertForecast)})


__all__ = [n for n in dir() if not n.startswith("_")]
