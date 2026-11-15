from dataclasses import dataclass, field
from typing import Mapping
@dataclass(frozen=True)
class AgentState:
    capital_usd: float
    margin_usd: float
    inventory: Mapping[str,float] = field(default_factory=dict) # venue:asset -> native units
    venue_limits: Mapping[str,float] = field(default_factory=dict)
    available_venues: frozenset = frozenset()
    latency_seconds: float = 0.1
    max_latency_seconds: float = 2
    operational: bool = True
    legal_allowed: bool = True
    mode: str = 'shadow'
    def __post_init__(self):
        from ..economics.formulas import finite
        finite(self.capital_usd,self.margin_usd,self.latency_seconds,self.max_latency_seconds,*self.inventory.values(),*self.venue_limits.values())
        if min(self.capital_usd,self.margin_usd,self.latency_seconds,self.max_latency_seconds,*self.inventory.values(),*self.venue_limits.values())<0: raise ValueError('negative agent resources')
        if self.mode not in ('shadow','live'): raise ValueError('mode must be shadow or live')
