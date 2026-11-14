from dataclasses import dataclass, asdict
from .formulas import finite
@dataclass(frozen=True)
class Costs:
    fees: float = 0
    gas: float = 0
    impact: float = 0
    spread: float = 0
    financing: float = 0
    movement: float = 0
    ordering: float = 0
    @property
    def total(self):
        vals=tuple(asdict(self).values()); finite(*vals)
        if min(vals)<0: raise ValueError('negative cost')
        return sum(vals)
# Book walks/DEX curve outputs already embed spread, impact and fees.
# In those adapters charge only incremental gas/movement/etc; never twice.
