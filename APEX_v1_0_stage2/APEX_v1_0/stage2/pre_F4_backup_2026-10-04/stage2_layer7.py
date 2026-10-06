"""Stage 2 simulation primitives; no live trading and no strategy search.

Funding is currency-native. Historical interest_1h lacks an intrahour price/
position path: its adapter is explicitly approximate and fails closed by default.
Exact accruals and recorded settlements are separate ledger transactions.
Execution is a quote-currency, single-instrument linear/spot research model.
Inverse execution and exchange portfolio margin are deliberately refused.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Literal
from apex_v10.interfaces import RiskAllocation, ExecutionEvent, ExecutionKind, FillModel
from apex_v10.risk.allocator import ReturnsWindow


def finite(x, name, positive=False):
    if isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x) or (positive and x <= 0):
        raise ValueError(f'{name}: invalid finite number')


def timestamp(x):
    if isinstance(x, bool) or not isinstance(x, int) or x < 0:
        raise ValueError('timestamp must be nonnegative integer seconds')


def timestamped_returns(assets, rows, period_seconds, decision_ts):
    """Adapt explicitly timestamped return rows; never infer publication from candle time.

rows must contain a real known_at_ts and values in asset order. The caller is
responsible for the recorded timestamp's provenance. No padding or backfill.
"""
    timestamp(decision_ts)
    rows=tuple(rows)
    window=ReturnsWindow(tuple(assets),tuple(r['known_at_ts'] for r in rows),
                         tuple(tuple(r['values']) for r in rows),period_seconds)
    if any(t>decision_ts for t in window.known_at_ts): raise ValueError('future return row')
    return window


@dataclass(frozen=True)
class FundingAccrual:
    event_id: str
    start_ts: int
    end_ts: int
    known_at_ts: int
    symbol: str
    currency: str
    payment: float                 # positive paid by account; negative received
    provenance_id: str
    approximate: bool = False

    def __post_init__(self):
        for t in (self.start_ts, self.end_ts, self.known_at_ts): timestamp(t)
        if self.end_ts <= self.start_ts or self.known_at_ts < self.end_ts:
            raise ValueError('invalid accrual interval/availability')
        finite(self.payment, 'payment')
        if not all((self.event_id, self.symbol, self.currency, self.provenance_id)):
            raise ValueError('funding identity, currency and provenance required')


@dataclass(frozen=True)
class Settlement:
    event_id: str
    ts: int
    known_at_ts: int
    currency: str
    provenance_id: str

    def __post_init__(self):
        timestamp(self.ts); timestamp(self.known_at_ts)
        if self.known_at_ts < self.ts or self.ts % 86400 != 8 * 3600:
            raise ValueError('Deribit recorded daily settlement must be 08:00 UTC')
        if not all((self.event_id, self.currency, self.provenance_id)):
            raise ValueError('recorded settlement identity/provenance required')

@dataclass(frozen=True)
class FundingPositionClose:
    event_id: str
    ts: int
    known_at_ts: int
    symbol: str
    currency: str
    provenance_id: str

    def __post_init__(self):
        timestamp(self.ts); timestamp(self.known_at_ts)
        if self.known_at_ts < self.ts:
            raise ValueError('close availability before event')
        if not all((self.event_id, self.symbol, self.currency, self.provenance_id)):
            raise ValueError('close identity, currency and provenance required')


class FundingLedger:
    """Realized-session PNL accrual followed by a cash transfer at recorded settlement.

An interval ending at settlement is accrued first. Settlement transfers pending
PNL to cash without altering equity a second time. One ledger per currency.
"""
    def __init__(self, currency, cash=0., allow_approximate=False):
        finite(cash, 'cash')
        self.currency, self.cash, self.pending = currency, float(cash), 0.
        self.allow_approximate, self.seen, self.events = allow_approximate, set(), []
        self.last_key = (-1, -1)
        self.ends = {}
        self.closed = set()

    @property
    def equity(self): return self.cash + self.pending

    def apply(self, event, as_of_ts):
        timestamp(as_of_ts)
        if not isinstance(event, (FundingAccrual, FundingPositionClose, Settlement)): raise TypeError('typed funding event required')
        t = event.end_ts if isinstance(event, FundingAccrual) else event.ts
        order = 0 if isinstance(event, FundingAccrual) else (1 if isinstance(event, FundingPositionClose) else 2)
        key = (t, order)
        if event.known_at_ts > as_of_ts or t > as_of_ts:
            raise ValueError('future funding event')
        if event.currency != self.currency or event.event_id in self.seen or key < self.last_key:
            raise ValueError('currency mismatch, duplicate, or out-of-order event')
        if isinstance(event, FundingAccrual):
            if event.approximate and not self.allow_approximate: raise ValueError('approximate funding refused')
            if event.symbol in self.closed: raise ValueError('accrual after explicit position close')
            prior = self.ends.get(event.symbol)
            if prior is not None and prior != event.start_ts: raise ValueError('funding gap or overlap')
            # A sample must not straddle a settlement: otherwise settlement PNL cannot be assigned.
            boundary = (event.start_ts // 86400) * 86400 + 28800
            if boundary <= event.start_ts: boundary += 86400
            if boundary < event.end_ts: raise ValueError('accrual crosses daily settlement')
            self.pending -= event.payment
            self.ends[event.symbol] = event.end_ts
            self.events.append({'kind':'accrual', 'event_id':event.event_id, 'ts':t,
                                'currency':self.currency,'payment':event.payment,
                                'approximate':event.approximate,'provenance_id':event.provenance_id})
        elif isinstance(event, FundingPositionClose):
            prior = self.ends.get(event.symbol)
            if prior is None or prior != t: raise ValueError('close requires accrued coverage through close timestamp')
            del self.ends[event.symbol]
            self.closed.add(event.symbol)
            self.events.append({'kind':'position_close','event_id':event.event_id,'ts':t,
                                'currency':self.currency,'symbol':event.symbol,
                                'provenance_id':event.provenance_id})
        else:
            # Refuse retroactive accrual before a settlement already posted.
            if any(end != t for end in self.ends.values()):
                raise ValueError('settlement requires complete accrued coverage through its timestamp')
            self.cash += self.pending
            self.events.append({'kind':'settlement','event_id':event.event_id,'ts':t,
                                'currency':self.currency,'cash_delta':self.pending,
                                'provenance_id':event.provenance_id})
            self.pending = 0.
        self.seen.add(event.event_id); self.last_key = key


def deribit_hourly_sample(*, end_ts, known_at_ts, symbol, rate_1h, index_price,
                          signed_usd_position, provenance_id, allow_approximate=False):
    """Approximate inverse BTC/ETH accrual for an explicitly constant USD position.

interest_1h is already an hourly rate: do NOT divide it by eight. USD position
is converted to coin using the sampled index; intrahour FX/path is unavailable.
This adapter is replay-only and cannot expose the end-of-hour rate to decisions
earlier in the hour. Changes within the hour require finer funding/price data.
"""
    if not allow_approximate: raise ValueError('hourly sample cannot prove exact inverse funding')
    if symbol not in ('BTC-PERPETUAL','ETH-PERPETUAL'): raise ValueError('unsupported inverse instrument')
    finite(rate_1h,'rate'); finite(index_price,'index',True); finite(signed_usd_position,'position')
    return FundingAccrual(f'{symbol}:{end_ts}', end_ts-3600,end_ts,known_at_ts,symbol,
                          symbol.split('-')[0],signed_usd_position/index_price*rate_1h,
                          provenance_id,True)


@dataclass(frozen=True)
class VenueSchedule:
    schedule_id: str
    venue: str
    symbol: str
    valid_from: int
    valid_until: int             # exclusive; historical schedules never inferred from today's web page
    known_at_ts: int
    maker_bps: float
    taker_bps: float
    initial_margin: float
    maintenance_margin: float
    liquidation_buffer: float
    liquidation_bps: float
    source: str
    research_only: bool = True

    def __post_init__(self):
        for t in (self.valid_from,self.valid_until,self.known_at_ts): timestamp(t)
        if self.valid_until <= self.valid_from: raise ValueError('invalid schedule interval')
        for n in ('maker_bps','taker_bps','initial_margin','maintenance_margin','liquidation_buffer','liquidation_bps'):
            finite(getattr(self,n),n)
        if not 0 <= self.maintenance_margin <= self.initial_margin <= 1:
            raise ValueError('invalid margin rates')
        if min(self.taker_bps,self.liquidation_buffer,self.liquidation_bps) < 0:
            raise ValueError('invalid fee/buffer')
        if not all((self.schedule_id,self.venue,self.symbol,self.source)): raise ValueError('schedule provenance required')

    def check(self, ts):
        if self.known_at_ts > ts or not self.valid_from <= ts < self.valid_until:
            raise ValueError('schedule unavailable or outside its effective interval')


@dataclass(frozen=True)
class Quote:
    symbol: str
    ts: int
    known_at_ts: int
    bid: float
    ask: float
    depth_quote: float
    max_participation: float
    impact_bps: float = 0.
    mark: float | None = None

    def __post_init__(self):
        if not self.symbol: raise ValueError('quote symbol required')
        timestamp(self.ts); timestamp(self.known_at_ts)
        if self.known_at_ts < self.ts: raise ValueError('quote availability before observation')
        for n in ('bid','ask','depth_quote'): finite(getattr(self,n),n,True)
        finite(self.max_participation,'participation',True); finite(self.impact_bps,'impact')
        if self.bid > self.ask or self.max_participation > 1 or self.impact_bps < 0:
            raise ValueError('invalid quote/liquidity')
        if self.mark is not None: finite(self.mark,'mark',True)


@dataclass(frozen=True)
class Account:
    cash: float                 # quote collateral; spot inventory also valued in equity
    position: float            # signed base units
    entry_price: float | None = None

    def __post_init__(self):
        finite(self.cash,'cash'); finite(self.position,'position')
        if self.entry_price is not None: finite(self.entry_price,'entry',True)


@dataclass(frozen=True)
class ExecutionResult:
    event: ExecutionEvent
    account: Account
    requested_quantity: float
    unfilled_quantity: float
    status: str
    approximate: bool
    initial_required: float
    maintenance_required: float


class ExecutionSimulator:
    """Unified allocation -> target -> delta -> fill -> accounting contract.

Liquidity curve: square-root impact relative to supplied quote depth; capped
participation permits partial fills. This is an assumption, not reconstructed
historical order-book execution. Passive fills need explicit fill evidence.
Linear isolated margin uses caller-supplied schedule, not exchange PM rules.
"""
    def __init__(self, schedule: VenueSchedule, product: Literal['spot','linear']='linear', *, max_quote_age_s:int, asset_to_symbol:dict[str,str]):
        if product not in ('spot','linear'): raise ValueError('inverse/portfolio-margin execution not implemented')
        if isinstance(max_quote_age_s, bool) or not isinstance(max_quote_age_s, int) or max_quote_age_s < 0:
            raise ValueError('max_quote_age_s must be a nonnegative integer')
        if not asset_to_symbol or any(not a or not s for a,s in asset_to_symbol.items()):
            raise ValueError('explicit asset-to-symbol mapping required')
        self.schedule,self.product,self.max_quote_age_s=schedule,product,max_quote_age_s
        self.asset_to_symbol=dict(asset_to_symbol)

    def _check_quote(self, quote, ts):
        timestamp(ts)
        if quote.symbol != self.schedule.symbol: raise ValueError('quote/schedule symbol mismatch')
        if quote.known_at_ts > ts or quote.ts > ts: raise ValueError('future quote')
        if ts - quote.ts > self.max_quote_age_s: raise ValueError('stale quote')

    def equity(self,a,price):
        if self.product=='spot': return a.cash+a.position*price
        if a.position and a.entry_price is None: raise ValueError('nonflat derivative needs entry price')
        return a.cash+a.position*(price-(a.entry_price or price))

    def rebalance(self,allocation: RiskAllocation,asset:str,account:Account,quote:Quote,*,
                  ts:int,passive_limit=None,confirmed_maker_quantity=None,reduce_only=False):
        if not isinstance(allocation,RiskAllocation): raise TypeError('RiskAllocation required')
        timestamp(ts); self.schedule.check(ts); self._check_quote(quote,ts)
        if allocation.decision_ts > ts: raise ValueError('future allocation')
        if asset not in allocation.weights: raise ValueError('asset absent from allocation')
        if self.asset_to_symbol.get(asset) != self.schedule.symbol:
            raise ValueError('asset/schedule symbol mismatch')
        if allocation.gross > allocation.gross_cap or any(abs(w)>allocation.per_asset_cap for w in allocation.weights.values()):
            raise ValueError('allocation exceeds exact caps')
        mid=(quote.bid+quote.ask)/2
        equity=self.equity(account,quote.mark or mid)
        if equity <= 0: raise ValueError('nonpositive equity')
        weight=allocation.weights[asset]
        if self.product=='spot' and weight < 0: raise ValueError('spot short refused')
        requested=weight*equity/mid-account.position
        qty=requested
        if reduce_only and (account.position==0 or qty*account.position>=0): qty=0.
        if reduce_only and abs(qty)>abs(account.position): qty=-account.position
        qty=math.copysign(min(abs(qty),quote.depth_quote*quote.max_participation/mid),qty)
        maker=False
        if passive_limit is not None:
            finite(passive_limit,'limit',True)
            if (qty>0 and passive_limit>=quote.ask) or (qty<0 and passive_limit<=quote.bid):
                raise ValueError('post-only crossing rejected; a limit order is not necessarily maker')
            if confirmed_maker_quantity is None: qty=0.
            else:
                finite(confirmed_maker_quantity,'confirmed quantity')
                if confirmed_maker_quantity*qty<0: raise ValueError('maker evidence wrong side')
                qty=math.copysign(min(abs(qty),abs(confirmed_maker_quantity)),qty)
            maker=True
        price=passive_limit if maker else ((quote.ask if qty>=0 else quote.bid)*
                 (1+math.copysign(quote.impact_bps/10000*math.sqrt(abs(qty)*mid/quote.depth_quote),qty)))
        finite(price,'execution price',True)
        fee=abs(qty)*price*(self.schedule.maker_bps if maker else self.schedule.taker_bps)/10000
        newpos=account.position+qty
        if self.product=='spot':
            proposed=Account(account.cash-qty*price-fee,newpos)
        else:
            closed=min(abs(qty),abs(account.position)) if qty*account.position<0 else 0.
            pnl=closed*math.copysign(1,account.position)*(price-(account.entry_price or price))
            if newpos==0: entry=None
            elif account.position==0 or account.position*newpos<0: entry=price
            elif qty*account.position>0:
                entry=(abs(account.position)*account.entry_price+abs(qty)*price)/abs(newpos)
            else: entry=account.entry_price
            proposed=Account(account.cash+pnl-fee,newpos,entry)
        initial=abs(newpos)*(quote.mark or mid)*self.schedule.initial_margin if self.product=='linear' else 0.
        maintenance=abs(newpos)*(quote.mark or mid)*(self.schedule.maintenance_margin+self.schedule.liquidation_buffer) if self.product=='linear' else 0.
        newequity=self.equity(proposed,quote.mark or mid)
        reducing=abs(newpos)<=abs(account.position) and newpos*account.position>=0
        reject=(self.product=='spot' and (proposed.cash < 0 or newpos < 0)) or (self.product=='linear' and not reducing and newequity < max(initial,maintenance))
        if reject or qty==0:
            event=ExecutionEvent(ts,self.schedule.venue,self.schedule.symbol,ExecutionKind.UNFILLED,
                                 requested,float(price),self.schedule.schedule_id,FillModel.CONSERVATIVE_BAR)
            return ExecutionResult(event,account,requested,requested,'margin_rejected' if reject else 'unfilled',True,initial,maintenance)
        event=ExecutionEvent(ts,self.schedule.venue,self.schedule.symbol,ExecutionKind.FILL,qty,float(price),
                             self.schedule.schedule_id,FillModel.CONSERVATIVE_BAR,max(fee,0.),max(-fee,0.))
        return ExecutionResult(event,proposed,requested,requested-qty,'filled' if qty==requested else 'partial',True,initial,maintenance)

    def liquidation_required(self,account,quote,ts):
        self.schedule.check(ts); self._check_quote(quote,ts)
        if self.product!='linear': return False
        if quote.mark is None: raise ValueError('mark data required for liquidation assessment')
        threshold=abs(account.position)*quote.mark*(self.schedule.maintenance_margin+self.schedule.liquidation_buffer)
        return self.equity(account,quote.mark)<=threshold

    def liquidate(self,account,quote,ts):
        if not self.liquidation_required(account,quote,ts): raise ValueError('liquidation buffer not breached')
        if not account.position: raise ValueError('flat account')
        qty=-account.position
        price=(quote.bid if qty<0 else quote.ask)*(1+math.copysign(quote.impact_bps/10000*math.sqrt(abs(qty)*(quote.bid+quote.ask)/2/quote.depth_quote),qty))
        finite(price,'liquidation price',True)
        fee=abs(qty)*price*self.schedule.liquidation_bps/10000
        pnl=account.position*(price-account.entry_price)
        event=ExecutionEvent(ts,self.schedule.venue,self.schedule.symbol,ExecutionKind.LIQUIDATION,qty,price,
                             self.schedule.schedule_id,FillModel.CONSERVATIVE_BAR,fee_paid=fee,
                             mark_price_available=True,liquidation_approximate=True)
        return ExecutionResult(event,Account(account.cash+pnl-fee,0.),qty,0.,'liquidated',True,0.,0.)
