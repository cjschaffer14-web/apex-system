from dataclasses import dataclass, field
from typing import Mapping
from .formulas import finite, net_expected_value
@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    episode_id: str
    gross_usd: float # F1, executable terminal minus initial minus success costs
    capture_probability: float
    failure_loss_usd: float
    holding_cost_usd: float
    capital_usd: float
    seconds_at_risk: float
    margin_usd: float = 0
    risk_proxy: float = 0
    inventory_required: Mapping[str,float] = field(default_factory=dict)
    venue_usage: Mapping[str,float] = field(default_factory=dict)
    liquidity_ok: bool = True
    settlement_ok: bool = True
    quality_ok: bool = True
    movement_cost_usd: float = 0 # diagnostic; already in F1 cost
    turnover_usd: float = 0
    strategy: str = 'opportunity_chasing'
    feature_status: str = 'production'
    @property
    def nev(self): return net_expected_value(self.capture_probability,self.gross_usd,self.failure_loss_usd,self.holding_cost_usd)
    def validate(self):
        finite(self.capital_usd,self.seconds_at_risk,self.margin_usd,self.risk_proxy,self.movement_cost_usd,self.turnover_usd,*self.inventory_required.values(),*self.venue_usage.values())
        if self.capital_usd<=0 or self.seconds_at_risk<=0 or min(self.margin_usd,self.risk_proxy,self.movement_cost_usd,self.turnover_usd,*self.inventory_required.values(),*self.venue_usage.values())<0: raise ValueError('invalid candidate resources')
        _=self.nev
