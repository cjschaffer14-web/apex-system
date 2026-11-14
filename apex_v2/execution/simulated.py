"""In-memory book-walk simulation, no transport/connector/order API dependency."""
from decimal import Decimal
from ..core import walk_buy, walk_sell
from .interfaces import ExecutionEngine

class SimulatedExecutionEngine(ExecutionEngine):
    def execute(self, request, snapshot, now_ns):
        if request.mode not in ('paper','shadow'): raise ValueError('live order submission forbidden')
        snapshot.fresh(now_ns)
        if request.economic_venue_id != snapshot.economic_venue_id or request.pair != snapshot.book.pair:
            raise ValueError('order/snapshot mismatch')
        if not isinstance(request.quantity,Decimal) or not request.quantity.is_finite() or request.quantity <= 0:
            raise ValueError('invalid quantity')
        if snapshot.fee_bps is None: raise ValueError('simulation requires declared fee')
        if request.side == 'buy': fill = walk_buy(snapshot.book.asks, request.quantity)
        elif request.side == 'sell': fill = walk_sell(snapshot.book.bids, request.quantity)
        else: raise ValueError('unsupported side')
        return {'mode':request.mode,'orders_authorized':False,'status':'simulated_fill' if fill else 'insufficient_depth',
                'amount_out': str(fill[0]*(1-Decimal(str(snapshot.fee_bps))/10000)) if fill else None,
                'capture_evidence':False,'timestamp_ns':now_ns}
