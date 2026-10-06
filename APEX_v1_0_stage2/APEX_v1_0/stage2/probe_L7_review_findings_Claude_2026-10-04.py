#!/usr/bin/env python3
"""Claude review probe for ChatGPT Layer 7 (2026-10-04). Read-only; writes nothing.

Each check prints OPEN while the gap exists and CLOSED once the simulator fails
closed. Not part of the unittest suite, so the 138-test regression stays green
until ChatGPT lands fixes and pins them with tests.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apex_v10.interfaces import RiskAllocation
from apex_v10.stage2_layer7 import (Account, ExecutionSimulator, FundingAccrual,
                                    FundingLedger, Quote, Settlement, VenueSchedule)


def check(name, fn):
    try:
        fn()
        print(f'OPEN    {name}')
    except ValueError as e:
        print(f'CLOSED  {name}: {e}')


sched = VenueSchedule('fixture', 'fixture', 'BTC-PERPETUAL', 0, 10**9, 0, 0., 5., .1, .05, .01, 10., 'synthetic fixture')
alloc = RiskAllocation(100, 'fixture', {'ETH': .5}, 2., 3., .5, 'independent_fractional_kelly', 1.)
sim = ExecutionSimulator(sched)

# F1: an ETH weight executes against a BTC-PERPETUAL schedule (fees/margin of the wrong instrument).
check('F1 asset/schedule symbol mismatch accepted',
      lambda: sim.rebalance(alloc, 'ETH', Account(1000., 0.), Quote(10**6, 10**6, 99., 101., 1e6, .1), ts=10**6))

# F2: a quote observed ~11.5 days before the fill time is accepted (no maximum quote age).
check('F2 stale quote accepted',
      lambda: ExecutionSimulator(VenueSchedule('fixture', 'fixture', 'ETH', 0, 10**9, 0, 0., 5., .1, .05, .01, 10., 'synthetic fixture'))
      .rebalance(alloc, 'ETH', Account(1000., 0.), Quote(1, 1, 99., 101., 1e6, .1), ts=10**6))


# F3: once a symbol stops accruing (position closed before 08:00), every later settlement is refused.
def ledger_after_close():
    led = FundingLedger('BTC')
    led.apply(FundingAccrual('a1', 0, 3600, 3600, 'BTC-PERPETUAL', 'BTC', 1e-4, 'fixture'), 3600)
    led.apply(FundingAccrual('b1', 0, 28800, 28800, 'OTHER-BTC-INSTRUMENT', 'BTC', 1e-4, 'fixture'), 28800)
    led.apply(Settlement('s1', 28800, 28800, 'BTC', 'fixture'), 28800)


check('F3 settlement possible after a symbol closes mid-session', ledger_after_close)
print('Note: F3 prints CLOSED today (settlement refused); the desired end state is that it settles once the close is recorded.')
