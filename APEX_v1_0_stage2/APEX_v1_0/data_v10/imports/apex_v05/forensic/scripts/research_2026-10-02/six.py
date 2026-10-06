"""Owner hypothesis test: are there '6' cycles (6th hour, 6th day, 6-month) in BTC/ETH returns? Real Coinbase data.
Each family is tested with a permutation max-|t| test (family-wise p-value) and an out-of-sample split."""
import json, math, random, datetime as dt
from statistics import mean, pstdev

def series(prod, gran):
    rows = json.load(open(f"{prod}_{gran}.json"))
    out = []
    for (t0, *_a, c0, _v0), (t1, *_b, c1, _v1) in zip(rows, rows[1:]):
        if t1 - t0 == gran and c0 > 0:
            out.append((t1 - gran, math.log(c1 / c0)))     # return over the bar that starts at t0
    return out

def tstat(xs, ys):
    if len(xs) < 3 or len(ys) < 3: return 0.0
    m1, m2, s1, s2 = mean(xs), mean(ys), pstdev(xs), pstdev(ys)
    return (m1 - m2) / math.sqrt(s1 ** 2 / len(xs) + s2 ** 2 / len(ys) + 1e-30)

def family(data, label, target_label, value=lambda r: r, perms=300, seed=1):
    labs = [label(t) for t, _ in data]; vals = [value(r) for _, r in data]
    uniq = sorted(set(labs)); idx = {l: i for i, l in enumerate(uniq)}; li = [idx[l] for l in labs]
    k = len(uniq); N = len(vals); TS = sum(vals); TQ = sum(v * v for v in vals)
    def stats(vs):
        s = [0.0] * k; q = [0.0] * k; n = [0] * k
        for i, v in zip(li, vs):
            s[i] += v; q[i] += v * v; n[i] += 1
        out = []
        for j in range(k):
            a_n, b_n = n[j], N - n[j]
            if a_n < 3 or b_n < 3: out.append(0.0); continue
            ma, mb = s[j] / a_n, (TS - s[j]) / b_n
            va = q[j] / a_n - ma * ma; vb = (TQ - q[j]) / b_n - mb * mb
            out.append((ma - mb) / math.sqrt(max(va, 0) / a_n + max(vb, 0) / b_n + 1e-30))
        return out
    obs = stats(vals)
    rng = random.Random(seed); vs = list(vals); maxes = []
    for _ in range(perms):
        rng.shuffle(vs)
        maxes.append(max(abs(x) for x in stats(vs)))
    t6 = obs[idx[target_label]] if target_label in idx else 0.0
    best = max(range(k), key=lambda j: abs(obs[j]))
    return {"t_for_6": round(t6, 2), "familywise_p_for_6": round(sum(1 for m in maxes if m >= abs(t6)) / perms, 3),
            "strongest_label": uniq[best], "strongest_t": round(obs[best], 2),
            "strongest_familywise_p": round(sum(1 for m in maxes if m >= abs(obs[best])) / perms, 3), "labels": k}

utc = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc)
res = {}
for prod in ("BTC-USD", "ETH-USD"):
    h = series(prod, 3600); d = series(prod, 86400)
    split_h = [x for x in h if utc(x[0]).year <= 2021], [x for x in h if utc(x[0]).year >= 2022]
    split_d = [x for x in d if utc(x[0]).year <= 2021], [x for x in d if utc(x[0]).year >= 2022]
    for name, part in (("2017-2021", 0), ("2022-2026", 1)):
        res[f"{prod} hour-of-day return, {name}"] = family(split_h[part], lambda t: utc(t).hour, 6)
        res[f"{prod} hour-of-day |return|, {name}"] = family(split_h[part], lambda t: utc(t).hour, 6, value=abs)
        res[f"{prod} day-of-month return, {name}"] = family(split_d[part], lambda t: utc(t).day, 6)
        res[f"{prod} day-of-week return (Mon=1, 6=Sat), {name}"] = family(split_d[part], lambda t: utc(t).isoweekday(), 6)
    # 6-month cycle: autocorrelation of monthly log returns at lag 6
    months = {}
    for t, r in d:
        k = (utc(t).year, utc(t).month); months[k] = months.get(k, 0.0) + r
    m = [months[k] for k in sorted(months)]
    mu = mean(m); var = sum((x - mu) ** 2 for x in m)
    ac = {lag: sum((m[i] - mu) * (m[i - lag] - mu) for i in range(lag, len(m))) / var for lag in range(1, 13)}
    res[f"{prod} monthly autocorrelation"] = {"lag6": round(ac[6], 3), "band_95pct": round(1.96 / math.sqrt(len(m)), 3),
                                              "largest_lag": max(ac, key=lambda k: abs(ac[k])), "largest": round(max(ac.values(), key=abs), 3),
                                              "months": len(m)}
for k, v in res.items():
    print(k, json.dumps(v))
json.dump(res, open("six.json", "w"), indent=1)
