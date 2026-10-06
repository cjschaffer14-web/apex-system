"""Two checks on occam.py's leading rule (hold BTC only above its 200-day average):
1. Is it better than plain holding beyond luck? Paired stationary block bootstrap (mean block 20 days) of the
   Sharpe difference and the max-drawdown difference, 2000 resamples, spot taker costs (85 bps).
2. Does the same rule, unchanged, do the same on ETH, an asset it was not chosen on?
"""
from __future__ import annotations
import json, math, sys
from pathlib import Path
import numpy as np
import occam as O

rng = np.random.default_rng(11)


def sharpe(r):
    return r.mean() / r.std() * math.sqrt(365) if r.std() > 0 else 0.0


def mdd(r):
    eq = np.cumprod(1 + r)
    return float(np.max(1 - eq / np.maximum.accumulate(eq)))


def block_idx(n, mean_block=20):
    out, p = np.empty(n, dtype=int), 1 / mean_block
    i = rng.integers(n)
    for k in range(n):
        out[k] = i
        i = rng.integers(n) if rng.random() < p else (i + 1) % n
    return out


def main(db):
    days, pairs, px = O.load(db)
    res = {}
    for asset in ("BTC-USD", "ETH-USD"):
        j = pairs.index(asset)
        first = int(np.argmax(~np.isnan(px[:, j])))
        c = px[first:, j]
        r = np.r_[np.nan, c[1:] / c[:-1] - 1]
        nets = {}
        for rule in ("hold", "sma200", "sma200_vt"):
            net, _ = O.run(O.btc_rule(rule, c), r, 85)
            nets[rule] = np.nan_to_num(net[200:])
        row = {k: {"sharpe": round(sharpe(v), 3), "max_drawdown": round(mdd(v), 3),
                   "cagr": round(float(np.prod(1 + v) ** (365 / len(v)) - 1), 4)} for k, v in nets.items()}
        for rule in ("sma200", "sma200_vt"):
            ds, dd = [], []
            for _ in range(2000):
                ix = block_idx(len(nets["hold"]))
                a, b = nets[rule][ix], nets["hold"][ix]
                ds.append(sharpe(a) - sharpe(b))
                dd.append(mdd(b) - mdd(a))
            ds, dd = np.array(ds), np.array(dd)
            row[f"{rule}_vs_hold"] = {"sharpe_diff": round(sharpe(nets[rule]) - sharpe(nets["hold"]), 3),
                                      "p_sharpe_better": round(float((ds > 0).mean()), 3),
                                      "drawdown_reduction": round(mdd(nets["hold"]) - mdd(nets[rule]), 3),
                                      "p_drawdown_smaller": round(float((dd > 0).mean()), 3)}
        res[asset] = row
        print(asset, json.dumps(row))
    Path(__file__).with_name("occam_check.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
