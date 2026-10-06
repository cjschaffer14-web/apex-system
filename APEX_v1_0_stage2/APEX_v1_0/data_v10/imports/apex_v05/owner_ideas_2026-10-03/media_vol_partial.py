"""Follow-up to media.py: do the volatility leads survive once today's own volatility is known?
Volatility clusters, and fear, exchange flows and MVRV all rise after big moves. Partial rank correlation of each
feature with next-7-day volatility, controlling for the last 7 and 28 days of realized volatility (OLS on ranks).
"""
import json, sys
import numpy as np
from scipy.stats import rankdata
import media as M

def resid(v, X):
    A = np.c_[np.ones(len(v)), X]
    return v - A @ np.linalg.lstsq(A, v, rcond=None)[0]

def main(db):
    import sqlite3
    con = sqlite3.connect(db)
    px = dict(con.execute("SELECT ts / 86400, close FROM candles WHERE source='coinbase' AND pair='BTC-USD' AND interval=1440"))
    days = np.arange(min(px), max(px) + 1)
    logc = np.log(np.array([px.get(int(x), np.nan) for x in days]))
    r = np.abs(np.r_[np.nan, np.diff(logc)])
    v7 = np.array([np.nansum(r[max(0, t - 6):t + 1]) for t in range(len(r))])
    v28 = np.array([np.nansum(r[max(0, t - 27):t + 1]) / 4 for t in range(len(r))])
    feats = M.build_features(db)[1]
    idx = np.arange(400, len(days) - 7, 7)
    y = np.array([np.nansum(r[i + 1:i + 8]) for i in idx])
    cut = 1640995200 // 86400
    out = {}
    for name, f in feats.items():
        x = f[idx]
        row = {}
        for per, mask in (("to_2021", days[idx] < cut), ("2022_on", days[idx] >= cut), ("full", np.ones(len(idx), bool))):
            m = np.isfinite(x) & np.isfinite(y) & mask
            ctrl = np.c_[rankdata(v7[idx][m]), rankdata(v28[idx][m])]
            a, b = resid(rankdata(x[m]), ctrl), resid(rankdata(y[m]), ctrl)
            pc = float(np.corrcoef(a, b)[0, 1])
            row[per] = {"n": int(m.sum()), "partial_ic": round(pc, 3), "z": round(pc * np.sqrt(m.sum() - 3), 2)}
        out[name] = row
        print(f"{name:56s} " + "  ".join(f"{p} {row[p]['partial_ic']:+.3f} (z {row[p]['z']:+.2f})" for p in row))
    M.HERE.joinpath("media_vol_partial.json").write_text(json.dumps(out, indent=1))

if __name__ == "__main__":
    main(sys.argv[1])
