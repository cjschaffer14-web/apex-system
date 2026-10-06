"""Cross-sectional 2-week momentum on 18 Coinbase coins, weekly rebalance, real daily closes.
Survivorship bias: the universe is coins still listed today, which flatters long-only results."""
import sys, json, math, glob
sys.path.insert(0, '/home/claude/build/APEX_v0_4')
from apex.ext import crypto_pack as cp

px = {}
for f in glob.glob("*_86400.json"):
    prod = f.split("_")[0]
    px[prod] = {ts // 86400: c for ts, o, h, l, c, v in json.load(open(f))}
days = sorted(set().union(*[set(d) for d in px.values()]))
d0 = max(min(px["BTC-USD"]), days[0])
days = [d for d in days if d >= d0]

def ret(prod, a, b):
    s = px[prod]
    return s[b] / s[a] - 1 if a in s and b in s else None

def run(k=3, look=14, hold=7, cost_bps=85.0, long_short=False, min_coins=6):
    c = cost_bps / 1e4
    w_prev, rets = {}, []
    for i in range(look, len(days) - hold, hold):
        t = days[i]
        scores = {p: ret(p, t - look, t) for p in px}
        scores = {p: s for p, s in scores.items() if s is not None and all(t + j in px[p] for j in range(hold + 1))}
        if len(scores) < min_coins:
            continue
        ranked = sorted(scores, key=scores.get)
        w = {p: 1.0 / k for p in ranked[-k:]}
        if long_short:
            w = {p: 0.5 / k for p in ranked[-k:]}
            for p in ranked[:k]:
                w[p] = -0.5 / k
        turnover = sum(abs(w.get(p, 0) - w_prev.get(p, 0)) for p in set(w) | set(w_prev))
        for j in range(hold):
            day_r = sum(wt * (px[p][t + j + 1] / px[p][t + j] - 1) for p, wt in w.items())
            rets.append(day_r - (turnover * c if j == 0 else 0.0))
        w_prev = w
    eq, curve = 1.0, [1.0]
    for r in rets:
        eq *= 1 + r; curve.append(eq)
    return {"days": len(rets), "sharpe": round(cp.sharpe(rets, 365.0), 3), "total_return": round(eq - 1, 3),
            "max_drawdown": round(cp.max_drawdown(curve), 3), "psr": round(cp.probabilistic_sharpe(rets), 3)}

def basket(cost=0.0):
    rets = []
    for i in range(len(days) - 1):
        t = days[i]
        rs = [px[p][t + 1] / px[p][t] - 1 for p in px if t in px[p] and t + 1 in px[p]]
        if len(rs) >= 6:
            rets.append(sum(rs) / len(rs))
    eq, curve = 1.0, [1.0]
    for r in rets:
        eq *= 1 + r; curve.append(eq)
    return {"days": len(rets), "sharpe": round(cp.sharpe(rets, 365.0), 3), "total_return": round(eq - 1, 3),
            "max_drawdown": round(cp.max_drawdown(curve), 3)}

res = {
    "long_only_top3_85bps": run(),
    "long_only_top3_45bps": run(cost_bps=45),
    "long_short_3x3_perps_6bps": run(long_short=True, cost_bps=6),
    "long_short_3x3_85bps": run(long_short=True, cost_bps=85),
    "equal_weight_basket_hold": basket(),
}
for k, v in res.items():
    print(k, json.dumps(v))
print("universe", len(px), "coins; first day", days[0] * 86400)
json.dump(res, open("xsec.json", "w"), indent=1)
