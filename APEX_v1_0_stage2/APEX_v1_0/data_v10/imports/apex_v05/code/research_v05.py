"""v0.5 research engine: many weak signals, one combined model, costs inside the decision, and a running
evidence record instead of a pass/fail gate (owner decision 3, 2 Oct 2026).

  Panel           daily closes and volumes for the universe, aligned by UTC day
  Signal factory  weak cross-sectional signals scored per coin per rebalance day, using data up to that day only
  Combined model  ridge regression on all signals at once (the "one model" idea), refit on an expanding window
                  with a purge so no training label overlaps the decision date
  Portfolio       long-short (perpetual-futures venue) and long-only (spot venue) books, volatility-targeted,
                  with a no-trade band and venue costs charged on turnover
  Evidence        every trial is logged; each carries a deflated Sharpe that counts ALL trials so far, and the
                  family carries a probability of backtest overfitting (CSCV). No gate stops the loop; the evidence
                  is a number that grows or decays, and only real money needs the owner.
  Hypotheses      owner hypotheses (e.g. calendar cycles) are registered before they are tested, then counted.

Research outputs only; nothing here is financial advice.
"""
from __future__ import annotations
import datetime as dt
import hashlib, itertools, json, math, random
from dataclasses import dataclass, field
from statistics import NormalDist, mean, pstdev
from typing import Any, Callable
from . import crypto_pack as cp
from .v04_math import mat_inv
from .data_v05 import iso_day

HORIZON = 7                    # days held between rebalances
VENUES = {"perps_long_short": {"cost_bps": 6.0, "long_short": True},      # ~2-4 bps a side plus spread (US perps)
          "spot_long_only": {"cost_bps": 85.0, "long_short": False}}      # Kraken Pro tier-1 taker 0.80% + slippage


# --- panel ---------------------------------------------------------------------------------------------------

@dataclass
class Panel:
    days: list[int]
    products: list[str]
    close: dict[str, list[float | None]]
    volume: dict[str, list[float | None]]

    @classmethod
    def from_store(cls, store: cp.MarketStore, products: list[str] | None = None, source: str = "coinbase",
                   interval: int = 1440) -> "Panel":
        q = "SELECT pair, ts, close, volume FROM candles WHERE source=? AND interval=?"
        data: dict[str, dict[int, tuple[float, float]]] = {}
        for pair, ts, c, v in store.db.execute(q, (source, interval)):
            if products is None or pair in products:
                data.setdefault(pair, {})[int(ts // 86400)] = (c, v)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, dict[int, tuple[float, float]]]) -> "Panel":
        if not data:
            return cls([], [], {}, {})
        lo = min(min(d) for d in data.values()); hi = max(max(d) for d in data.values())
        days = list(range(lo, hi + 1))
        prods = sorted(data)
        close = {p: [data[p].get(d, (None, None))[0] for d in days] for p in prods}
        vol = {p: [data[p].get(d, (None, None))[1] for d in days] for p in prods}
        return cls(days, prods, close, vol)

    def logp(self, p: str) -> list[float | None]:
        return [math.log(c) if c and c > 0 else None for c in self.close[p]]


def _window(xs: list, i: int, n: int) -> list | None:
    if i - n + 1 < 0:
        return None
    w = xs[i - n + 1:i + 1]
    return None if any(x is None for x in w) else w


def _rets(lp: list[float | None]) -> list[float | None]:
    return [None] + [b - a if a is not None and b is not None else None for a, b in zip(lp, lp[1:])]


# --- signal factory -----------------------------------------------------------------------------------------

def _edm_simplex(wk: list[float | None], i_week: int, E: int = 3, min_lib: int = 30) -> float | None:
    """Empirical dynamic modelling: embed weekly returns in E dimensions (Takens), find the E+1 nearest past
    states, and forecast next week's return as their exponentially weighted outcome (simplex projection)."""
    def state(j: int):
        w = wk[j - E + 1:j + 1] if j - E + 1 >= 0 else None
        return None if w is None or any(x is None for x in w) else w
    x = state(i_week)
    if x is None:
        return None
    lib = []
    for j in range(E - 1, i_week - 1):              # the outcome wk[j+1] must be known by i_week
        s = state(j)
        if s is not None and wk[j + 1] is not None:
            lib.append((math.dist(s, x), wk[j + 1]))
    if len(lib) < min_lib:
        return None
    lib.sort(key=lambda t: t[0])
    nn = lib[:E + 1]
    d0 = nn[0][0] or 1e-12
    ws = [math.exp(-d / d0) for d, _ in nn]
    return sum(w * y for w, (_, y) in zip(ws, nn)) / sum(ws)


SIGNALS = ("mom3", "mom7", "mom14", "mom28", "mom56", "rev1", "lowvol28", "trend50", "maxret7", "volz28",
           "lowbeta60", "edm_simplex")


def compute_signals(panel: Panel, rebal: list[int]) -> dict[str, dict[str, dict[int, float]]]:
    """signal -> product -> rebalance index -> raw score (data up to and including that day only)."""
    out = {s: {p: {} for p in panel.products} for s in SIGNALS}
    btc = panel.logp("BTC-USD") if "BTC-USD" in panel.products else None
    rb = _rets(btc) if btc else None
    for p in panel.products:
        lp = panel.logp(p)
        r = _rets(lp)
        vol = panel.volume[p]
        wk = [None] * len(rebal)                     # weekly log returns ending at each rebalance day
        for k, i in enumerate(rebal):
            if i - HORIZON >= 0 and lp[i] is not None and lp[i - HORIZON] is not None:
                wk[k] = lp[i] - lp[i - HORIZON]
        for k, i in enumerate(rebal):
            if lp[i] is None:
                continue
            for n in (3, 7, 14, 28, 56):
                if i - n >= 0 and lp[i - n] is not None:
                    out[f"mom{n}"][p][i] = lp[i] - lp[i - n]
            if r[i] is not None:
                out["rev1"][p][i] = -r[i]
            w = _window(r, i, 28)
            if w:
                out["lowvol28"][p][i] = -pstdev(w)
            w = _window(panel.close[p], i, 50)
            if w:
                out["trend50"][p][i] = lp[i] - math.log(sum(w) / 50)
            w = _window(r, i, 7)
            if w:
                out["maxret7"][p][i] = -max(w)
            w7, w28 = _window(vol, i, 7), _window(vol, i, 28)
            if w7 and w28 and sum(w7) > 0 and sum(w28) > 0:
                out["volz28"][p][i] = math.log(sum(w7) / 7) - math.log(sum(w28) / 28)
            if rb is not None:
                a, b = _window(r, i, 60), _window(rb, i, 60)
                if a and b:
                    mb = mean(b); vb = sum((x - mb) ** 2 for x in b)
                    if vb > 0:
                        out["lowbeta60"][p][i] = -sum((x - mean(a)) * (y - mb) for x, y in zip(a, b)) / vb
            f = _edm_simplex(wk, k)
            if f is not None:
                out["edm_simplex"][p][i] = f
    return out


def forward_returns(panel: Panel, rebal: list[int]) -> dict[str, dict[int, float]]:
    out = {p: {} for p in panel.products}
    for p in panel.products:
        lp = panel.logp(p)
        for i in rebal:
            if i + HORIZON < len(lp) and lp[i] is not None and lp[i + HORIZON] is not None:
                out[p][i] = lp[i + HORIZON] - lp[i]
    return out


def _zscores(vals: dict[str, float]) -> dict[str, float]:
    if len(vals) < 3:
        return {}
    m, s = mean(vals.values()), pstdev(vals.values())
    return {k: (v - m) / s for k, v in vals.items()} if s > 0 else {}


def _ranks(vals: dict[str, float]) -> dict[str, float]:
    order = sorted(vals, key=vals.get)
    return {k: i for i, k in enumerate(order)}


def spearman(a: dict[str, float], b: dict[str, float]) -> float | None:
    keys = [k for k in a if k in b]
    if len(keys) < 6:
        return None
    ra, rb = _ranks({k: a[k] for k in keys}), _ranks({k: b[k] for k in keys})
    n = len(keys)
    d2 = sum((ra[k] - rb[k]) ** 2 for k in keys)
    return 1 - 6 * d2 / (n * (n * n - 1))


# --- portfolio ------------------------------------------------------------------------------------------------

@dataclass
class BookConfig:
    cost_bps: float
    long_short: bool
    target_vol: float = 0.10
    max_gross: float = 1.0
    band: float = 0.01


MIN_PRODUCTS = 6


def weights_from_scores(scores: dict[str, float], long_short: bool) -> dict[str, float]:
    if len(scores) < MIN_PRODUCTS:            # too few coins for a cross-section: stay flat
        return {}
    z = _zscores(scores)
    if not z:
        return {}
    if long_short:
        g = sum(abs(v) for v in z.values())
        return {k: v / g for k, v in z.items()} if g else {}
    pos = {k: v for k, v in z.items() if v > 0}
    g = sum(pos.values())
    return {k: v / g for k, v in pos.items()} if g else {}


def run_book(score_by_date: dict[int, dict[str, float]], fwd: dict[str, dict[int, float]], rebal: list[int],
             cfg: BookConfig) -> dict:
    """Weekly book: target weights from scores, volatility-scaled from the book's own past, no-trade band,
    costs on turnover. Returns weekly net returns aligned with `rebal` (None where no position was possible)."""
    cost = cfg.cost_bps / 1e4
    prev: dict[str, float] = {}
    raw_hist: list[float] = []
    net: list[float | None] = []
    gross_ret: list[float | None] = []
    turn_total = 0.0
    for i in rebal:
        scores = score_by_date.get(i, {})
        tradable = {p: s for p, s in scores.items() if i in fwd.get(p, {})}
        w = weights_from_scores(tradable, cfg.long_short)
        if not w:
            net.append(None); gross_ret.append(None)
            continue
        est = pstdev(raw_hist[-12:]) * math.sqrt(52) if len(raw_hist) >= 6 else None
        scale = min(cfg.max_gross, cfg.target_vol / est) if est else 0.5 * cfg.max_gross
        target = {p: v * scale for p, v in w.items()}
        new = dict(prev)
        for p in set(target) | set(prev):
            t, o = target.get(p, 0.0), prev.get(p, 0.0)
            if abs(t - o) >= cfg.band or t == 0.0:
                new[p] = t
        new = {p: v for p, v in new.items() if abs(v) > 1e-12 and p in tradable}
        turnover = sum(abs(new.get(p, 0.0) - prev.get(p, 0.0)) for p in set(new) | set(prev))
        g = sum(v * (math.exp(fwd[p][i]) - 1) for p, v in new.items())
        raw = sum(v * (math.exp(fwd[p][i]) - 1) for p, v in w.items())
        raw_hist.append(raw)
        net.append(g - turnover * cost)
        gross_ret.append(g)
        turn_total += turnover
        prev = new
    valid = [x for x in net if x is not None]
    eq, curve = 1.0, [1.0]
    for x in valid:
        eq *= 1 + x
        curve.append(eq)
    return {"weekly": net, "gross": gross_ret, "sharpe": cp.sharpe(valid, 52.0),
            "gross_sharpe": cp.sharpe([x for x in gross_ret if x is not None], 52.0), "return": eq - 1,
            "max_drawdown": cp.max_drawdown(curve), "weeks": len(valid),
            "turnover_per_year": turn_total / max(1e-9, len(valid) / 52.0), "last_weights": prev}


# --- the combined model --------------------------------------------------------------------------------------

def ridge_fit(X: list[list[float]], y: list[float], lam: float) -> list[float]:
    k = len(X[0])
    xtx = [[sum(r[a] * r[b] for r in X) + (lam if a == b else 0.0) for b in range(k)] for a in range(k)]
    xty = [sum(r[a] * t for r, t in zip(X, y)) for a in range(k)]
    inv = mat_inv(xtx)
    return [sum(inv[a][b] * xty[b] for b in range(k)) for a in range(k)]


def combined_scores(sigs: dict[str, dict[str, dict[int, float]]], fwd: dict[str, dict[int, float]], rebal: list[int],
                    names: tuple[str, ...] = SIGNALS, lam: float = 50.0, min_train: int = 52, refit_every: int = 4
                    ) -> tuple[dict[int, dict[str, float]], list[dict]]:
    """Expanding-window ridge on cross-sectional z-scores; a sample dated j trains a decision at i only if its
    label window has closed (j + HORIZON <= i). Missing signals count as 0 (the cross-sectional mean)."""
    z_by_date: dict[int, dict[str, list[float]]] = {}
    for i in rebal:
        zs = {n: _zscores({p: v[i] for p, v in sigs[n].items() if i in v}) for n in names}
        prods = set().union(*[set(z) for z in zs.values()]) if zs else set()
        z_by_date[i] = {p: [zs[n].get(p, 0.0) for n in names] for p in prods}
    out: dict[int, dict[str, float]] = {}
    fits: list[dict] = []
    beta = None
    nf = len(names)
    xtx = [[0.0] * nf for _ in range(nf)]
    xty = [0.0] * nf
    n_samples, added = 0, 0                     # rebal[:added] are already in the running sums
    for k, i in enumerate(rebal):
        while added < k and rebal[added] + HORIZON <= i:      # labels that have closed by day i
            j = rebal[added]
            f = {p: fwd[p][j] for p in z_by_date[j] if j in fwd.get(p, {})}
            if len(f) >= 6:
                m = mean(f.values())
                for p, x in z_by_date[j].items():
                    if p in f:
                        t = f[p] - m
                        for a in range(nf):
                            xty[a] += x[a] * t
                            row = xtx[a]
                            for b in range(nf):
                                row[b] += x[a] * x[b]
                        n_samples += 1
            added += 1
        if k >= min_train and (beta is None or k % refit_every == 0) and n_samples > 5 * nf:
            inv = mat_inv([[xtx[a][b] + (lam if a == b else 0.0) for b in range(nf)] for a in range(nf)])
            beta = [sum(inv[a][b] * xty[b] for b in range(nf)) for a in range(nf)]
            fits.append({"at": i, "samples": n_samples, "beta": [round(b, 5) for b in beta]})
        if beta is not None:
            out[i] = {p: sum(b * x for b, x in zip(beta, xs)) for p, xs in z_by_date[i].items()}
    return out, fits


# --- evidence: deflated Sharpe over all trials, and the probability of backtest overfitting -----------------------

def pbo_cscv(matrix: list[list[float]], blocks: int = 8) -> float | None:
    """Bailey-Borwein-Lopez de Prado-Zhu CSCV. matrix: rows = periods, columns = trials (aligned, no gaps).
    Returns the share of splits where the in-sample winner ranks below the out-of-sample median."""
    T = len(matrix)
    if T < blocks * 4 or not matrix or len(matrix[0]) < 2:
        return None
    N = len(matrix[0])
    size = T // blocks
    parts = [matrix[b * size:(b + 1) * size] for b in range(blocks)]

    def sr(rows: list[list[float]], j: int) -> float:
        xs = [r[j] for r in rows]
        s = pstdev(xs)
        return mean(xs) / s if s else 0.0
    below = total = 0
    for combo in itertools.combinations(range(blocks), blocks // 2):
        ins = [r for b in combo for r in parts[b]]
        oos = [r for b in range(blocks) if b not in combo for r in parts[b]]
        is_sr = [sr(ins, j) for j in range(N)]
        best = max(range(N), key=lambda j: is_sr[j])
        oos_sr = [sr(oos, j) for j in range(N)]
        rank = sum(1 for j in range(N) if oos_sr[j] < oos_sr[best]) + 1
        omega = rank / (N + 1)
        below += math.log(omega / (1 - omega)) <= 0
        total += 1
    return below / total


@dataclass
class Trial:
    name: str
    kind: str                       # signal | model | hypothesis | volatility
    weekly: list[float | None]
    metrics: dict = field(default_factory=dict)


def evidence_table(trials: list[Trial], prior_trials: int = 0) -> dict:
    """Continuous evidence for every trial: DSR counts every trial ever run (prior + now); the family's PBO is
    shared. evidence = DSR x (1 - PBO). Nothing passes or fails here; the numbers rise or decay."""
    n_total = prior_trials + len(trials)
    cand = [t for t in trials if t.kind in ("signal", "model")]
    longest = max((sum(1 for x in t.weekly if x is not None) for t in cand), default=0)
    cols = [t for t in cand if sum(1 for x in t.weekly if x is not None) >= 0.5 * longest > 0]   # skip empty trials
    idx = [k for k in range(len(cols[0].weekly))] if cols else []
    common = [k for k in idx if all(t.weekly[k] is not None for t in cols)]
    matrix = [[t.weekly[k] for t in cols] for k in common]
    pbo = pbo_cscv(matrix) if len(cols) >= 2 else None
    rows = {}
    for t in trials:
        valid = [x for x in t.weekly if x is not None]
        dsr = cp.deflated_sharpe(valid, n_total) if len(valid) > 10 else 0.0
        rows[t.name] = {"kind": t.kind, "weeks": len(valid), "sharpe": round(cp.sharpe(valid, 52.0), 3),
                        "psr": round(cp.probabilistic_sharpe(valid), 3), "dsr": round(dsr, 3),
                        "evidence": round(dsr * (1 - (pbo if pbo is not None else 0.5)), 3), **t.metrics}
    return {"trials_counted": n_total, "pbo_family": None if pbo is None else round(pbo, 3), "rows": rows}


def run_research(panel: Panel, prior_trials: int = 0, venues: dict = VENUES, min_train: int = 52) -> dict:
    """One research pass: every single-signal book and the combined model, on both venues, with evidence."""
    start, last = 70, len(panel.days) - 1
    if last < start + HORIZON:
        return {"note": "not enough history", "trials": [], "evidence": {"rows": {}, "trials_counted": prior_trials}}
    rebal = list(range(last - HORIZON * ((last - start) // HORIZON), last + 1, HORIZON))   # grid ends today
    sigs = compute_signals(panel, rebal)
    fwd = forward_returns(panel, rebal)
    trials: list[Trial] = []
    ic_summary = {}
    for n in SIGNALS:
        ics = [x for x in (spearman({p: v[i] for p, v in sigs[n].items() if i in v},
                                    {p: f[i] for p, f in fwd.items() if i in f}) for i in rebal) if x is not None]
        icm = mean(ics) if ics else 0.0
        ict = icm / (pstdev(ics) / math.sqrt(len(ics))) if len(ics) > 2 and pstdev(ics) > 0 else 0.0
        ic_summary[n] = {"ic_mean": round(icm, 4), "ic_t": round(ict, 2), "dates": len(ics)}
        by_date = {i: {p: v[i] for p, v in sigs[n].items() if i in v} for i in rebal}
        book = run_book(by_date, fwd, rebal, BookConfig(**venues["perps_long_short"]))
        trials.append(Trial(f"signal:{n}", "signal", book["weekly"], {"ic_mean": round(icm, 4), "ic_t": round(ict, 2)}))
    scores, fits = combined_scores(sigs, fwd, rebal, min_train=min_train)
    books = {}
    for v, spec in venues.items():
        book = run_book(scores, fwd, rebal, BookConfig(**spec))
        books[v] = book
        trials.append(Trial(f"model:combined:{v}", "model", book["weekly"],
                            {"gross_sharpe": round(book["gross_sharpe"], 3), "max_drawdown": round(book["max_drawdown"], 3),
                             "turnover_per_year": round(book["turnover_per_year"], 2)}))
    # Benchmarks on the same weeks (not trials): equal-weight basket and BTC held.
    ew = []
    for i in rebal:
        f = [math.exp(fw[i]) - 1 for fw in fwd.values() if i in fw]
        ew.append(mean(f) if len(f) >= 6 else None)
    btc = [math.exp(fwd["BTC-USD"][i]) - 1 if i in fwd.get("BTC-USD", {}) else None for i in rebal]
    ev = evidence_table(trials, prior_trials)
    latest = rebal[-1] if rebal else None
    scale_now = {}
    for v, b in books.items():
        raw = [x for x in b["gross"] if x is not None][-12:]
        est = pstdev(raw) * math.sqrt(52) if len(raw) >= 6 else None
        scale_now[v] = round(min(1.0, 0.10 / est), 4) if est else 0.5
    return {"rebalances": len(rebal), "first_day": iso_day(panel.days[rebal[0]]) if rebal else None,
            "last_day": iso_day(panel.days[rebal[-1]]) if rebal else None, "products": len(panel.products),
            "ic": ic_summary, "evidence": ev,
            "books": {v: {k: (round(b[k], 3) if isinstance(b[k], float) else b[k]) for k in
                          ("sharpe", "gross_sharpe", "return", "max_drawdown", "weeks", "turnover_per_year")} for v, b in books.items()},
            "benchmarks": {"equal_weight_hold_sharpe": round(cp.sharpe([x for x in ew if x is not None], 52.0), 3),
                           "btc_hold_sharpe": round(cp.sharpe([x for x in btc if x is not None], 52.0), 3)},
            "model_fits": len(fits), "last_beta": dict(zip(SIGNALS, fits[-1]["beta"])) if fits else {},
            "latest_scores": scores.get(latest, {}), "latest_day": iso_day(panel.days[latest]) if latest is not None else None,
            "scale_now": scale_now, "trials": trials}


# --- volatility: does attention add to a HAR model? --------------------------------------------------------------

def attention_volatility_test(panel: Panel, attention: dict[str, dict[int, float]], product: str = "BTC-USD",
                              min_train: int = 104) -> dict:
    """Weekly: log next-week realized vol ~ HAR (last week, last 4 weeks) [+ abnormal attention]. Expanding-window
    out-of-sample forecasts; reports the loss reduction and a Diebold-Mariano style t-statistic."""
    if product not in panel.products:
        return {"note": "no data"}
    r = _rets(panel.logp(product))
    days = panel.days
    rv = lambda a, b: math.log(math.sqrt(sum(x * x for x in r[a:b] if x is not None) + 1e-12))

    def abn(series: dict[int, float], d: int) -> float | None:
        w7 = [series.get(days[d] - k) for k in range(7)]
        w28 = [series.get(days[d] - k) for k in range(28)]
        if any(x is None or x <= 0 for x in w7 + w28):
            return None
        return math.log(sum(w7) / 7) - math.log(sum(w28) / 28)
    rows = []
    for i in range(35, len(days) - 7, 7):
        if any(x is None for x in r[i - 27:i + 8]):
            continue
        att = [abn(s, i) for s in attention.values()]
        rows.append((rv(i + 1, i + 8), [1.0, rv(i - 6, i + 1), rv(i - 27, i + 1)], att))
    if len(rows) < min_train + 20:
        return {"note": f"{len(rows)} weeks; not enough"}
    l0, l1 = [], []
    for k in range(min_train, len(rows)):
        y, base, att = rows[k]
        train = [r_ for r_ in rows[:k - 1]]
        b0 = ridge_fit([x for _, x, _ in train], [t for t, _, _ in train], 1e-6)
        e0 = (y - sum(b * x for b, x in zip(b0, base))) ** 2
        tr1 = [(t, x + [a or 0.0 for a in at]) for t, x, at in train]
        b1 = ridge_fit([x for _, x in tr1], [t for t, _ in tr1], 1e-3)
        e1 = (y - sum(b * x for b, x in zip(b1, base + [a or 0.0 for a in att]))) ** 2
        l0.append(e0); l1.append(e1)
    d = [a - b for a, b in zip(l0, l1)]
    dm = mean(d) / (pstdev(d) / math.sqrt(len(d))) if pstdev(d) > 0 else 0.0
    return {"weeks_tested": len(d), "loss_har": round(mean(l0), 4), "loss_har_attention": round(mean(l1), 4),
            "improvement_pct": round(100 * (1 - mean(l1) / mean(l0)), 2), "dm_t": round(dm, 2),
            "attention_series": list(attention)}


# --- owner hypotheses -----------------------------------------------------------------------------------------------

def hypothesis_id(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:12]


def _calendar_family(data: list[tuple[int, float]], label: Callable[[int], int], target: int, perms: int, seed: int) -> dict:
    labs = [label(t) for t, _ in data]; vals = [v for _, v in data]
    uniq = sorted(set(labs)); idx = {l: i for i, l in enumerate(uniq)}; li = [idx[l] for l in labs]
    k, N = len(uniq), len(vals)
    TS, TQ = sum(vals), sum(v * v for v in vals)

    def stats(vs: list[float]) -> list[float]:
        s = [0.0] * k; q = [0.0] * k; n = [0] * k
        for i, v in zip(li, vs):
            s[i] += v; q[i] += v * v; n[i] += 1
        out = []
        for j in range(k):
            a, b = n[j], N - n[j]
            if a < 3 or b < 3:
                out.append(0.0); continue
            ma, mb = s[j] / a, (TS - s[j]) / b
            va, vb = q[j] / a - ma * ma, (TQ - q[j]) / b - mb * mb
            out.append((ma - mb) / math.sqrt(max(va, 0) / a + max(vb, 0) / b + 1e-30))
        return out
    obs = stats(vals)
    rng = random.Random(seed); vs = list(vals); maxes = []
    for _ in range(perms):
        rng.shuffle(vs)
        maxes.append(max(abs(x) for x in stats(vs)))
    t = obs[idx[target]] if target in idx else 0.0
    return {"t": round(t, 2), "familywise_p": round(sum(1 for m in maxes if m >= abs(t)) / perms, 3), "labels": k, "n": N}


CAL_UNITS = {"hour": lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).hour,
             "weekday": lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).isoweekday(),
             "monthday": lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).day,
             "month": lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).month}


def test_hypothesis(store: cp.MarketStore, spec: dict, perms: int = 300, split_year: int = 2022) -> dict:
    """Supported: {"type": "calendar", "unit": hour|weekday|monthday|month, "value": 6, "product": "BTC-USD",
    "measure": "return"|"abs_return"}; {"type": "cycle", "months": 6, "product": "BTC-USD"}.
    Calendar effects are tested in two periods (before / from `split_year`); a real effect must hold in both."""
    product = spec.get("product", "BTC-USD")
    if spec["type"] == "calendar":
        interval = 60 if spec["unit"] == "hour" else 1440
        rows = store.db.execute("SELECT ts, close FROM candles WHERE source='coinbase' AND pair=? AND interval=? ORDER BY ts",
                                (product, interval)).fetchall()
        step = interval * 60
        # A candle's return is its close over the previous close; it belongs to the candle's own start time.
        data = [(t1, math.log(c1 / c0)) for (t0, c0), (t1, c1) in zip(rows, rows[1:]) if t1 - t0 == step and c0 > 0]
        if spec.get("measure") == "abs_return":
            data = [(t, abs(r)) for t, r in data]
        lab = CAL_UNITS[spec["unit"]]
        cut = dt.datetime(split_year, 1, 1, tzinfo=dt.timezone.utc).timestamp()
        a = _calendar_family([x for x in data if x[0] < cut], lab, int(spec["value"]), perms, 1)
        b = _calendar_family([x for x in data if x[0] >= cut], lab, int(spec["value"]), perms, 2)
        holds = a["familywise_p"] < 0.05 and b["familywise_p"] < 0.05 and (a["t"] > 0) == (b["t"] > 0)
        return {"before": a, "after": b, "supported": holds,
                "verdict": "supported in both periods" if holds else "not supported (fails a period or the multiple-testing check)"}
    if spec["type"] == "cycle":
        rows = store.db.execute("SELECT ts, close FROM candles WHERE source='coinbase' AND pair=? AND interval=1440 ORDER BY ts",
                                (product,)).fetchall()
        months: dict[tuple, list[float]] = {}
        for t, c in rows:
            d = dt.datetime.fromtimestamp(t, dt.timezone.utc)
            months.setdefault((d.year, d.month), []).append(c)
        m = [math.log(v[-1] / v[0]) for k, v in sorted(months.items()) if len(v) > 20 and v[0] > 0]
        lag = int(spec["months"])
        if len(m) < 3 * lag:
            return {"note": "not enough months"}
        mu = mean(m); var = sum((x - mu) ** 2 for x in m)
        ac = sum((m[i] - mu) * (m[i - lag] - mu) for i in range(lag, len(m))) / var
        band = 1.96 / math.sqrt(len(m))
        return {"autocorrelation": round(ac, 3), "noise_band_95": round(band, 3), "months": len(m),
                "supported": abs(ac) > band, "verdict": "outside the noise band" if abs(ac) > band else "inside the noise band"}
    return {"note": f"type {spec['type']!r} is not supported yet (events need event data: v0.6)"}
