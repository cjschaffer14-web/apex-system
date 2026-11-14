#!/usr/bin/env python3
"""Read-only Global Arbitrage Observatory for APEX.

This module never submits orders. It measures cross-venue price state, detects
misalignment episodes, estimates net-realizable value, and compares classical
pair-spread chasing with portfolio-state rebalancing using pre-positioned
inventory.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import math
import statistics
import time
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple


class Lane(str, Enum):
    DEX_DEX = "dex_dex"
    CEX_DEX = "cex_dex"
    STABLE_WRAPPED_BASIS = "stable_wrapped_basis"
    ORACLE_LIQUIDATION = "oracle_liquidation"  # reported separately; never merged into swap-arb P&L


@dataclass(frozen=True)
class MarketObservation:
    ts_ns: int
    asset: str
    economic_venue: str
    domain: str
    source_id: str
    bid: float
    ask: float
    bid_depth_usd: float
    ask_depth_usd: float
    explicit_fee_bps: float = 0.0
    reliability: float = 1.0
    source_kind: str = "direct"  # direct, rpc, aggregator, cex
    executable: bool = True
    lane: Lane = Lane.DEX_DEX
    metadata: Mapping[str, object] = field(default_factory=dict)

    def validate(self) -> None:
        if not all(math.isfinite(x) for x in (self.bid,self.ask,self.bid_depth_usd,self.ask_depth_usd,self.explicit_fee_bps,self.reliability)) or self.explicit_fee_bps<0:
            raise ValueError("invalid finite observation inputs")
        if not (self.bid > 0 and self.ask > 0 and self.ask >= self.bid):
            raise ValueError("invalid two-sided market")
        if min(self.bid_depth_usd, self.ask_depth_usd) < 0:
            raise ValueError("negative depth")
        if not (0 <= self.reliability <= 1):
            raise ValueError("reliability must be within [0,1]")

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


@dataclass(frozen=True)
class GlobalShadowPrice:
    asset: str
    ts_ns: int
    price: float
    independent_venues: int
    raw_sources: int
    effective_depth_usd: float
    confidence: float
    venues: Tuple[str, ...]
    rejected_sources: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CostEstimate:
    pool_fee_usd: float = 0.0
    gas_usd: float = 0.0
    ordering_usd: float = 0.0
    hedge_usd: float = 0.0
    failed_attempt_usd: float = 0.0
    inventory_financing_usd: float = 0.0
    rebalance_usd: float = 0.0
    adverse_move_usd: float = 0.0
    bridge_usd: float = 0.0

    @property
    def total_usd(self) -> float:
        return sum(asdict(self).values())


@dataclass(frozen=True)
class OpportunityMeasurement:
    ts_ns: int
    lane: Lane
    asset: str
    buy_venue: str
    sell_venue: str
    domain_pair: str
    global_price: float
    local_buy_price: float
    local_sell_price: float
    gross_edge_bps: float
    executable_value_usd: float
    costs: CostEstimate
    estimated_net_edge_usd: float
    expected_turnover_usd: float
    confidence: float
    data_quality_flags: Tuple[str, ...] = ()
    capture_evidence: Optional[str] = None


@dataclass
class Episode:
    episode_id: str
    key: Tuple[str, str, str, str]
    lane: Lane
    asset: str
    buy_venue: str
    sell_venue: str
    birth_ns: int
    last_seen_ns: int
    max_spread_bps: float
    max_executable_value_usd: float
    max_estimated_net_edge_usd: float
    peak_ns: int
    half_life_ns: Optional[int] = None
    capture_ns: Optional[int] = None
    observations: int = 1
    capture_evidence: Optional[str] = None
    confidence_min: float = 1.0
    data_quality_flags: set = field(default_factory=set)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["lane"] = self.lane.value
        d["key"] = list(self.key)
        d["data_quality_flags"] = sorted(self.data_quality_flags)
        d["persistence_seconds"] = max(0.0, (self.last_seen_ns - self.birth_ns) / 1e9)
        d["half_life_seconds"] = None if self.half_life_ns is None else self.half_life_ns / 1e9
        return d


class ShadowPriceEngine:
    """Robust global price estimator using independent economic venues.

    Multiple RPCs or aggregators for the same economic venue improve source
    reliability but do not multiply venue independence.
    """

    def __init__(self, freshness_half_life_s: float = 4.0, max_age_s: float = 20.0):
        self.freshness_half_life_s = freshness_half_life_s
        self.max_age_s = max_age_s

    def build(self, asset: str, observations: Sequence[MarketObservation], now_ns: Optional[int] = None) -> GlobalShadowPrice:
        now_ns = time.time_ns() if now_ns is None else now_ns
        valid: List[MarketObservation] = []
        rejected: List[str] = []
        for obs in observations:
            try:
                obs.validate()
            except ValueError:
                rejected.append(obs.source_id)
                continue
            if obs.asset != asset:
                continue
            age_s = max(0.0, (now_ns - obs.ts_ns) / 1e9)
            if obs.ts_ns > now_ns or not obs.executable or age_s > self.max_age_s:
                rejected.append(obs.source_id)
                continue
            valid.append(obs)
        if not valid:
            raise ValueError(f"no fresh observations for {asset}")

        # Collapse redundant RPC/source observations for the same economic venue.
        by_venue: Dict[str, List[MarketObservation]] = {}
        for obs in valid:
            by_venue.setdefault(obs.economic_venue, []).append(obs)

        venue_rows: List[Tuple[str, float, float, float]] = []  # venue, price, weight, effective_depth
        for venue, rows in by_venue.items():
            mids = [r.mid for r in rows]
            price = statistics.median(mids)
            effective_depth = min(min(r.bid_depth_usd, r.ask_depth_usd) for r in rows)
            best_reliability = max(r.reliability for r in rows)
            newest_ns = max(r.ts_ns for r in rows)
            age_s = max(0.0, (now_ns - newest_ns) / 1e9)
            freshness = 0.5 ** (age_s / max(self.freshness_half_life_s, 1e-9))
            fee_penalty = 1.0 / (1.0 + statistics.median(r.explicit_fee_bps for r in rows) / 10.0)
            exec_penalty = 1.0 if any(r.executable for r in rows) else 0.25
            depth_weight = math.sqrt(max(effective_depth, 1.0))
            weight = freshness * best_reliability * fee_penalty * exec_penalty * depth_weight
            venue_rows.append((venue, price, max(weight, 1e-12), effective_depth))

        venue_rows.sort(key=lambda r: r[1])
        total_w = sum(r[2] for r in venue_rows)
        acc = 0.0
        weighted_median = venue_rows[-1][1]
        for row in venue_rows:
            acc += row[2]
            if acc >= total_w / 2:
                weighted_median = row[1]
                break

        # Robust reweighting around the cross-venue weighted median.
        deviations = [abs(r[1] / weighted_median - 1.0) for r in venue_rows]
        mad = statistics.median(deviations) if deviations else 0.0
        scale = max(5e-5, 3.0 * mad)
        robust_rows = []
        for venue, price, weight, depth in venue_rows:
            z = abs(price / weighted_median - 1.0) / scale
            robust_factor = 1.0 if z <= 1 else 1.0 / z
            robust_rows.append((venue, price, weight * robust_factor, depth))
        denom = sum(r[2] for r in robust_rows)
        price = sum(r[1] * r[2] for r in robust_rows) / denom
        concentration = max(r[2] for r in robust_rows) / denom
        independence = len(robust_rows)
        confidence = min(1.0, (independence / 4.0)) * max(0.0, 1.0 - max(0.0, concentration - 0.5))
        return GlobalShadowPrice(
            asset=asset,
            ts_ns=now_ns,
            price=price,
            independent_venues=independence,
            raw_sources=len(valid),
            effective_depth_usd=sum(r[3] for r in robust_rows),
            confidence=confidence,
            venues=tuple(sorted(by_venue)),
            rejected_sources=tuple(sorted(rejected)),
        )


class NetRealizableValue:
    @staticmethod
    def estimate(
        notional_usd: float,
        gross_edge_bps: float,
        *,
        pool_fee_bps: float = 0.0,
        gas_usd: float = 0.0,
        ordering_usd: float = 0.0,
        hedge_bps: float = 0.0,
        failed_attempt_probability: float = 0.0,
        failed_attempt_cost_usd: float = 0.0,
        inventory_financing_bps: float = 0.0,
        rebalance_bps: float = 0.0,
        adverse_move_bps: float = 0.0,
        bridge_usd: float = 0.0,
    ) -> Tuple[CostEstimate, float]:
        if notional_usd < 0:
            raise ValueError("negative notional")
        costs = CostEstimate(
            pool_fee_usd=notional_usd * pool_fee_bps / 1e4,
            gas_usd=gas_usd,
            ordering_usd=ordering_usd,
            hedge_usd=notional_usd * hedge_bps / 1e4,
            failed_attempt_usd=max(0.0, failed_attempt_probability) * failed_attempt_cost_usd,
            inventory_financing_usd=notional_usd * inventory_financing_bps / 1e4,
            rebalance_usd=notional_usd * rebalance_bps / 1e4,
            adverse_move_usd=notional_usd * adverse_move_bps / 1e4,
            bridge_usd=bridge_usd,
        )
        gross = notional_usd * gross_edge_bps / 1e4
        return costs, gross - costs.total_usd


class EpisodeTracker:
    """Deduplicates a persistent dislocation into one economic episode."""

    def __init__(self, open_threshold_bps: float = 5.0, close_threshold_bps: float = 2.0, gap_tolerance_s: float = 15.0):
        self.open_threshold_bps = open_threshold_bps
        self.close_threshold_bps = close_threshold_bps
        self.gap_tolerance_ns = int(gap_tolerance_s * 1e9)
        self.active: Dict[Tuple[str, str, str, str], Episode] = {}
        self.closed: List[Episode] = []
        self.counter = 0

    def _key(self, m: OpportunityMeasurement) -> Tuple[str, str, str, str]:
        return (m.lane.value, m.asset, m.buy_venue, m.sell_venue)

    def ingest(self, m: OpportunityMeasurement) -> Optional[Episode]:
        key = self._key(m)
        current = self.active.get(key)
        if current and m.ts_ns - current.last_seen_ns > self.gap_tolerance_ns:
            self._close(key, capture=False, evidence="observation_gap")
            current = None
        if current is None:
            if m.gross_edge_bps < self.open_threshold_bps:
                return None
            self.counter += 1
            eid = f"ep-{self.counter:08d}"
            self.active[key] = Episode(
                episode_id=eid,
                key=key,
                lane=m.lane,
                asset=m.asset,
                buy_venue=m.buy_venue,
                sell_venue=m.sell_venue,
                birth_ns=m.ts_ns,
                last_seen_ns=m.ts_ns,
                max_spread_bps=m.gross_edge_bps,
                max_executable_value_usd=m.executable_value_usd,
                max_estimated_net_edge_usd=m.estimated_net_edge_usd,
                peak_ns=m.ts_ns,
                confidence_min=m.confidence,
                data_quality_flags=set(m.data_quality_flags),
            )
            return self.active[key]
        current.last_seen_ns = m.ts_ns
        current.observations += 1
        current.confidence_min = min(current.confidence_min, m.confidence)
        current.data_quality_flags.update(m.data_quality_flags)
        if m.gross_edge_bps > current.max_spread_bps:
            current.max_spread_bps = m.gross_edge_bps
            current.peak_ns = m.ts_ns
            current.half_life_ns = None
        current.max_executable_value_usd = max(current.max_executable_value_usd, m.executable_value_usd)
        current.max_estimated_net_edge_usd = max(current.max_estimated_net_edge_usd, m.estimated_net_edge_usd)
        if current.half_life_ns is None and m.ts_ns >= current.peak_ns and m.gross_edge_bps <= current.max_spread_bps / 2:
            current.half_life_ns = m.ts_ns - current.peak_ns
        if m.capture_evidence or m.gross_edge_bps <= self.close_threshold_bps:
            evidence = m.capture_evidence or "spread_decay"
            return self._close(key, capture=bool(m.capture_evidence), evidence=evidence)
        return current

    def _close(self, key: Tuple[str, str, str, str], capture: bool, evidence: str) -> Episode:
        ep = self.active.pop(key)
        if capture:
            ep.capture_ns = ep.last_seen_ns
        ep.capture_evidence = evidence
        self.closed.append(ep)
        return ep

    def close_stale(self, now_ns: int) -> List[Episode]:
        closed = []
        for key, ep in list(self.active.items()):
            if now_ns - ep.last_seen_ns > self.gap_tolerance_ns:
                closed.append(self._close(key, capture=False, evidence="observation_gap"))
        return closed


@dataclass(frozen=True)
class InventoryLocation:
    domain: str
    venue: str
    asset: str
    quantity: float


@dataclass(frozen=True)
class PortfolioTarget:
    """Externally supplied target global weights; observatory does not invent strategy weights."""
    weights: Mapping[str, float]

    def validate(self) -> None:
        if not self.weights:
            raise ValueError("empty portfolio target")
        if any(v < 0 for v in self.weights.values()):
            raise ValueError("negative target weight")
        if abs(sum(self.weights.values()) - 1.0) > 1e-6:
            raise ValueError("target weights must sum to 1")


@dataclass(frozen=True)
class RebalanceAction:
    domain: str
    venue: str
    sell_asset: str
    buy_asset: str
    notional_usd: float
    expected_alpha_usd: float
    estimated_cost_usd: float

    @property
    def net_value_usd(self) -> float:
        return self.expected_alpha_usd - self.estimated_cost_usd


@dataclass(frozen=True)
class StrategyComparison:
    episode_ids: Tuple[str, ...]
    pairwise_gross_alpha_usd: float
    pairwise_net_alpha_usd: float
    pairwise_turnover_usd: float
    portfolio_gross_alpha_usd: float
    portfolio_net_alpha_usd: float
    portfolio_turnover_usd: float
    retained_alpha_ratio: float
    turnover_ratio: float


class PortfolioStateRebalancer:
    """Simulates local swaps against a global target using pre-positioned inventory.

    It does not bridge, move capital, or place orders. A pair of local swaps on
    separate venues can change *where* assets reside while preserving global
    asset totals, harvesting a relative-value discrepancy.
    """

    def propose_two_venue_swap(
        self,
        *,
        venue_a: str,
        venue_b: str,
        domain_a: str,
        domain_b: str,
        asset_x: str,
        asset_y: str,
        notional_usd: float,
        x_price_a: float,
        x_price_b: float,
        y_price_a: float,
        y_price_b: float,
        cost_bps_each_swap: float,
        inventory: Sequence[InventoryLocation],
    ) -> List[RebalanceAction]:
        if domain_a != domain_b:
            # Still allowed in simulation only if inventory is already present on both domains.
            pass
        have = {(i.domain, i.venue, i.asset): i.quantity for i in inventory}
        # Desired direction: buy X where X is cheaper and buy Y where Y is cheaper.
        if x_price_a < x_price_b and y_price_b < y_price_a:
            legs = [
                (domain_a, venue_a, asset_y, asset_x, y_price_a / y_price_b - 1.0),
                (domain_b, venue_b, asset_x, asset_y, x_price_b / x_price_a - 1.0),
            ]
        elif x_price_b < x_price_a and y_price_a < y_price_b:
            legs = [
                (domain_b, venue_b, asset_y, asset_x, y_price_b / y_price_a - 1.0),
                (domain_a, venue_a, asset_x, asset_y, x_price_a / x_price_b - 1.0),
            ]
        else:
            return []
        actions: List[RebalanceAction] = []
        for domain, venue, sell_asset, buy_asset, rel in legs:
            px = y_price_a if sell_asset == asset_y and venue == venue_a else y_price_b if sell_asset == asset_y else x_price_a if venue == venue_a else x_price_b
            needed_qty = notional_usd / px
            if have.get((domain, venue, sell_asset), 0.0) + 1e-12 < needed_qty:
                return []
            gross = notional_usd * max(0.0, rel)
            cost = notional_usd * cost_bps_each_swap / 1e4
            actions.append(RebalanceAction(domain, venue, sell_asset, buy_asset, notional_usd, gross, cost))
        return actions

    @staticmethod
    def compare_matched_episodes(
        episode_ids: Sequence[str],
        pairwise_gross_alpha_usd: float,
        pairwise_cost_usd: float,
        pairwise_turnover_usd: float,
        portfolio_actions: Sequence[RebalanceAction],
    ) -> StrategyComparison:
        portfolio_gross = sum(a.expected_alpha_usd for a in portfolio_actions)
        portfolio_cost = sum(a.estimated_cost_usd for a in portfolio_actions)
        portfolio_turnover = sum(a.notional_usd for a in portfolio_actions)
        pairwise_net = pairwise_gross_alpha_usd - pairwise_cost_usd
        portfolio_net = portfolio_gross - portfolio_cost
        retained = portfolio_net / pairwise_net if pairwise_net > 0 else float("nan")
        turnover_ratio = portfolio_turnover / pairwise_turnover_usd if pairwise_turnover_usd > 0 else float("nan")
        return StrategyComparison(
            episode_ids=tuple(episode_ids),
            pairwise_gross_alpha_usd=pairwise_gross_alpha_usd,
            pairwise_net_alpha_usd=pairwise_net,
            pairwise_turnover_usd=pairwise_turnover_usd,
            portfolio_gross_alpha_usd=portfolio_gross,
            portfolio_net_alpha_usd=portfolio_net,
            portfolio_turnover_usd=portfolio_turnover,
            retained_alpha_ratio=retained,
            turnover_ratio=turnover_ratio,
        )


def measurement_from_pair(
    buy: MarketObservation,
    sell: MarketObservation,
    global_price: GlobalShadowPrice,
    *,
    notional_cap_usd: float,
    extra_costs: Optional[Mapping[str, float]] = None,
) -> OpportunityMeasurement:
    buy.validate(); sell.validate()
    if buy.asset != sell.asset or buy.asset != global_price.asset:
        raise ValueError("asset mismatch")
    notional = min(notional_cap_usd, buy.ask_depth_usd, sell.bid_depth_usd)
    gross_bps = (sell.bid / buy.ask - 1.0) * 1e4
    params = dict(extra_costs or {})
    params["pool_fee_bps"] = params.get("pool_fee_bps", 0.0) + buy.explicit_fee_bps + sell.explicit_fee_bps
    costs, net = NetRealizableValue.estimate(notional, gross_bps, **params)
    flags = []
    if not buy.executable or not sell.executable:
        flags.append("non_executable_reference")
    if buy.source_kind == "aggregator" or sell.source_kind == "aggregator":
        flags.append("aggregated_source")
    confidence = min(global_price.confidence, buy.reliability, sell.reliability)
    return OpportunityMeasurement(
        ts_ns=max(buy.ts_ns, sell.ts_ns),
        lane=buy.lane if buy.lane == sell.lane else Lane.CEX_DEX,
        asset=buy.asset,
        buy_venue=buy.economic_venue,
        sell_venue=sell.economic_venue,
        domain_pair=f"{buy.domain}->{sell.domain}",
        global_price=global_price.price,
        local_buy_price=buy.ask,
        local_sell_price=sell.bid,
        gross_edge_bps=gross_bps,
        executable_value_usd=notional,
        costs=costs,
        estimated_net_edge_usd=net,
        expected_turnover_usd=notional * 2,
        confidence=confidence,
        data_quality_flags=tuple(flags),
    )


def report_row(measurement: OpportunityMeasurement, episode: Optional[Episode] = None) -> dict:
    row = asdict(measurement)
    row["lane"] = measurement.lane.value
    row["costs"]["total_usd"] = measurement.costs.total_usd
    row["episode_id"] = episode.episode_id if episode else None
    row["opportunity_duration_s"] = None if episode is None else (episode.last_seen_ns - episode.birth_ns) / 1e9
    row["realized_marked_shadow_pnl_usd"] = measurement.estimated_net_edge_usd
    return row


def dump_jsonl(path: str, rows: Iterable[Mapping[str, object]]) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
