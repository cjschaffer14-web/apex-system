"""Read-only probe of ChatGPT's F5/F6 coverage and settlement fix (Claude, 2026-10-04).
Run from the package root: python stage2/probe_L7_F5F6_coverage_settlement_Claude_2026-10-04.py"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from apex_v10.stage2_layer7 import (FundingAccrual, FundingPositionClose,
    FundingPositionOpen, Settlement, FundingLedger)

D = 86400
def acc(eid, s, e, sym='BTC-PERPETUAL', pay=.01):
    return FundingAccrual(eid, s, e, e, sym, 'BTC', pay, 'probe')
def close(eid, t, sym='BTC-PERPETUAL'): return FundingPositionClose(eid, t, t, sym, 'BTC', 'probe')
def open_(eid, t, sym='BTC-PERPETUAL', cur='BTC'): return FundingPositionOpen(eid, t, t, sym, cur, 'probe')
def settle(eid, t): return Settlement(eid, t, t, 'BTC', 'probe')

def run(name, steps, expect):
    l = FundingLedger('BTC')
    try:
        for ev in steps: l.apply(ev, max(getattr(ev, 'end_ts', 0), getattr(ev, 'ts', 0)))
        got = 'accepted'
    except Exception as ex: got = f'refused ({type(ex).__name__}: {ex})'
    ok = got.startswith(expect)
    print(f"[{'AS EXPECTED' if ok else 'FINDING'}] {name}: {got}")
    return ok

base = [acc('a', 21600, 25200), close('c', 25200), settle('s', 28800)]
cases = [
 ('F4 valid close->settle->reopen->accrual', base + [open_('o', 30000), acc('b', 30000, 32400)], 'accepted'),
 ('F5a flat-period charge after reopen (28800->32400)', base + [open_('o', 30000), acc('b', 28800, 32400)], 'refused'),
 ('F5b zero-net close, reopen before settlement', [acc('a', 21600, 25200, pay=0.), close('c', 25200), open_('o', 26000)], 'refused'),
 ('F5b zero-net close, reopen after settlement', [acc('a', 21600, 25200, pay=0.), close('c', 25200), settle('s', 28800), open_('o', 30000)], 'accepted'),
 ('F6 other BTC instrument accrued after settlement, reopen at 30000',
     base + [acc('x', 28800, 30000, sym='BTC-OTHER', pay=.02), open_('o', 30000)], 'accepted'),
 ('stale settlement: 2nd close then reopen before next settlement',
     base + [open_('o', 30000), acc('b', 30000, 32400), close('c2', 32400), open_('o2', 33000)], 'refused'),
 ('2nd cycle with next-day settlement',
     base + [open_('o', 30000), acc('b', 30000, 32400), close('c2', 32400), settle('s2', 28800 + D), open_('o2', 30000 + D)], 'accepted'),
 ('settlement after reopen with no accrual covering it', base + [open_('o', 30000), settle('s2', 28800 + D)], 'refused'),
 ('settlement after reopen with accrual through settlement',
     base + [open_('o', 30000), acc('b', 30000, 28800 + D), settle('s2', 28800 + D)], 'accepted'),
 ('close, settle and reopen all at 08:00', [acc('a', 21600, 28800), close('c', 28800), settle('s', 28800), open_('o', 28800), acc('b', 28800, 32400)], 'accepted'),
 ('reopen with wrong currency', base + [open_('o', 30000, cur='ETH')], 'refused'),
 ('reopen of an active symbol', [acc('a', 21600, 25200), open_('o', 25200)], 'refused'),
]
n = sum(run(*c) for c in cases)
print(f"\n{n}/{len(cases)} cases as expected")
