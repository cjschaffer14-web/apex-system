"""Owner question (3 Oct 2026): can we get a positive return simply (Occam's razor) before deployment?

The simplest rules, written down before looking at results, each with textbook parameters and nothing fitted:
  hold            always hold BTC
  sma50/100/200   hold BTC while yesterday's close is above its 50/100/200-day average, else cash
  tsmom28/90      hold BTC while its 28/90-day return is positive, else cash
  voltarget       hold BTC sized to 50% annual volatility (30-day realized), capped at 1x
  sma200_vt       the 200-day filter and the volatility sizing together
  basket_sma200   equal-weight the coins that are above their own 200-day average (6+ coins listed)
Daily Coinbase closes. The signal uses closes up to day t; the position earns day t+1's return. Costs are
charged on every change of position: 85 bps (spot taker) and 40 bps (spot maker). Long-only, no leverage,
no funding. Two periods (to 2021, 2022 to now). The deflated Sharpe counts every trial the research
program has run so far (21 in v0.5 + these 9).
"""
from __future__ import annotations
import json, math, sqlite3, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from apex.ext.crypto_pack import deflated_sharpe          # noqa: E402

DB = sys.argv[1] if len(sys.argv) > 1 else "state/market.sqlite"
OUT = Path(__file__).with_name("occam.json")
PRIOR_TRIALS = 21
DAY = 86400


def load(db):
    con = sqlite3.connect(db)
    pairs = [r[0] for r in con.execute("SELECT DISTINCT pair FROM candles WHERE source='coinbase' AND interval=1440")]
    days = sorted({r[0] // DAY for r in con.execute("SELECT ts FROM candles WHERE source='coinbase' AND interval=1440")})
    idx = {d: i for i, d in enumerate(days)}
    px = np.full((len(days), len(pairs)), np.nan)
    for j, p in enumerate(pairs):
        for ts, c in con.execute("SELECT ts, close FROM candles WHERE source='coinbase' AND interval=1440 AND pair=?", (p,)):
            px[idx[ts // DAY], j] = c
    return np.array(days), pairs, px


def sma(x, n):
    """n-day average, defined only where all n of the last days have a close (no zeros counted before listing)."""
    out = np.full_like(x, np.nan)
    c = np.nancumsum(x)
    k = np.cumsum(~np.isnan(x))
    s = c[n - 1:] - np.r_[0, c[:-n]]
    cnt = k[n - 1:] - np.r_[0, k[:-n]]
    out[n - 1:] = np.where(cnt == n, s / n, np.nan)
    return out


def realized_vol(x, n=30):
    r = np.r_[np.nan, np.diff(np.log(x))]
    out = np.full_like(x, np.nan)
    for t in range(n, len(x)):
        out[t] = np.nanstd(r[t - n + 1:t + 1]) * math.sqrt(365)
    return out


def btc_rule(name, c):
    if name == "hold":
        return np.ones_like(c)
    if name.startswith("sma") and name[3:].isdigit():
        n = int(name[3:])
        return (c > sma(c, n)).astype(float) * ~np.isnan(sma(c, n))
    if name.startswith("tsmom"):
        n = int(name[5:])
        w = np.zeros_like(c)
        w[n:] = (c[n:] / c[:-n] > 1).astype(float)
        return w
    vt = np.nan_to_num(np.minimum(1.0, 0.5 / realized_vol(c)), nan=0.0)
    if name == "voltarget":
        return vt
    if name == "sma200_vt":
        return btc_rule("sma200", c) * vt
    raise ValueError(name)


def basket_rule(px):
    w = np.zeros_like(px)
    for j in range(px.shape[1]):
        s = sma(px[:, j], 200)
        w[:, j] = np.nan_to_num((px[:, j] > s).astype(float) * ~np.isnan(s))
    live = (~np.isnan(px)).sum(axis=1) >= 6
    n_on = w.sum(axis=1)
    w = np.where((n_on > 0)[:, None] & live[:, None], w / np.maximum(n_on, 1)[:, None], 0.0)
    return w


def run(weights, rets, cost_bps):
    """weights[t] decided at close t, earns rets[t+1]. Returns the daily net return series aligned to t+1."""
    w = np.nan_to_num(weights)
    if w.ndim == 1:
        w, rets = w[:, None], rets[:, None]
    gross = (w[:-1] * np.nan_to_num(rets[1:])).sum(axis=1)
    turn = np.abs(np.diff(np.vstack([np.zeros(w.shape[1]), w]), axis=0)).sum(axis=1)[:-1]
    return gross - turn * cost_bps / 1e4, turn


def stats(r, n_trials):
    r = r[~np.isnan(r)]
    eq = np.cumprod(1 + r)
    years = len(r) / 365
    mdd = float(np.max(1 - eq / np.maximum.accumulate(eq)))
    sh = float(r.mean() / r.std() * math.sqrt(365)) if r.std() > 0 else 0.0
    return {"cagr": round(float(eq[-1] ** (1 / years) - 1), 4), "sharpe": round(sh, 3), "max_drawdown": round(mdd, 3),
            "total_x": round(float(eq[-1]), 2), "dsr": round(deflated_sharpe(list(r), n_trials), 3), "days": int(len(r))}


def main():
    days, pairs, px = load(DB)
    b = pairs.index("BTC-USD")
    first = int(np.argmax(~np.isnan(px[:, b])))
    days, px = days[first:], px[first:]
    c = px[:, b]
    rets_all = np.r_[np.full((1, px.shape[1]), np.nan), px[1:] / px[:-1] - 1]
    rules = ["hold", "sma50", "sma100", "sma200", "tsmom28", "tsmom90", "voltarget", "sma200_vt", "basket_sma200"]
    n_trials = PRIOR_TRIALS + len(rules)
    cut = 1640995200 // DAY
    warm = 200                                                  # every rule starts on the same day (200-day warm-up)
    out = {"data": {"from_day": int(days[warm]), "to_day": int(days[-1])}, "n_trials_counted": n_trials, "rules": {}}
    for name in rules:
        w = basket_rule(px) if name == "basket_sma200" else btc_rule(name, c)
        rr = rets_all if name == "basket_sma200" else rets_all[:, b]
        row = {}
        for cost in (85, 40):
            net, turn = run(w, rr, cost)
            net, turn, d = net[warm:], turn[warm:], days[warm + 1:]
            row[f"{cost}bps"] = {"full": stats(net, n_trials), "to_2021": stats(net[d < cut], n_trials),
                                 "2022_on": stats(net[d >= cut], n_trials), "last_365d": stats(net[-365:], n_trials),
                                 "trades_per_year": round(float((turn > 0).sum() / (len(turn) / 365)), 1),
                                 "time_in_market": round(float(np.mean(np.nan_to_num(w[warm:]).sum(axis=1) if np.ndim(w) == 2 else np.nan_to_num(w[warm:]))), 3)}
        out["rules"][name] = row
        f, a, z = row["85bps"]["full"], row["85bps"]["to_2021"], row["85bps"]["2022_on"]
        print(f"{name:14s} 85bps: CAGR {f['cagr']:+.1%} Sharpe {f['sharpe']:.2f} maxDD {f['max_drawdown']:.0%} DSR {f['dsr']:.2f} | "
              f"to2021 Sh {a['sharpe']:.2f} | 2022+ Sh {z['sharpe']:.2f} CAGR {z['cagr']:+.1%} DD {z['max_drawdown']:.0%} | "
              f"last365 {row['85bps']['last_365d']['cagr']:+.1%} | trades/yr {row['85bps']['trades_per_year']}", flush=True)
    OUT.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
