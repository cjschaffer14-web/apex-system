"""APEX v1.0 typed DAG interfaces (Stage 0 proposal; standard library only).

Every object passed between the eight DAG layers is a frozen dataclass that validates itself on construction, so
a contract violation fails loudly at the boundary instead of silently corrupting a backtest.

    L1 Data & chronology        ObservationFrame (Bar, Observation)
    L2 Structural operators     StructureState (Pivot), GeometryForecast
    L3 Environmental state      MarketStateDistribution
    L4 Strategy experts         ExpertInput -> ExpertForecast
    L5 Mixture router           StrategyMixture
    L6 Risk allocation          RiskAllocation
    L7 Venue execution          ExecutionEvent
    L8 Evidence                 TrialRecord, EvidenceBundle

Conventions
  * Timestamps are integer UTC epoch seconds; names end in `_ts`.
  * `decision_ts` is the instant a decision is made. Nothing published after it may be visible to that decision.
  * Expected returns use one unit everywhere: LOG return over `horizon_bars` bars of `bar_seconds` each.
  * State labels are descriptive. Nothing in L3 can size a trade; nothing in L4 can read account, leverage, router
    output or future labels.
  * Research only: EvidenceBundle.authority_request is always False. There is no live-order type in this module.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from types import MappingProxyType
from typing import Any, Literal, Mapping, Optional, Protocol, Sequence, runtime_checkable

INTERFACE_VERSION = "1.0.0-stage0"
RETURN_UNIT = "log_return_per_horizon"
DSR_CONFIDENCE_THRESHOLD = 0.95           # a probability-like quantity in [0, 1]; never ">1.0"
PROB_TOL = 1e-9


# ---------------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------------
def _finite(name: str, x: float) -> None:
    if not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x):
        raise ValueError(f"{name} must be a finite number, got {x!r}")


def _ts(name: str, x: int) -> None:
    if not isinstance(x, int) or isinstance(x, bool) or x < 0:
        raise ValueError(f"{name} must be a non-negative integer UTC epoch second, got {x!r}")


def _freeze(m: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(m or {}))


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, MappingProxyType) or isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
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
    EXACT_RELEASE = "exact_release"            # release timestamp taken from an official calendar/archive
    CONSERVATIVE_LAG = "conservative_lag"      # exact time unprovable; a deliberately late assumption is used
    APPROXIMATE = "approximate"                # best effort; excluded from gate-quality evidence by default


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


class ReturnsStatus(str, Enum):
    STORED = "stored"                      # per-period series saved and hashed
    RECONSTRUCTABLE = "reconstructable"    # frozen code+data regenerate it (verified in Stage 0 / Stage 1)
    UNAVAILABLE = "unavailable"            # cannot enter CSCV/PBO


class TrialStatus(str, Enum):
    EVALUATED = "evaluated"
    FAILED = "failed"                      # crashed / invalid; still counted if a result was seen
    REJECTED = "rejected"


# ---------------------------------------------------------------------------------------------------------------
# L1 Data & chronology
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Provenance:
    source: str                            # e.g. "coinbase", "nyfed", "treasury_fiscaldata", "cboe", "bitmex"
    endpoint: str                          # URL template or file path the data came from
    retrieved_ts: int
    raw_payload_sha256: str
    parent_baseline_sha256: str            # hash of the frozen DB this artifact descends from
    third_party: bool = False              # True when not the originating authority (e.g. a library mirror)

    def __post_init__(self) -> None:
        _ts("retrieved_ts", self.retrieved_ts)
        for n in ("raw_payload_sha256", "parent_baseline_sha256"):
            v = getattr(self, n)
            if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
                raise ValueError(f"{n} must be a lowercase hex SHA-256")


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
        for n in ("open", "high", "low", "close", "volume"):
            _finite(n, getattr(self, n))
        if min(self.open, self.high, self.low, self.close) <= 0 or self.volume < 0:
            raise ValueError("prices must be positive and volume non-negative")
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
            raise ValueError("availability_quality must be an AvailabilityQuality")


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
        """Latest value whose published_ts <= decision_ts (ties broken by the later observation)."""
        best = None
        for o in self.observations:
            if o.series_id == series_id and o.published_ts <= self.decision_ts:
                if best is None or (o.observation_ts, o.published_ts) > (best.observation_ts, best.published_ts):
                    best = o
        return best


# ---------------------------------------------------------------------------------------------------------------
# L2 Structural operators
# ---------------------------------------------------------------------------------------------------------------
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
        _finite("price", self.price)


@dataclass(frozen=True)
class StructureState:
    decision_ts: int
    asset: str
    pivots: tuple[Pivot, ...]              # confirmed pivots only
    features: Mapping[str, float] = field(default_factory=dict)
    operator_ids: tuple[str, ...] = ()     # which operators (and versions) produced the features

    def __post_init__(self) -> None:
        _ts("decision_ts", self.decision_ts)
        unconfirmed = [p for p in self.pivots if p.confirmed_ts > self.decision_ts]
        if unconfirmed:
            raise ValueError(f"{len(unconfirmed)} unconfirmed/active pivot(s) leaked into StructureState")
        for k, v in self.features.items():
            _finite(f"features[{k}]", v)
        object.__setattr__(self, "features", _freeze(self.features))


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
        if len(self.ratio_grid) != len(self.reach_probability) or not self.ratio_grid:
            raise ValueError("ratio_grid and reach_probability must have the same, non-zero length")
        if any(b <= a for a, b in zip(self.ratio_grid, self.ratio_grid[1:])):
            raise ValueError("ratio_grid must be strictly increasing")
        if any(not 0.0 <= p <= 1.0 for p in self.reach_probability):
            raise ValueError("probabilities must lie in [0, 1]")
        if any(b > a + PROB_TOL for a, b in zip(self.reach_probability, self.reach_probability[1:])):
            raise ValueError("reach probability must be non-increasing with target distance")
        if self.horizon_bars <= 0:
            raise ValueError("horizon_bars must be positive")

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
        if any(p < 0 or not math.isfinite(p) for p in self.probabilities):
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
FORBIDDEN_EXPERT_INPUTS = frozenset({
    "equity", "account", "balance", "leverage", "margin", "position", "positions", "allocation", "weights",
    "router", "router_output", "mixture", "future", "label", "labels", "target", "pnl",
})


@dataclass(frozen=True)
class ExpertInput:
    """The only thing an expert may read: sanitized structure and its own past forecasts."""
    decision_ts: int
    structure: StructureState
    own_history: tuple["ExpertForecast", ...] = ()

    def __post_init__(self) -> None:
        if self.structure.decision_ts != self.decision_ts:
            raise ValueError("structure must be cut at the same decision_ts")
        if any(f.decision_ts >= self.decision_ts for f in self.own_history):
            raise ValueError("own_history may contain only earlier forecasts")
        leaked = {k for k in self.structure.features if k.lower() in FORBIDDEN_EXPERT_INPUTS}
        if leaked:
            raise ValueError(f"structure features carry forbidden expert inputs: {sorted(leaked)}")


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
        if self.horizon_bars <= 0 or self.bar_seconds <= 0:
            raise ValueError("horizon_bars and bar_seconds must be positive")
        _finite("expected_return", self.expected_return)
        if self.expected_volatility is not None:
            _finite("expected_volatility", self.expected_volatility)
            if self.expected_volatility < 0:
                raise ValueError("expected_volatility must be non-negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must lie in [0, 1]")
        if not -1.0 <= self.direction_score <= 1.0:
            raise ValueError("direction_score must lie in [-1, 1]")
        if self.return_unit != RETURN_UNIT:
            raise ValueError(f"return_unit must be {RETURN_UNIT!r}")
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    @property
    def horizon_seconds(self) -> int:
        return self.horizon_bars * self.bar_seconds


# ---------------------------------------------------------------------------------------------------------------
# L5 Mixture router
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class StrategyMixture:
    decision_ts: int
    router_id: str
    state_estimator_id: str
    expert_weights: Mapping[str, float]    # non-negative; 1 - sum is cash/abstain
    forecasts: tuple[ExpertForecast, ...]

    def __post_init__(self) -> None:
        _ts("decision_ts", self.decision_ts)
        w = dict(self.expert_weights)
        if any(v < 0 or not math.isfinite(v) for v in w.values()) or sum(w.values()) > 1 + 1e-9:
            raise ValueError("expert weights must be finite, non-negative and sum to at most 1")
        ids = {f.expert_id for f in self.forecasts}
        if set(w) - ids:
            raise ValueError(f"weights for experts without a forecast: {sorted(set(w) - ids)}")
        if len({f.horizon_seconds for f in self.forecasts}) > 1:
            raise ValueError("all forecasts in one mixture must share one horizon (common units for Kelly)")
        if any(f.decision_ts != self.decision_ts for f in self.forecasts):
            raise ValueError("forecasts must be made at the mixture's decision_ts")
        object.__setattr__(self, "expert_weights", _freeze(w))

    def combined_expected_return(self) -> dict[str, float]:
        """Weighted expected log return per asset over the common horizon (weights act on forecasts, not P&L)."""
        out: dict[str, float] = {}
        for f in self.forecasts:
            out[f.asset] = out.get(f.asset, 0.0) + self.expert_weights.get(f.expert_id, 0.0) * f.expected_return
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
        if self.covariance_method not in COVARIANCE_METHODS:
            raise ValueError(f"covariance_method must be one of {COVARIANCE_METHODS}")
        for k, v in self.weights.items():
            _finite(f"weights[{k}]", v)
            if abs(v) > self.per_asset_cap + 1e-9:
                raise ValueError(f"{k} weight {v} exceeds the per-asset cap {self.per_asset_cap}")
        if self.gross > self.gross_cap + 1e-9:
            raise ValueError(f"gross exposure {self.gross} exceeds the cap {self.gross_cap}")
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
    price: Optional[float]
    fee: float                             # in quote currency, >= 0 means paid
    schedule_id: str                       # versioned fee/margin/funding schedule used
    fill_model: FillModel
    funding_rate: Optional[float] = None
    funding_event_ts: Optional[int] = None # the venue's recorded settlement time (never a synthetic grid)
    same_bar_ambiguous: bool = False
    ambiguity_resolution: Optional[Literal["pessimistic", "finer_data", "optimistic"]] = None
    mark_price_available: bool = False
    liquidation_approximate: bool = False

    def __post_init__(self) -> None:
        _ts("ts", self.ts)
        _finite("quantity", self.quantity)
        _finite("fee", self.fee)
        if self.price is not None:
            _finite("price", self.price)
        if self.kind == ExecutionKind.FUNDING:
            if self.funding_rate is None or self.funding_event_ts is None:
                raise ValueError("a funding event needs the recorded rate and settlement timestamp")
            _finite("funding_rate", self.funding_rate)
        if self.same_bar_ambiguous and self.ambiguity_resolution is None:
            raise ValueError("an ambiguous same-bar event must state how it was resolved")
        if self.ambiguity_resolution not in (None, "pessimistic", "finer_data", "optimistic"):
            raise ValueError("ambiguity_resolution must be pessimistic, finer_data or optimistic")
        if self.fill_model == FillModel.CONSERVATIVE_BAR and self.ambiguity_resolution == "optimistic":
            raise ValueError("conservative_bar resolves ambiguity pessimistically unless finer data decides")
        if self.kind == ExecutionKind.LIQUIDATION and not self.mark_price_available and not self.liquidation_approximate:
            raise ValueError("liquidation without mark-price data must be flagged approximate")


# ---------------------------------------------------------------------------------------------------------------
# L8 Evidence
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TrialRecord:
    """One actual evaluated candidate (one ledger line). Never a repeated aggregate or a 'trial_count'."""
    trial_id: str                          # = identity_sha256()[:16] unless imported from a legacy batch
    family: str                            # e.g. "v06.signal_elliott", "v09.long_only_mixture"
    parameters: Mapping[str, Any]
    asset: str
    venue: str
    product: str                           # "spot", "perp", ...
    code_sha256: str
    spec_sha256: Optional[str]
    data_sha256: str
    window: Mapping[str, Any]              # {"train": [ts0, ts1], "validation": [...], "test": [...]} or full-sample
    cost_model_id: str
    metrics: Mapping[str, float]           # nominal, as computed at the time
    returns_status: ReturnsStatus
    returns_ref: Optional[str] = None      # path to the per-period series
    returns_sha256: Optional[str] = None
    status: TrialStatus = TrialStatus.EVALUATED
    parent_trial_id: Optional[str] = None
    viewed_before_later_choice: bool = True    # conservative default: assume it influenced later work
    source_artifact: Optional[str] = None      # e.g. "results/btc_v06_historical_25bps.json#runs[12]"

    def __post_init__(self) -> None:
        if self.returns_status == ReturnsStatus.STORED and not (self.returns_ref and self.returns_sha256):
            raise ValueError("a stored return series needs a path and its SHA-256")
        if self.returns_status == ReturnsStatus.UNAVAILABLE and self.returns_sha256:
            raise ValueError("an unavailable series cannot carry a hash")
        object.__setattr__(self, "parameters", _freeze(self.parameters))
        object.__setattr__(self, "window", _freeze(self.window))
        object.__setattr__(self, "metrics", _freeze(self.metrics))

    def identity_sha256(self) -> str:
        """Same family + parameters + asset/venue/product + code/data/spec + window + cost model = same trial."""
        ident = {k: getattr(self, k) for k in ("family", "parameters", "asset", "venue", "product", "code_sha256",
                                               "spec_sha256", "data_sha256", "window", "cost_model_id")}
        return sha256_of(ident)


@dataclass(frozen=True)
class EvidenceBundle:
    schema_version: str
    bundle_id: str
    created_ts: int
    source_ai: str
    role: str
    trial_ids: tuple[str, ...]
    n_trials_counted: int                  # distinct actual trials in the ledger at evaluation time
    verdict: Verdict
    dsr: Optional[float]
    pbo: Optional[float]
    pbo_matrix_sha256: Optional[str]       # PBO is allowed only with an aligned per-period return matrix
    holdout_accessed: bool
    code_sha256: str
    data_sha256: str
    spec_sha256: Optional[str]
    execution_model_id: str
    observations: tuple[str, ...] = ()
    falsifiers: tuple[str, ...] = ()
    dsr_threshold: float = DSR_CONFIDENCE_THRESHOLD
    authority_request: bool = False

    def __post_init__(self) -> None:
        _ts("created_ts", self.created_ts)
        if self.authority_request is not False:
            raise ValueError("research evidence can never request authority")
        if self.dsr_threshold != DSR_CONFIDENCE_THRESHOLD:
            raise ValueError(f"the DSR gate is fixed at {DSR_CONFIDENCE_THRESHOLD}")
        if self.dsr is not None and not 0.0 <= self.dsr <= 1.0:
            raise ValueError("DSR is a probability-like quantity in [0, 1]")
        if self.pbo is not None:
            if not 0.0 <= self.pbo <= 1.0:
                raise ValueError("PBO must lie in [0, 1]")
            if not self.pbo_matrix_sha256:
                raise ValueError("PBO without an aligned return matrix is not allowed")
        if self.n_trials_counted < len(set(self.trial_ids)):
            raise ValueError("n_trials_counted cannot be smaller than the trials cited")
        if self.verdict == Verdict.CANDIDATE and (self.dsr is None or self.dsr < self.dsr_threshold):
            raise ValueError("'candidate' requires DSR >= 0.95 (otherwise structural_only or rejected)")
        if self.verdict == Verdict.CANDIDATE and self.holdout_accessed:
            raise ValueError("a result that touched the protected holdout during selection cannot be a candidate")

    def sha256(self) -> str:
        return sha256_of(self)


# ---------------------------------------------------------------------------------------------------------------
# Layer component protocols (implementations arrive in Stages 1-4)
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


def expert_input_fields() -> set[str]:
    """Field names an expert can reach (used by tests to prove none is forbidden)."""
    reach = {f.name for f in fields(ExpertInput)} | {f.name for f in fields(StructureState)} \
        | {f.name for f in fields(ExpertForecast)}
    return reach


__all__ = [n for n in dir() if not n.startswith("_")]
