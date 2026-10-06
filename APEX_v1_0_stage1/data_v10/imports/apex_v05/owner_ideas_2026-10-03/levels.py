"""Owner idea (3 Oct 2026): BTC reacts at special price levels -- round numbers (10k, 20k, 50k) and their
golden-ratio multiples (16.18k, 32.4k, 64.7k, 161.8k) -- and at powers of 1.618, 1.1618, e and pi.

Test. For each level family, measure on BTC-USD hourly closes (Coinbase, 2017 to now):
  bounce   when price comes within 0.5% of a level (after being at least 1.5% away), how often it turns back
           (moves 1.5% away on the side it came from) rather than breaking through, within 72 hours
  vol      mean absolute next-hour return while price sits within 0.5% of a level, relative to all hours
  dwell    share of hours spent within 0.25% of a level (do prices cluster there?)
Null. The same family with its levels shifted to a random position: geometric grids are rotated in log
space (same ratio, random phase), round-number sets are rotated by a random factor (log-periodic sets) or a
random additive offset (multiples of 10k). Each placebo has exactly the same number and spacing of levels,
so anything that is just "prices move" cancels. The real levels must beat the placebos.
Two periods (2017-2021, 2022-2026) and the full sample; z-scores against 400 placebos.
"""
from __future__ import annotations
import json, math, sqlite3, sys
from pathlib import Path
import numpy as np

DB = sys.argv[1] if len(sys.argv) > 1 else "state/market.sqlite"
OUT = Path(__file__).with_name("levels.json")
PHI = (1 + 5 ** 0.5) / 2
DELTA = 0.005          # band half-width (log), ~0.5%
FAR = 3 * DELTA        # "away" threshold, ~1.5%
H = 72                 # hours to resolve bounce vs break
N_PLACEBO = 400
rng = np.random.default_rng(20261003)


def load(db):
    rows = sqlite3.connect(db).execute(
        "SELECT ts, close FROM candles WHERE source='coinbase' AND pair='BTC-USD' AND interval=60 ORDER BY ts").fetchall()
    ts = np.array([r[0] for r in rows], dtype=np.int64)
    x = np.log(np.array([r[1] for r in rows], dtype=float))
    return ts, x


def geometric(r, anchor=1.0):
    def levels(lo, hi, u):
        a = math.log(anchor) + u * math.log(r)
        n0, n1 = math.floor((lo - a) / math.log(r)) - 1, math.ceil((hi - a) / math.log(r)) + 1
        return np.array([a + n * math.log(r) for n in range(n0, n1 + 1)])
    return levels


def log_periodic(mantissas):
    """{m x 10^k}; placebo rotates the whole pattern by 10^u (u in [0,1))."""
    def levels(lo, hi, u):
        out = []
        for k in range(math.floor(lo / math.log(10)) - 1, math.ceil(hi / math.log(10)) + 2):
            for m in mantissas:
                out.append(math.log(m) + k * math.log(10) + u * math.log(10))
        return np.array(sorted(out))
    return levels


def arithmetic(step):
    """multiples of `step`; placebo adds a random offset in [0, step)."""
    def levels(lo, hi, u):
        a, b = math.exp(lo), math.exp(hi)
        n0, n1 = max(1, math.floor(a / step) - 1), math.ceil(b / step) + 1
        return np.log(np.array([n * step + u * step for n in range(n0, n1 + 1) if n * step + u * step > 0]))
    return levels


FAMILIES = {
    "round 1-2-5 (10k, 20k, 50k, 100k ...)": log_periodic([1, 2, 5]),
    "round multiples of 10k": arithmetic(10_000),
    "round x golden ratio (16.18k, 32.4k, 64.7k, 161.8k ...)": log_periodic([PHI, 2 * PHI, 4 * PHI, 5 * PHI]),
    "powers of 1.618 (golden ratio)": geometric(PHI),
    "powers of 1.1618 (as written)": geometric(1.1618),
    "powers of e": geometric(math.e),
    "powers of pi": geometric(math.pi),
}


def metrics(x, absr, lv):
    """bounce rate, n touches, vol ratio, dwell share for one set of log-levels lv over log prices x."""
    bounces = breaks = 0
    near = np.zeros(len(x), dtype=bool)
    dwell = np.zeros(len(x), dtype=bool)
    lo, hi = x.min() - FAR, x.max() + FAR
    for L in lv[(lv > lo) & (lv < hi)]:
        d = x - L
        ad = np.abs(d)
        inb = ad <= DELTA
        near |= inb
        dwell |= ad <= DELTA / 2
        far = np.flatnonzero(ad >= FAR)
        if len(far) < 2 or not inb.any():
            continue
        entries = np.flatnonzero(inb & ~np.r_[False, inb[:-1]])
        k = np.searchsorted(far, entries)
        ok = (k > 0) & (k < len(far))
        entries, k = entries[ok], k[ok]
        if not len(entries):
            continue
        prev_far, next_far = far[k - 1], far[k]
        _, first = np.unique(prev_far, return_index=True)          # one touch per excursion
        entries, prev_far, next_far = entries[first], prev_far[first], next_far[first]
        resolved = next_far - entries <= H
        same = np.sign(d[prev_far]) == np.sign(d[next_far])
        bounces += int((same & resolved).sum())
        breaks += int((~same & resolved).sum())
    n = bounces + breaks
    nr = near[:-1]
    vol = float(absr[nr].mean() / absr.mean()) if nr.any() else float("nan")
    return {"bounce": bounces / n if n else float("nan"), "touches": n, "vol": vol, "dwell": float(dwell.mean())}


def run_period(x, label):
    absr = np.abs(np.diff(x))
    lo, hi = x.min(), x.max()
    out = {}
    for name, fam in FAMILIES.items():
        real = metrics(x, absr, fam(lo, hi, 0.0))
        plac = [metrics(x, absr, fam(lo, hi, u)) for u in rng.uniform(0, 1, N_PLACEBO)]
        row = {"real": {k: round(v, 4) if isinstance(v, float) else v for k, v in real.items()}}
        for m in ("bounce", "vol", "dwell"):
            pv = np.array([p[m] for p in plac if not math.isnan(p[m])])
            z = (real[m] - pv.mean()) / pv.std() if pv.std() > 0 else 0.0
            p_two = float((np.abs(pv - pv.mean()) >= abs(real[m] - pv.mean())).mean())
            row[m] = {"placebo_mean": round(float(pv.mean()), 4), "z": round(float(z), 2), "p": round(p_two, 4)}
        out[name] = row
        print(f"{label:9s} {name:58s} touches {real['touches']:5d}  bounce {real['bounce']:.3f} (z {row['bounce']['z']:+.2f})"
              f"  vol x{real['vol']:.3f} (z {row['vol']['z']:+.2f})  dwell z {row['dwell']['z']:+.2f}", flush=True)
    return out


def main():
    ts, x = load(DB)
    cut = 1640995200                   # 2022-01-01 UTC
    res = {"data": {"hours": int(len(x)), "from": int(ts[0]), "to": int(ts[-1])},
           "settings": {"band": DELTA, "away": FAR, "resolve_hours": H, "placebos": N_PLACEBO},
           "families": len(FAMILIES), "metrics": 3}
    res["2017-2021"] = run_period(x[ts < cut], "2017-21")
    res["2022-2026"] = run_period(x[ts >= cut], "2022-26")
    res["full"] = run_period(x, "full")
    # a family/metric counts as supported only if |z| >= 2 in both periods with the same sign and the full-sample
    # z clears a Bonferroni bar for 7 families x 3 metrics (|z| >= 3.04, two-sided 0.05/21)
    verdicts = {}
    for name in FAMILIES:
        for m in ("bounce", "vol", "dwell"):
            a, b, f = res["2017-2021"][name][m]["z"], res["2022-2026"][name][m]["z"], res["full"][name][m]["z"]
            ok = abs(a) >= 2 and abs(b) >= 2 and (a > 0) == (b > 0) and abs(f) >= 3.04
            verdicts[f"{name} | {m}"] = {"z_2017_21": a, "z_2022_26": b, "z_full": f, "supported": ok}
    res["verdicts"] = verdicts
    OUT.write_text(json.dumps(res, indent=1))
    print("\nSUPPORTED:", [k for k, v in verdicts.items() if v["supported"]] or "none")


if __name__ == "__main__":
    main()
