"""Read-only probe of ChatGPT's F4 reopen-lifecycle fix (Claude, 2026-10-04).
Run from the package root: python stage2/probe_L7_F4_reopen_Claude_2026-10-04.py"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from apex_v10.stage2_layer7 import (FundingAccrual, FundingPositionClose,
    FundingPositionOpen, Settlement, FundingLedger)

def acc(eid, s, e, sym='BTC-PERPETUAL', pay=.01):
    return FundingAccrual(eid, s, e, e, sym, 'BTC', pay, 'probe')

def run(name, fn, expect):
    try: fn(); got = 'accepted'
    except Exception as ex: got = f'refused ({type(ex).__name__}: {ex})'
    ok = got.startswith(expect)
    print(f"[{'AS EXPECTED' if ok else 'FINDING'}] {name}: {got}")

def valid_cycle():
    l = FundingLedger('BTC')
    l.apply(acc('a', 21600, 25200), 25200)
    l.apply(FundingPositionClose('c', 25200, 25200, 'BTC-PERPETUAL', 'BTC', 'probe'), 25200)
    l.apply(Settlement('s', 28800, 28800, 'BTC', 'probe'), 28800)
    l.apply(FundingPositionOpen('o', 30000, 30000, 'BTC-PERPETUAL', 'BTC', 'probe'), 30000)
    l.apply(acc('b', 30000, 32400), 32400)
    return l

def reopen_active():
    l = FundingLedger('BTC'); l.apply(acc('a', 21600, 25200), 25200)
    l.apply(FundingPositionOpen('o', 25200, 25200, 'BTC-PERPETUAL', 'BTC', 'probe'), 25200)

def reopen_before_settlement():
    l = FundingLedger('BTC'); l.apply(acc('a', 21600, 25200), 25200)
    l.apply(FundingPositionClose('c', 25200, 25200, 'BTC-PERPETUAL', 'BTC', 'probe'), 25200)
    l.apply(FundingPositionOpen('o', 26000, 26000, 'BTC-PERPETUAL', 'BTC', 'probe'), 26000)

def reopen_wrong_currency():
    l = FundingLedger('BTC'); l.apply(acc('a', 21600, 25200), 25200)
    l.apply(FundingPositionClose('c', 25200, 25200, 'BTC-PERPETUAL', 'BTC', 'probe'), 25200)
    l.apply(Settlement('s', 28800, 28800, 'BTC', 'probe'), 28800)
    l.apply(FundingPositionOpen('o', 30000, 30000, 'BTC-PERPETUAL', 'ETH', 'probe'), 30000)

# F5 candidate: first accrual after reopen may start BEFORE the open timestamp.
def accrual_starts_before_open():
    l = FundingLedger('BTC'); l.apply(acc('a', 21600, 25200), 25200)
    l.apply(FundingPositionClose('c', 25200, 25200, 'BTC-PERPETUAL', 'BTC', 'probe'), 25200)
    l.apply(Settlement('s', 28800, 28800, 'BTC', 'probe'), 28800)
    l.apply(FundingPositionOpen('o', 30000, 30000, 'BTC-PERPETUAL', 'BTC', 'probe'), 30000)
    l.apply(acc('b', 28800, 32400), 32400)   # covers 28800-30000, while flat

# F5 candidate: zero-payment session lets reopen pass the "settled" gate before settlement.
def zero_pending_reopen_before_settlement():
    l = FundingLedger('BTC'); l.apply(acc('a', 21600, 25200, pay=0.0), 25200)
    l.apply(FundingPositionClose('c', 25200, 25200, 'BTC-PERPETUAL', 'BTC', 'probe'), 25200)
    l.apply(FundingPositionOpen('o', 26000, 26000, 'BTC-PERPETUAL', 'BTC', 'probe'), 26000)

# F6 candidate: with a second open symbol, pending is ledger-wide, so reopen is
# only possible at the exact settlement timestamp.
def reopen_with_other_symbol_active():
    l = FundingLedger('BTC')
    l.apply(acc('a', 21600, 25200), 25200); l.apply(acc('x1', 21600, 25200, 'BTC-FUT'), 25200)
    l.apply(FundingPositionClose('c', 25200, 25200, 'BTC-PERPETUAL', 'BTC', 'probe'), 25200)
    l.apply(acc('x2', 25200, 28800, 'BTC-FUT'), 28800)
    l.apply(Settlement('s', 28800, 28800, 'BTC', 'probe'), 28800)
    l.apply(acc('x3', 28800, 30000, 'BTC-FUT'), 30000)
    l.apply(FundingPositionOpen('o', 30000, 30000, 'BTC-PERPETUAL', 'BTC', 'probe'), 30000)

l = valid_cycle(); print('valid cycle ends:', l.ends, 'closed:', l.closed, 'pending:', round(l.pending, 12))
run('valid close->settle->reopen->accrual', valid_cycle, 'accepted')
run('reopen active symbol', reopen_active, 'refused')
run('reopen before settlement', reopen_before_settlement, 'refused')
run('reopen wrong currency', reopen_wrong_currency, 'refused')
run('F5a accrual starting before reopen ts', accrual_starts_before_open, 'refused')
run('F5b zero-pending reopen before settlement', zero_pending_reopen_before_settlement, 'refused')
run('F6 reopen while another symbol accrues', reopen_with_other_symbol_active, 'accepted')
