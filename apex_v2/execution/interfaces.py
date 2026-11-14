from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
@dataclass(frozen=True)
class OrderRequest:
    economic_venue_id: str
    pair: str
    side: str
    quantity: Decimal
    mode: str = 'paper'
class ExecutionEngine(ABC):
    @abstractmethod
    def execute(self, request, snapshot, now_ns): pass
