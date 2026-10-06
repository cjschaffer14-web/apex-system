"""A fake public web for tests: Coinbase candles, Wikimedia, GDELT, Fear & Greed, Kraken funding (synthetic)."""
import json, math, random, datetime as dt
from urllib.parse import urlsplit, parse_qs

def price(prod, ts):
    seed = sum(map(ord, prod))
    day = ts / 86400
    base = 50 + seed % 200
    trend = 0.0004 * day * (1 + (seed % 5) / 5)
    wave = 0.3 * math.sin(day / (20 + seed % 30) + seed)
    noise = random.Random(int(ts) * 7 + seed).gauss(0, 0.02)
    return base * math.exp(trend + wave + noise)

def opener(url, headers, timeout, start_day=16000, calls=None):
    if calls is not None:
        calls.append(url)
    u = urlsplit(url); q = {k: v[0] for k, v in parse_qs(u.query).items()}
    if u.netloc == "api.coinbase.com":
        prod = u.path.split("/")[-2]
        step = 86400 if q["granularity"] == "ONE_DAY" else 3600
        a, b = int(q["start"]), int(q["end"])
        out = []
        t = max(a - a % step, start_day * 86400)
        while t <= b:
            c = price(prod, t); o = price(prod, t - step)
            out.append({"start": str(t), "open": f"{o:.4f}", "high": f"{max(o, c) * 1.01:.4f}", "low": f"{min(o, c) * 0.99:.4f}",
                        "close": f"{c:.4f}", "volume": f"{100 + (t // step) % 50}"})
            t += step
        return 200, json.dumps({"candles": out[::-1]}).encode()
    if u.netloc == "wikimedia.org":
        items = []
        for d in range(start_day, start_day + 1400):
            stamp = dt.datetime.fromtimestamp(d * 86400, dt.timezone.utc).strftime("%Y%m%d00")
            items.append({"timestamp": stamp, "views": 10000 + (d * 37) % 5000})
        return 200, json.dumps({"items": items}).encode()
    if u.netloc == "api.gdeltproject.org":
        data = [{"date": dt.datetime.fromtimestamp(d * 86400, dt.timezone.utc).strftime("%Y%m%dT000000Z"), "value": 300 + d % 90}
                for d in range(start_day, start_day + 1400)]
        return 200, json.dumps({"timeline": [{"series": "Article Count", "data": data}]}).encode()
    if u.netloc == "api.alternative.me":
        return 200, json.dumps({"data": [{"value": str(20 + d % 60), "timestamp": str(d * 86400)} for d in range(start_day + 600, start_day + 3600)]}).encode()
    if u.netloc == "futures.kraken.com":
        rates = [{"timestamp": dt.datetime.fromtimestamp((start_day + 1300) * 86400 + h * 3600, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "relativeFundingRate": 0.00001} for h in range(48)]
        return 200, json.dumps({"result": "success", "rates": rates}).encode()
    if u.netloc == "community-api.coinmetrics.io":                     # v0.5.1: on-chain data (synthetic)
        rows = [{"asset": "btc", "time": dt.datetime.fromtimestamp(d * 86400, dt.timezone.utc).strftime("%Y-%m-%dT00:00:00.000000000Z"),
                 "FlowInExNtv": f"{20000 + (d * 13) % 5000}", "FlowOutExNtv": f"{20000 + (d * 17) % 5000}",
                 "SplyExNtv": f"{2000000 + (d * 7) % 50000}", "SplyCur": "19000000",
                 "CapMVRVCur": f"{1.5 + 0.5 * math.sin(d / 90):.4f}", "AdrActCnt": f"{800000 + (d * 31) % 100000}"}
                for d in range(start_day, start_day + 3200)]
        return 200, json.dumps({"data": rows}).encode()
    return 404, b"{}"
