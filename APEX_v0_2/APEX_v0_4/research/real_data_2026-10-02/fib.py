"""Fibonacci retracement test against random-level and round-level controls, on real daily/hourly closes."""
import sys, json, math, random
sys.path.insert(0, '/home/claude/build/APEX_v0_4')
from apex.ext import crypto_pack as cp
import json as _j
def load(prod, gran):
    rows = _j.load(open(f"{prod}_{gran}.json")); closes, last = [], None
    for ts, o, h, l, c, v in rows:
        if last is not None and ts - last > gran:
            closes += [closes[-1]] * ((ts - last) // gran - 1)
        closes.append(c); last = ts
    return closes

def swings(closes, lookback=60):
    """For each bar t: the swing high/low of the bars before t and whether the low came first. Computed once."""
    from collections import deque
    n = len(closes); out = [None] * n
    for t in range(lookback, n):
        w = closes[t - lookback:t]
        i_hi = max(range(lookback), key=w.__getitem__); i_lo = min(range(lookback), key=w.__getitem__)
        out[t] = (w[i_hi], w[i_lo], i_lo < i_hi)
    return out

def retrace_signal(closes, ratios, sw, lookback=60, band=0.01, max_hold=None, stop_ratio=0.786):
    """Long after a pullback into a retracement level of the latest up-swing, once price turns up; exit at the swing
    high, below the stop level, or after max_hold bars. Uses only data up to bar t."""
    n = len(closes); out = [0.0] * n; pos = 0.0; held = 0; hi = lo = None
    max_hold = max_hold or lookback
    for t in range(lookback, n):
        H, L, up = sw[t]
        if pos:
            held += 1
            if closes[t] >= hi or closes[t] <= hi - stop_ratio * (hi - lo) or held >= max_hold:
                pos, held = 0.0, 0
        elif up and H > L:                              # an up-swing: low first, then high
            for r in ratios:
                level = H - r * (H - L)
                if abs(closes[t - 1] - level) <= band * level and closes[t] > closes[t - 1]:
                    pos, held, hi, lo = 1.0, 0, H, L
                    break
        out[t] = pos
    return out

def run(closes, ratios, bpy, fee, sw):
    cfg = cp.SimConfig(bars_per_year=bpy, fee_bps=fee, target_vol=None, brake_floor=1.0)
    cfg.contract = cp.CryptoTradingContract(drawdown_halt=0.99)          # isolate the signal: no halt, no brake
    sig = retrace_signal(closes, ratios, sw)
    r = cp.simulate(closes, sig, cfg, 60, None)
    return cp.sharpe(r["returns"], bpy), cp.sharpe(r["gross"], bpy), r["trades"]

FIB = (0.382, 0.5, 0.618)
rng = random.Random(42)
controls = [tuple(sorted(rng.uniform(0.25, 0.75) for _ in range(3))) for _ in range(40)]
res = {}
for prod in [a for a in sys.argv[1:] if not a.startswith("--")] or ("BTC-USD", "ETH-USD"):
    for gran, bpy in ((3600, 8760.0),) if "--hourly" in sys.argv else ((86400, 365.0), (3600, 8760.0)):
        try:
            closes = load(prod, gran)
        except FileNotFoundError:
            continue
        sw = swings(closes)
        for fee in (40.0,):
            f_net, f_gross, f_tr = run(closes, FIB, bpy, fee, sw)
            ctl = [run(closes, c, bpy, fee, sw)[1] for c in controls]
            rnd = run(closes, (0.333, 0.5, 0.667), bpy, fee, sw)
            pct = sum(1 for c in ctl if c < f_gross) / len(ctl)
            key = f"{prod} {'daily' if gran == 86400 else 'hourly'}"
            res[key] = {"fib_gross_sharpe": round(f_gross, 3), "fib_net_sharpe_45bps": round(f_net, 3), "fib_trades": f_tr,
                        "random_levels_median_gross": round(sorted(ctl)[len(ctl) // 2], 3),
                        "fib_percentile_among_random": round(pct, 2), "thirds_levels_gross": round(rnd[1], 3)}
            print(key, json.dumps(res[key]), flush=True)
json.dump(res, open("fib.json", "w"), indent=1)
