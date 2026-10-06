"""Real-data baseline: v0.4.1 walk-forward (8 rules) on Coinbase BTC/ETH, at three cost levels."""
import sys, json, math
sys.path.insert(0, '/home/claude/build/APEX_v0_4')
from apex.ext import crypto_pack as cp

def load(prod, gran):
    rows = json.load(open(f"{prod}_{gran}.json"))
    # keep the longest run of consecutive bars (exchange outages leave gaps)
    closes, last = [], None
    for ts, o, h, l, c, v in rows:
        if last is not None and ts - last > gran:          # gap: carry the price flat across missing bars
            for _ in range((ts - last) // gran - 1):
                closes.append(closes[-1])
        closes.append(c); last = ts
    return closes

out = {}
for prod in ("BTC-USD", "ETH-USD"):
    for gran, bpy, tr, te in ((86400, 365.0, 365, 90), (3600, 8760.0, 24 * 90, 24 * 30)):
        try:
            closes = load(prod, gran)
        except FileNotFoundError:
            continue
        for bps_fee in (80.0, 40.0, 5.0):
            cfg = cp.SimConfig(bars_per_year=bpy, fee_bps=bps_fee)
            r = cp.walk_forward(closes, cfg, tr, te, n_trials=6)
            key = f"{prod} {'daily' if gran == 86400 else 'hourly'} fee{int(bps_fee)}"
            out[key] = {k: (round(r[k], 3) if isinstance(r[k], float) else r[k]) for k in
                        ("oos_bars", "trades", "oos_sharpe", "gross_sharpe", "oos_return", "max_drawdown", "halted",
                         "avg_exposure", "buy_hold_sharpe", "buy_hold_return", "dsr")}
            out[key]["T2"] = cp.t2_gate(r).passed
            out[key]["T2_proposed"] = cp.t2_strict_gate(r).passed
            print(key, json.dumps(out[key]), flush=True)
json.dump(out, open("baseline.json", "w"), indent=1)
