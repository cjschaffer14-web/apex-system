"""Venue-neutral market-order preparation and routing against supplied spot books.

No network, credentials, private adapter, reservation or order submission. Quantities
are explicit BASE units on both sides. Balances are per venue, never pooled across
exchanges; a returned route remains a shadow proposal, not a broker fill.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from ..connectivity.markets import pair_name


@dataclass(frozen=True)
class SpotIntent:
    strategy_id: str
    pair: str
    side: str
    base_quantity: Decimal
    max_quote_notional: Decimal
    max_slippage_bps: Decimal


def number(value, name, allow_zero=False):
    if not isinstance(value, Decimal) or not value.is_finite() or (value < 0 if allow_zero else value <= 0):
        raise ValueError('invalid ' + name)
    return value


class SpotRouter:
    def __init__(self, max_age_s=2):
        self.max_age_s = max_age_s

    def route(self, intent, snapshots, markets, balances, now_ns):
        if not intent.strategy_id or intent.side not in ('buy', 'sell'):
            raise ValueError('strategy and buy/sell side required')
        pair = pair_name(intent.pair)
        qty = number(intent.base_quantity, 'base quantity')
        cap = number(intent.max_quote_notional, 'notional cap')
        slip_cap = number(intent.max_slippage_bps, 'slippage cap', True)
        base, quote = pair.split('/')
        candidates, rejected, seen = [], [], set()
        for snapshot in snapshots:
            venue = snapshot.economic_venue_id
            if (venue, snapshot.book.pair) in seen:
                raise ValueError('duplicate venue/pair book')
            seen.add((venue, snapshot.book.pair))
            if snapshot.book.pair != pair:
                continue
            try:
                snapshot.fresh(now_ns, self.max_age_s)
                market = markets[(venue, pair)]
                if market.venue != venue or market.pair != pair:
                    raise ValueError('market identity mismatch')
                if market.observed_ns > now_ns or now_ns - market.observed_ns > 86_400_000_000_000:
                    raise ValueError('market rules stale/future')
                if not market.market_orders:
                    raise ValueError('market orders unavailable')
                if market.base_increment is None or market.min_quote is None:
                    raise ValueError('unknown order constraints')
                step = number(market.base_increment, 'base increment')
                rounded = (qty / step).to_integral_value(rounding=ROUND_DOWN) * step
                # Do not compare different sizes as if they were equivalent routes.
                if rounded != qty:
                    raise ValueError('quantity violates venue increment')
                if market.min_base is not None and qty < market.min_base:
                    raise ValueError('below minimum base quantity')
                if snapshot.fee_bps is None:
                    raise ValueError('unknown taker fee')
                fee = Decimal(str(snapshot.fee_bps)) / 10000
                rows = snapshot.book.asks if intent.side == 'buy' else snapshot.book.bids
                if sum(x.size for x in rows) < qty:
                    raise ValueError('insufficient depth')
                remaining, gross = qty, Decimal(0)
                for level in rows:
                    take = min(remaining, level.size)
                    gross += take * level.price
                    remaining -= take
                    if not remaining:
                        break
                if gross < market.min_quote or gross > cap:
                    raise ValueError('quote notional outside limits')
                vwap = gross / qty
                slippage = ((vwap / rows[0].price - 1) if intent.side == 'buy'
                            else (1 - vwap / rows[0].price)) * 10000
                if slippage > slip_cap:
                    raise ValueError('slippage cap exceeded')
                # Quote-equivalent fee for comparison; reserve an additional fee
                # buffer in the spent currency conservatively, regardless of the
                # eventual fee debit currency. No private fee accounting is claimed.
                fee_value = gross * fee
                spend_asset = quote if intent.side == 'buy' else base
                required = (gross if intent.side == 'buy' else qty) * (1 + fee)
                available = number(balances[(venue, spend_asset)], 'available balance', True)
                if available < required:
                    raise ValueError('insufficient venue-local balance')
                if intent.side == 'buy' and required > cap:
                    raise ValueError('fee-inclusive quote cap exceeded')
                net_quote = gross + fee_value if intent.side == 'buy' else gross - fee_value
                candidates.append({'venue': venue, 'native_symbol': market.native_symbol,
                    'pair': pair, 'side': intent.side, 'base_quantity': str(qty),
                    'gross_quote': str(gross), 'fee_quote_equivalent': str(fee_value),
                    'fee_basis': 'declared taker assumption; quote-equivalent comparison',
                    'effective_quote': str(net_quote), 'vwap': str(vwap),
                    'slippage_bps': str(slippage), 'reserve_asset': spend_asset,
                    'reserve_amount': str(required), 'synthetic': snapshot.synthetic,
                    'strategy_id': intent.strategy_id})
            except (ValueError, KeyError) as error:
                rejected.append({'venue': venue, 'reason': str(error) if isinstance(error, ValueError) else 'missing market or balance'})
        candidates.sort(key=lambda x: (Decimal(x['effective_quote']) * (1 if intent.side == 'buy' else -1), x['venue']))
        return {'status': 'shadow_route_ready' if candidates else 'no_eligible_route',
            'mode': 'shadow', 'orders_authorized': False, 'submitted': False,
            'selected': candidates[0] if candidates else None, 'alternatives': candidates,
            'rejected': rejected, 'balance_reservations_applied': False,
            'note': 'Single-order proposal; concurrent orders require shared reservations.'}
