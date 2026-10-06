"""v0.5.1: three more kinds of owner hypothesis, from the owner's ideas of 3 Oct 2026.

  level    "BTC reacts at special prices": round numbers, golden-ratio multiples, powers of 1.618, e, pi ...
           Bounce rate and volatility near the levels, against the same grid shifted to random positions.
  rule     "a simple rule makes money": a long-only trend / momentum / volatility-sized rule on one coin, with
           costs, against simply holding that coin (Sharpe, drawdown, deflated Sharpe over every trial).
  feature  "media or whale activity predicts the market": any stored attention or on-chain series against the
           next 7- or 28-day return, or next-week volatility (controlling for today's volatility).

Every kind is tested before 2022 and from 2022; a result counts only if it holds in both periods with the same
sign. Like every owner hypothesis, it is registered before it is tested and counted as a trial. Standard library
only, so it runs anywhere APEX runs. `core_trend_weights` is the rule behind the proposed BTC core paper book.
"""
from __future__ import annotations
import bisect, datetime as dt, math, random
from statistics import mean, pstdev
from typing import Any, Callable
from . import crypto_pack as cp
from . import research_v05 as rv

PHI = (1 + 5 ** 0.5) / 2
SPLIT_TS = dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc).timestamp()
DAY = 86400


def _closes(store: cp.MarketStore, product: str, interval: int) -> list[tuple[int, float]]:
    return [(int(t), float(c)) for t, c in store.db.execute(
        "SELECT ts, close FROM candles WHERE source='coinbase' AND pair=? AND interval=? ORDER BY ts",
        (product, interval)) if c and c > 0]


def _ranks(v: list[float]) -> list[float]:
    order = sorted(range(len(v)), key=v.__getitem__)
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def _pearson(x: list[float], y: list[float]) -> float:
    mx, my = mean(x), mean(y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else 0.0


def _residualize(y: list[float], cols: list[list[float]]) -> list[float]:
    """y minus its least-squares fit on [1, cols...] (normal equations, Gauss-Jordan; a handful of columns)."""
    X = [[1.0] + [c[i] for c in cols] for i in range(len(y))]
    k = len(X[0])
    A = [[sum(r[i] * r[j] for r in X) for j in range(k)] + [sum(r[i] * yy for r, yy in zip(X, y))] for i in range(k)]
    for i in range(k):
        p = max(range(i, k), key=lambda r: abs(A[r][i]))
        A[i], A[p] = A[p], A[i]
        if abs(A[i][i]) < 1e-12:
            return list(y)
        for r in range(k):
            if r != i:
                f = A[r][i] / A[i][i]
                A[r] = [a - f * b for a, b in zip(A[r], A[i])]
    beta = [A[i][k] / A[i][i] for i in range(k)]
    return [yy - sum(b * xv for b, xv in zip(beta, row)) for yy, row in zip(y, X)]


# =================================================================================================================
# 1. Price levels
# =================================================================================================================
LEVEL_BAND, LEVEL_AWAY, LEVEL_RESOLVE_H = 0.005, 0.015, 72      # +-0.5% band, 1.5% away, 72 hours to resolve


def level_grid(spec: dict, lo: float, hi: float, u: float) -> list[float]:
    """Log-price levels of a family between lo and hi (log prices). u in [0, 1) shifts the family: u = 0 is the
    owner's grid; any other u is a placebo with exactly the same number and spacing of levels."""
    fam = spec.get("family")
    if fam == "geometric":                                # anchor x ratio^n   (powers of 1.618, e, pi ...)
        lr = math.log(float(spec["ratio"]))
        a = math.log(float(spec.get("anchor", 1.0))) + u * lr
        return [a + n * lr for n in range(math.floor((lo - a) / lr) - 1, math.ceil((hi - a) / lr) + 2)]
    if fam == "round":                                    # mantissa x times x 10^k   (10k, 20k, 50k; 16.18k ...)
        ms = [math.log(float(m) * float(spec.get("times", 1.0))) for m in spec.get("mantissas", [1, 2, 5])]
        l10 = math.log(10)
        out = [m + k * l10 + u * l10 for k in range(math.floor(lo / l10) - 2, math.ceil(hi / l10) + 2) for m in ms]
        return sorted(out)
    if fam == "arithmetic":                               # n x step + offset    (multiples of 10,000)
        step = float(spec["step"])
        a, b = math.exp(lo), math.exp(hi)
        return [math.log(n * step + u * step) for n in range(max(0, math.floor(a / step) - 1), math.ceil(b / step) + 2)
                if n * step + u * step > 0]
    raise ValueError(f"unknown level family {fam!r}")


def _level_spacing_ok(lv: list[float]) -> bool:
    return all(b - a > 2 * LEVEL_AWAY for a, b in zip(lv, lv[1:]))


def _level_scan(x: list[float], period: list[int], lv: list[float]) -> list[list[float]]:
    """One pass over hourly log prices. Per period: [bounces, breaks, sum |next move| in band, hours in band].
    A touch: price enters the +-0.5% band of a level after being at least 1.5% away. It bounces if the next time it
    is 1.5% away, it is on the side it came from (within 72 hours); otherwise it broke through."""
    acc = [[0, 0, 0.0, 0], [0, 0, 0.0, 0]]
    n, m = len(x), len(lv)
    zone, side_in, touched, touched_p = None, 0, -1, 0
    bl = bisect.bisect_left
    for t in range(n):
        xt = x[t]
        j = bl(lv, xt)
        if j == 0:
            L = lv[0]
        elif j == m:
            L = lv[m - 1]
        else:
            L = lv[j] if lv[j] - xt < xt - lv[j - 1] else lv[j - 1]
        d = xt - L
        ad = -d if d < 0 else d
        if ad < LEVEL_AWAY:
            if zone != L:
                zone, touched = L, -1
                side_in = (1 if x[t - 1] > L else -1) if t > 0 else 0
            if ad <= LEVEL_BAND:
                if touched < 0:
                    touched, touched_p = t, period[t]
                if t + 1 < n:
                    a = acc[period[t]]
                    mv = x[t + 1] - xt
                    a[2] += -mv if mv < 0 else mv
                    a[3] += 1
        elif zone is not None:
            if touched >= 0 and side_in and t - touched <= LEVEL_RESOLVE_H:
                acc[touched_p][0 if (1 if d > 0 else -1) == side_in else 1] += 1
            zone, touched = None, -1
    return acc


def test_level(store: cp.MarketStore, spec: dict, placebos: int = 100, seed: int = 20261003) -> dict:
    rows = _closes(store, spec.get("product", "BTC-USD"), 60)
    if len(rows) < 2000:
        return {"note": "not enough hourly history yet", "retry": True}
    x = [math.log(c) for _, c in rows]
    period = [0 if t < SPLIT_TS else 1 for t, _ in rows]
    lo, hi = min(x) - 0.1, max(x) + 0.1
    try:
        real_lv = level_grid(spec, lo, hi, 0.0)
    except (KeyError, ValueError) as e:
        return {"note": f"bad level spec: {e}"}
    if not _level_spacing_ok(real_lv):
        return {"note": "levels closer than 3% apart cannot be told apart at this band width"}
    base = [0.0, 0.0]
    cnt = [0, 0]
    for t in range(len(x) - 1):
        base[period[t]] += abs(x[t + 1] - x[t])
        cnt[period[t]] += 1
    base = [b / c if c else 0.0 for b, c in zip(base, cnt)]

    def summarize(acc: list[list[float]]) -> list[tuple[float, float, int]]:
        out = []
        for p in (0, 1):
            b, k, s, h = acc[p]
            out.append(((b / (b + k)) if b + k else float("nan"), (s / h / base[p]) if h and base[p] else float("nan"), b + k))
        return out

    real = summarize(_level_scan(x, period, real_lv))
    rng = random.Random(seed)
    plac = [summarize(_level_scan(x, period, level_grid(spec, lo, hi, rng.random()))) for _ in range(placebos)]
    res: dict[str, Any] = {}
    for p, name in ((0, "to_2021"), (1, "2022_on")):
        row: dict[str, Any] = {"touches": real[p][2]}
        for i, metric in ((0, "bounce"), (1, "vol")):
            pv = [q[p][i] for q in plac if not math.isnan(q[p][i])]
            sd = pstdev(pv) if len(pv) > 2 else 0.0
            row[metric] = round(real[p][i], 4)
            row[f"{metric}_placebo"] = round(mean(pv), 4) if pv else None
            row[f"{metric}_z"] = round((real[p][i] - mean(pv)) / sd, 2) if sd > 0 and not math.isnan(real[p][i]) else 0.0
        res[name] = row
    found = [mt for mt in ("bounce", "vol") if abs(res["to_2021"][f"{mt}_z"]) >= 2 and abs(res["2022_on"][f"{mt}_z"]) >= 2
             and (res["to_2021"][f"{mt}_z"] > 0) == (res["2022_on"][f"{mt}_z"] > 0)]
    res.update({"placebos": placebos, "supported": bool(found),
                "verdict": (f"supported in both periods ({', '.join(found)})" if found else
                            "not supported: these levels behave like randomly placed levels with the same spacing")})
    return res


# =================================================================================================================
# 2. Simple rules (Occam's razor)
# =================================================================================================================
def rule_weights(closes: list[float], rule: str = "sma", days: int = 200, vol_target: float | None = None,
                 vol_days: int = 30, band: float = 0.0) -> list[float]:
    """Weight decided at each close using closes up to that day only (long-only, 0..1). With `band`, a change of
    size smaller than the band is skipped unless it switches the position on or off."""
    n = len(closes)
    w = [0.0] * n
    logr = [0.0] + [math.log(closes[i] / closes[i - 1]) for i in range(1, n)]
    s = s1 = s2 = 0.0
    prev = 0.0
    for t in range(n):
        s += closes[t]
        if t >= days:
            s -= closes[t - days]
        s1 += logr[t]
        s2 += logr[t] ** 2
        if t >= vol_days:
            s1 -= logr[t - vol_days]
            s2 -= logr[t - vol_days] ** 2
        if rule == "hold":
            on = 1.0
        elif rule == "sma":
            on = 1.0 if t >= days - 1 and closes[t] > s / days else 0.0
        elif rule == "tsmom":
            on = 1.0 if t >= days and closes[t] > closes[t - days] else 0.0
        else:
            raise ValueError(f"unknown rule {rule!r}")
        if vol_target and on:
            if t < vol_days:
                on = 0.0
            else:
                var = max(s2 / vol_days - (s1 / vol_days) ** 2, 1e-12)
                on = min(1.0, vol_target / math.sqrt(var * 365))
        target = on
        if band and prev > 0 and target > 0 and abs(target - prev) < band:
            target = prev
        w[t] = prev = target
    return w


def rule_returns(closes: list[float], weights: list[float], cost_bps: float) -> list[float]:
    """Net daily returns: the weight set at close t earns day t+1; costs are paid on every change of weight."""
    out, prev = [], 0.0
    for t in range(len(closes) - 1):
        cost = abs(weights[t] - prev) * cost_bps / 1e4
        out.append(weights[t] * (closes[t + 1] / closes[t] - 1) - cost)
        prev = weights[t]
    return out


def _sharpe(r: list[float]) -> float:
    sd = pstdev(r) if len(r) > 2 else 0.0
    return mean(r) / sd * math.sqrt(365) if sd > 0 else 0.0


def _mdd(r: list[float]) -> float:
    eq = peak = 1.0
    worst = 0.0
    for x in r:
        eq *= 1 + x
        peak = max(peak, eq)
        worst = max(worst, 1 - eq / peak)
    return worst


def _cagr(r: list[float]) -> float:
    eq = 1.0
    for x in r:
        eq *= 1 + x
    return eq ** (365 / len(r)) - 1 if r and eq > 0 else -1.0


def _summary(r: list[float]) -> dict:
    return {"cagr": round(_cagr(r), 4), "sharpe": round(_sharpe(r), 3), "max_drawdown": round(_mdd(r), 3), "days": len(r)}


def core_trend_weights(closes: list[float]) -> list[float]:
    """The proposed BTC core book: hold BTC while it is above its 200-day average, sized to 50% annual volatility
    (30-day), never above 1x, skipping changes under 5 points unless the position switches on or off."""
    return rule_weights(closes, "sma", 200, vol_target=0.5, vol_days=30, band=0.05)


def test_rule(store: cp.MarketStore, spec: dict, n_trials: int = 1, boot: int = 300, seed: int = 11) -> dict:
    product = spec.get("product", "BTC-USD")
    rows = _closes(store, product, 1440)
    if len(rows) < 400:
        return {"note": "not enough daily history yet", "retry": True}
    ts = [t for t, _ in rows]
    c = [x for _, x in rows]
    try:
        w = rule_weights(c, spec.get("rule", "sma"), int(spec.get("days", 200)), spec.get("vol_target"),
                         int(spec.get("vol_days", 30)), float(spec.get("band", 0.0)))
    except ValueError as e:
        return {"note": str(e)}
    cost = float(spec.get("cost_bps", 85.0))
    warm = max(int(spec.get("days", 200)), int(spec.get("vol_days", 30)))
    net = rule_returns(c, w, cost)[warm:]
    hold = rule_returns(c, [1.0] * len(c), cost)[warm:]
    days = ts[warm + 1:]
    res: dict[str, Any] = {"rule": _summary(net), "hold": _summary(hold), "cost_bps": cost,
                           "time_in_market": round(mean(w[warm:-1]), 3)}
    for name, keep in (("to_2021", lambda d: d < SPLIT_TS), ("2022_on", lambda d: d >= SPLIT_TS), ("last_365d", None)):
        if keep is None:
            a, b = net[-365:], hold[-365:]
        else:
            a = [r for r, d in zip(net, days) if keep(d)]
            b = [r for r, d in zip(hold, days) if keep(d)]
        res[name] = {"rule": _summary(a), "hold": _summary(b)} if len(a) > 30 else None
    res["dsr"] = round(cp.deflated_sharpe(net, max(1, n_trials)), 3)
    rng = random.Random(seed)
    n = len(net)
    better_sharpe = smaller_dd = 0
    for _ in range(boot):                                       # stationary block bootstrap, mean block 20 days
        idx, i = [], rng.randrange(n)
        for _ in range(n):
            idx.append(i)
            i = rng.randrange(n) if rng.random() < 0.05 else (i + 1) % n
        a = [net[k] for k in idx]
        b = [hold[k] for k in idx]
        better_sharpe += _sharpe(a) > _sharpe(b)
        smaller_dd += _mdd(a) < _mdd(b)
    res["vs_hold"] = {"p_sharpe_better": round(better_sharpe / boot, 3), "p_drawdown_smaller": round(smaller_dd / boot, 3)}
    positive = res["dsr"] >= 0.95
    better = res["vs_hold"]["p_sharpe_better"] >= 0.95
    safer = res["vs_hold"]["p_drawdown_smaller"] >= 0.95
    res["supported"] = positive
    res["verdict"] = ("positive return beyond luck" if positive else "positive return not established") + "; " + \
                     ("beats holding on Sharpe" if better else "does not beat holding on Sharpe") + "; " + \
                     ("smaller drawdowns than holding" if safer else "drawdowns not reliably smaller")
    return res


# =================================================================================================================
# 3. Media, attention and on-chain features
# =================================================================================================================
def _daily(store: cp.MarketStore, source: str, metric: str) -> dict[int, float]:
    return {int(d): float(v) for d, v in store.db.execute(
        "SELECT ts, value FROM readings WHERE source=? AND metric=?", (source, metric)) if v is not None}


def _mean_window(s: dict[int, float], d: int, n: int, end_lag: int = 0) -> float | None:
    vals = [s[k] for k in range(d - end_lag - n + 1, d - end_lag + 1) if k in s]
    return mean(vals) if len(vals) >= max(1, int(0.7 * n)) else None


def _surprise(s: dict[int, float], d: int, short: int = 7, long: int = 28) -> float | None:
    a, b = _mean_window(s, d, short), _mean_window(s, d, long, end_lag=short)
    return math.log(a / b) if a and b and a > 0 and b > 0 else None


FEATURES: dict[str, str] = {
    "fear_greed": "Fear & Greed index level",
    "extreme_fear": "Fear & Greed below 25",
    "wiki_surprise": "Wikipedia 'Bitcoin' views, last 7 days vs the 28 before",
    "news_volume_surprise": "GDELT 'bitcoin' news volume, last 7 days vs the 28 before",
    "news_tone": "GDELT 'bitcoin' news tone, last 7 days minus the 28 before",
    "exchange_netflow_7d": "coins flowing into exchanges minus out, last 7 days, share of supply (whales selling?)",
    "exchange_balance_change_28d": "change in coins held on exchanges over 28 days, share of supply",
    "mvrv": "MVRV, market value over realized value (log)",
    "active_addresses_surprise": "active addresses, last 7 days vs the 90 before",
}


def feature_series(store: cp.MarketStore, name: str) -> Callable[[int], float | None]:
    """A function day -> feature value, using only data up to the day BEFORE (one-day lag)."""
    if name in ("fear_greed", "extreme_fear"):
        f = _daily(store, "attention", "fear_greed")
        if name == "fear_greed":
            return lambda d: f.get(d - 1)
        return lambda d: (1.0 if f[d - 1] < 25 else 0.0) if (d - 1) in f else None
    if name == "wiki_surprise":
        w = _daily(store, "attention", "wiki:Bitcoin")
        return lambda d: _surprise(w, d - 1)
    if name == "news_volume_surprise":
        g = _daily(store, "attention", "gdelt:bitcoin") or _daily(store, "attention", "gdelt:cryptocurrency")
        return lambda d: _surprise(g, d - 1)
    if name == "news_tone":
        g = _daily(store, "attention", "gdelt_tone:bitcoin")

        def tone(d: int) -> float | None:
            a, b = _mean_window(g, d - 1, 7), _mean_window(g, d - 1, 28, end_lag=7)
            return a - b if a is not None and b is not None else None
        return tone
    oc = {m: _daily(store, "onchain", f"cm:{m}") for m in ("FlowInExNtv", "FlowOutExNtv", "SplyExNtv", "SplyCur",
                                                            "CapMVRVCur", "AdrActCnt")}
    if name == "exchange_netflow_7d":
        def netflow(d: int) -> float | None:
            ks = range(d - 7, d)
            if not all(k in oc["FlowInExNtv"] and k in oc["FlowOutExNtv"] for k in ks) or (d - 1) not in oc["SplyCur"]:
                return None
            return sum(oc["FlowInExNtv"][k] - oc["FlowOutExNtv"][k] for k in ks) / oc["SplyCur"][d - 1]
        return netflow
    if name == "exchange_balance_change_28d":
        e, s = oc["SplyExNtv"], oc["SplyCur"]
        return lambda d: ((e[d - 1] - e[d - 29]) / s[d - 1]) if all(k in e for k in (d - 1, d - 29)) and (d - 1) in s else None
    if name == "mvrv":
        v = oc["CapMVRVCur"]
        return lambda d: math.log(v[d - 1]) if v.get(d - 1, 0) > 0 else None
    if name == "active_addresses_surprise":
        a = oc["AdrActCnt"]
        return lambda d: _surprise(a, d - 1, 7, 90)
    raise ValueError(f"unknown feature {name!r}; known: {sorted(FEATURES)}")


def test_feature(store: cp.MarketStore, spec: dict, perms: int = 300, seed: int = 5) -> dict:
    target = spec.get("target", "return7")
    if target not in ("return7", "return28", "vol7"):
        return {"note": f"unknown target {target!r} (return7, return28, vol7)"}
    try:
        f = feature_series(store, spec["feature"])
    except (KeyError, ValueError) as e:
        return {"note": str(e)}
    rows = _closes(store, spec.get("product", "BTC-USD"), 1440)
    px = {t // DAY: c for t, c in rows}
    if len(px) < 500:
        return {"note": "not enough daily history yet", "retry": True}
    d0, d1 = min(px), max(px)
    h = 28 if target == "return28" else 7
    absr = {d: abs(math.log(px[d] / px[d - 1])) for d in px if d - 1 in px}
    pts = []
    for d in range(d0 + 120, d1 - h + 1, h):                         # non-overlapping decision days
        x = f(d)
        if x is None or d not in px or (d + h) not in px:
            continue
        if target == "vol7":
            fwd = [absr.get(k) for k in range(d + 1, d + 8)]
            past7 = [absr.get(k) for k in range(d - 6, d + 1)]
            past28 = [absr.get(k) for k in range(d - 27, d + 1)]
            if None in fwd or None in past7 or None in past28:
                continue
            pts.append((d, x, sum(fwd), sum(past7), sum(past28)))
        else:
            pts.append((d, x, math.log(px[d + h] / px[d]), 0.0, 0.0))
    if len(pts) < 30:
        return {"note": "no data for this feature yet (it arrives with the attention and on-chain backfill)", "retry": True}
    split = int(SPLIT_TS // DAY)
    rng = random.Random(seed)
    res: dict[str, Any] = {"feature": FEATURES.get(spec["feature"], spec["feature"]), "target": target,
                           "controls": "today's 7- and 28-day volatility" if target == "vol7" else None}
    for name, keep in (("to_2021", lambda d: d < split), ("2022_on", lambda d: d >= split), ("full", lambda d: True)):
        sub = [p for p in pts if keep(p[0])]
        if len(sub) < 30:
            res[name] = None
            continue
        xs, ys = _ranks([p[1] for p in sub]), _ranks([p[2] for p in sub])
        if target == "vol7":
            ctrl = [_ranks([p[3] for p in sub]), _ranks([p[4] for p in sub])]
            xs, ys = _residualize(xs, ctrl), _residualize(ys, ctrl)
        ic = _pearson(xs, ys)
        null = []
        for _ in range(perms):
            yy = ys[:]
            rng.shuffle(yy)
            null.append(_pearson(xs, yy))
        sd = pstdev(null)
        res[name] = {"n": len(sub), "ic": round(ic, 3), "z": round(ic / sd, 2) if sd > 0 else 0.0}
    a, b = res.get("to_2021"), res.get("2022_on")
    ok = bool(a and b and abs(a["z"]) >= 2 and abs(b["z"]) >= 2 and (a["ic"] > 0) == (b["ic"] > 0))
    res["supported"] = ok
    res["verdict"] = "supported in both periods" if ok else "not supported (fails a period)"
    return res


# =================================================================================================================
def test_hypothesis(store: cp.MarketStore, spec: dict, n_trials: int = 1, perms: int = 300) -> dict:
    """v0.5 kinds (calendar, cycle) plus the v0.5.1 kinds (level, rule, feature)."""
    kind = spec.get("type")
    if kind == "level":
        return test_level(store, spec)
    if kind == "rule":
        return test_rule(store, spec, n_trials=n_trials)
    if kind == "feature":
        return test_feature(store, spec, perms=perms)
    return rv.test_hypothesis(store, spec, perms=perms)
