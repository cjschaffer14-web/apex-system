"""Owner idea (3 Oct 2026): BTC outperformed because of a shared agreement on bitcoin as the base, visible in the
sentiment of groups near "whale" activity. Experiment with media data.

Free, public proxies (private group chats are not reachable; see the reply):
  media      Fear & Greed index (alternative.me; aggregates social media, search trends, volatility, momentum),
             Wikipedia pageviews (Bitcoin, Cryptocurrency), GDELT worldwide news volume and tone for "bitcoin"
  whales     Coin Metrics Community on-chain data: coins flowing into / out of exchanges, exchange balances
             (large holders move coins to exchanges to sell and withdraw them to hold), MVRV (market value vs the
             price every coin last moved at), active addresses
Features use data up to the day before the decision (one-day lag, so nothing is seen early). Targets: BTC's
next 7-day and next 28-day return, sampled without overlap; and next-7-day volatility. Each test is run
before 2022 and from 2022, and a result counts only if it holds in both periods with the same sign and the
full sample clears a Bonferroni bar for every test in this file.
"""
from __future__ import annotations
import datetime as dt, json, math, sqlite3, sys, time, urllib.parse, urllib.request
from pathlib import Path
import numpy as np
from scipy.stats import spearmanr

DB = sys.argv[1] if len(sys.argv) > 1 else "state/market.sqlite"
HERE = Path(__file__).parent
CACHE = HERE / "media_data.json"
OUT = HERE / "media.json"
DAY = 86400
CM_METRICS = ["FlowInExNtv", "FlowOutExNtv", "SplyExNtv", "SplyCur", "CapMVRVCur", "AdrActCnt"]
rng = np.random.default_rng(20261003)


def get(url: str, tries: int = 6, wait: float = 8.0) -> bytes:
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "APEX-research/0.5"}), timeout=90) as r:
                return r.read()
        except Exception as e:                       # 429 / 5xx / timeouts: back off and retry
            if k == tries - 1:
                raise
            time.sleep(wait * (k + 1))
    raise RuntimeError("unreachable")


def fetch_all() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    out: dict = {"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    q = urllib.parse.urlencode({"assets": "btc", "metrics": ",".join(CM_METRICS), "frequency": "1d",
                                "start_time": "2015-01-01", "page_size": 10000})
    rows = json.loads(get(f"https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?{q}"))["data"]
    for m in CM_METRICS:
        out[f"cm:{m}"] = {str(int(dt.datetime.fromisoformat(r["time"].replace("Z", "+00:00")).timestamp()) // DAY): float(r[m])
                          for r in rows if r.get(m) not in (None, "")}
    today = dt.datetime.now(dt.timezone.utc)
    for mode in ("timelinevolraw", "timelinetone"):
        time.sleep(7)
        q = urllib.parse.urlencode({"query": "bitcoin", "mode": mode, "format": "json",
                                    "startdatetime": "20170101000000", "enddatetime": f"{today:%Y%m%d}000000"})
        tl = json.loads(get(f"https://api.gdeltproject.org/api/v2/doc/doc?{q}"))["timeline"][0]["data"]
        out[f"gdelt:bitcoin:{mode}"] = {
            str(int(dt.datetime.strptime(r["date"][:8], "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) // DAY): float(r["value"])
            for r in tl}
    CACHE.write_text(json.dumps(out))
    return out


def series(d: dict, days: np.ndarray) -> np.ndarray:
    return np.array([d.get(str(int(x)), np.nan) for x in days], dtype=float)


def roll_mean(x, n):
    out = np.full_like(x, np.nan)
    for t in range(n - 1, len(x)):
        w = x[t - n + 1:t + 1]
        if np.isfinite(w).sum() >= max(1, int(0.7 * n)):
            out[t] = np.nanmean(w)
    return out


def lag(x, k=1):
    return np.r_[np.full(k, np.nan), x[:-k]]


def build_features(db: str):
    """(days, features, closes): every feature lagged one day so a decision at day t's close sees only day t-1 data."""
    con = sqlite3.connect(db)
    px = dict(con.execute("SELECT ts / 86400, close FROM candles WHERE source='coinbase' AND pair='BTC-USD' AND interval=1440"))
    days = np.arange(min(px), max(px) + 1)
    c = np.array([px.get(int(x), np.nan) for x in days])
    rd = {}
    for metric, ts, v in con.execute("SELECT metric, ts, value FROM readings WHERE source='attention'"):
        rd.setdefault(metric, {})[str(ts)] = v
    ext = fetch_all()

    fng = series(rd["fear_greed"], days)
    wiki = series(rd["wiki:Bitcoin"], days)
    gvol = series(ext["gdelt:bitcoin:timelinevolraw"], days)
    gtone = series(ext["gdelt:bitcoin:timelinetone"], days)
    fin, fout = series(ext["cm:FlowInExNtv"], days), series(ext["cm:FlowOutExNtv"], days)
    sex, sply = series(ext["cm:SplyExNtv"], days), series(ext["cm:SplyCur"], days)
    mvrv, adr = series(ext["cm:CapMVRVCur"], days), series(ext["cm:AdrActCnt"], days)

    feats = {
        "fear & greed level": fng,
        "extreme fear (F&G < 25)": np.where(np.isfinite(fng), (fng < 25).astype(float), np.nan),
        "Wikipedia attention surprise (7d vs prior 28d)": np.log(roll_mean(wiki, 7)) - np.log(lag(roll_mean(wiki, 28), 7)),
        "news volume surprise, GDELT (7d vs prior 28d)": np.log(roll_mean(gvol, 7)) - np.log(lag(roll_mean(gvol, 28), 7)),
        "news tone, GDELT (7d vs prior 28d)": roll_mean(gtone, 7) - lag(roll_mean(gtone, 28), 7),
        "whales: net flow into exchanges, 7d (% of supply)": roll_mean(fin - fout, 7) * 7 / sply,
        "whales: change in exchange balances, 28d (% of supply)": (sex - lag(sex, 28)) / sply,
        "valuation: MVRV (log)": np.log(mvrv),
        "adoption: active addresses (7d vs prior 90d)": np.log(roll_mean(adr, 7)) - np.log(lag(roll_mean(adr, 90), 7)),
    }
    feats = {k: lag(v, 1) for k, v in feats.items()}             # decided at today's close with yesterday's data
    return days, feats, c


def main():
    days, feats, c = build_features(DB)
    logc = np.log(c)
    cut = 1640995200 // DAY
    tests = []
    out = {"data_from_day": int(days[0]), "data_to_day": int(days[-1]), "features": {}}
    for h, label in ((7, "next 7-day return"), (28, "next 28-day return"), (-7, "next 7-day volatility")):
        step = abs(h)
        idx = np.arange(400, len(days) - step, step)                 # non-overlapping decision days
        if h > 0:
            y = logc[idx + h] - logc[idx]
        else:
            r = np.diff(logc)
            y = np.array([np.nansum(np.abs(r[i:i + step])) for i in idx])
        for name, f in feats.items():
            x = f[idx]
            ok = np.isfinite(x) & np.isfinite(y)
            res = {}
            for per, mask in (("to_2021", days[idx] < cut), ("2022_on", days[idx] >= cut), ("full", np.ones(len(idx), bool))):
                m = ok & mask
                if m.sum() < 30:
                    res[per] = None
                    continue
                ic = spearmanr(x[m], y[m]).statistic
                perm = np.array([spearmanr(x[m], rng.permutation(y[m])).statistic for _ in range(1000)])
                res[per] = {"n": int(m.sum()), "ic": round(float(ic), 3), "z": round(float(ic / perm.std()), 2),
                            "p": round(float((np.abs(perm) >= abs(ic)).mean()), 4)}
            tests.append((label, name, res))
            out["features"].setdefault(name, {})[label] = res
    n_tests = len(tests)
    from statistics import NormalDist
    bar = NormalDist().inv_cdf(1 - 0.05 / (2 * n_tests))
    print(f"{n_tests} tests; Bonferroni |z| bar on the full sample {bar:.2f}\n")
    supported = []
    for label, name, res in tests:
        a, b, f = res["to_2021"], res["2022_on"], res["full"]
        ok = bool(a and b and f and abs(a["z"]) >= 2 and abs(b["z"]) >= 2 and (a["ic"] > 0) == (b["ic"] > 0) and abs(f["z"]) >= bar)
        res["supported"] = ok
        if ok:
            supported.append(f"{name} -> {label}")
        fmt = lambda r: f"IC {r['ic']:+.3f} z {r['z']:+.2f} (n {r['n']})" if r else "n/a"
        print(f"{label:22s} {name:56s} to2021 {fmt(a):28s} 2022+ {fmt(b):28s} full {fmt(f)}{'  SUPPORTED' if ok else ''}")
    out["n_tests"], out["bonferroni_z"], out["supported"] = n_tests, round(bar, 2), supported
    OUT.write_text(json.dumps(out, indent=1))
    print("\nSUPPORTED:", supported or "none")


if __name__ == "__main__":
    main()
