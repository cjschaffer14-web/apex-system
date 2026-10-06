"""Can the level test find a real effect? Plant one and see.

Simulate an hourly random walk with BTC's hourly volatility. Inside the 0.5% band of a golden-ratio level,
the next move pushes back toward the side price came from with probability p (0.5 = no effect). Run the same
bounce test as levels.py against 200 random-phase placebos. Report how often |z| >= 2 (power).
"""
from __future__ import annotations
import json, math
from pathlib import Path
import numpy as np
import levels as L

rng = np.random.default_rng(7)
SIGMA = 0.0075          # ~ BTC hourly log-return s.d. 2017-2026
N = 40_000              # ~4.5 years of hours (one test period)


def simulate(p_push: float, fam) -> np.ndarray:
    x = np.empty(N)
    x[0] = math.log(20_000)
    lv = fam(math.log(2_000), math.log(400_000), 0.0)
    side = 0.0
    for t in range(1, N):
        step = rng.normal(0, SIGMA)
        d = x[t - 1] - lv
        j = np.argmin(np.abs(d))
        if abs(d[j]) >= L.FAR:
            side = np.sign(d[j])
        elif abs(d[j]) <= L.DELTA and side != 0 and rng.random() < p_push:
            step = side * abs(step)          # pushed back to the side it came from
        x[t] = x[t - 1] + step
    return x


def main():
    fam = L.FAMILIES["powers of 1.618 (golden ratio)"]
    out = {}
    for p_push in (0.0, 0.15, 0.3):
        hits, zs = 0, []
        for _ in range(10):
            x = simulate(p_push, fam)
            absr = np.abs(np.diff(x))
            lo, hi = x.min(), x.max()
            real = L.metrics(x, absr, fam(lo, hi, 0.0))["bounce"]
            pl = np.array([L.metrics(x, absr, fam(lo, hi, u))["bounce"] for u in rng.uniform(0, 1, 200)])
            pl = pl[~np.isnan(pl)]
            z = (real - pl.mean()) / pl.std()
            zs.append(round(float(z), 2))
            hits += abs(z) >= 2
        out[f"push {p_push}"] = {"power_|z|>=2": hits / 10, "z": zs}
        print(p_push, out[f"push {p_push}"], flush=True)
    Path(__file__).with_name("levels_power.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
