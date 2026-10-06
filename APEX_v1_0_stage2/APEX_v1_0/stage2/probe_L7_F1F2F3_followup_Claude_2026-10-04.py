#!/usr/bin/env python3
"""Claude follow-up probe for ChatGPT's L7 F1-F3 fixes (2026-10-04). Read-only; writes nothing.

Re-runs the three original scenarios against the new API (Quote.symbol, max_quote_age_s,
asset_to_symbol, FundingPositionClose) and adds two edge checks. Not part of the unittest suite.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apex_v10.interfaces import RiskAllocation
from apex_v10.stage2_layer7 import (Account, ExecutionSimulator, FundingAccrual, FundingLedger,
                                    FundingPositionClose, Quote, Settlement, VenueSchedule)


def refused(name, fn):
    try:
        fn(); print(f'ACCEPTED {name}')
    except ValueError as e:
        print(f'REFUSED  {name}: {e}')


def sched(sym): return VenueSchedule('fixture', 'fixture', sym, 0, 10**9, 0, 0., 5., .1, .05, .01, 10., 'synthetic fixture')
alloc = RiskAllocation(100, 'fixture', {'ETH': .5}, 2., 3., .5, 'independent_fractional_kelly', 1.)
T = 10**6

# F1: ETH weight against a BTC-PERPETUAL schedule (expect REFUSED), and against ETH (expect ACCEPTED).
btc = ExecutionSimulator(sched('BTC-PERPETUAL'), max_quote_age_s=60, asset_to_symbol={'ETH': 'ETH-PERPETUAL'})
refused('F1 ETH weight on BTC-PERPETUAL schedule',
        lambda: btc.rebalance(alloc, 'ETH', Account(1000., 0.), Quote('BTC-PERPETUAL', T, T, 99., 101., 1e6, .1), ts=T))
refused('F1 quote symbol differs from schedule',
        lambda: btc.rebalance(alloc, 'ETH', Account(1000., 0.), Quote('ETH-PERPETUAL', T, T, 99., 101., 1e6, .1), ts=T))
eth = ExecutionSimulator(sched('ETH-PERPETUAL'), max_quote_age_s=60, asset_to_symbol={'ETH': 'ETH-PERPETUAL'})
refused('F1 control: matching ETH mapping (should be ACCEPTED)',
        lambda: eth.rebalance(alloc, 'ETH', Account(1000., 0.), Quote('ETH-PERPETUAL', T, T, 99., 101., 1e6, .1), ts=T))

# F2: ~11.5-day-old quote, both call paths.
old = Quote('ETH-PERPETUAL', 1, 1, 99., 101., 1e6, .1)
refused('F2 stale quote in rebalance', lambda: eth.rebalance(alloc, 'ETH', Account(1000., 0.), old, ts=T))
refused('F2 stale quote in liquidation_required', lambda: eth.liquidation_required(Account(1000., 1., 100.), old, ts=T))


# F3: close one symbol at its last accrual, then settle at 08:00 (expect ACCEPTED).
def close_then_settle():
    led = FundingLedger('BTC')
    led.apply(FundingAccrual('a1', 0, 3600, 3600, 'BTC-PERPETUAL', 'BTC', 1e-4, 'fixture'), 3600)
    led.apply(FundingPositionClose('c1', 3600, 3600, 'BTC-PERPETUAL', 'BTC', 'fixture'), 3600)
    led.apply(FundingAccrual('b1', 0, 28800, 28800, 'OTHER-BTC-INSTRUMENT', 'BTC', 1e-4, 'fixture'), 28800)
    led.apply(Settlement('s1', 28800, 28800, 'BTC', 'fixture'), 28800)
    return led


refused('F3 settle after explicit close (should be ACCEPTED)', close_then_settle)


# Edge: reopening the same symbol in a later session after a close.
def reopen_later():
    led = close_then_settle()
    led.apply(FundingAccrual('a2', 28800, 32400, 32400, 'BTC-PERPETUAL', 'BTC', 1e-4, 'fixture'), 32400)


refused('Edge: same symbol reopened in a later session', reopen_later)
