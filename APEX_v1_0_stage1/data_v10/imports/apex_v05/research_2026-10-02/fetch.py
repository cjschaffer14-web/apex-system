"""Public Coinbase Exchange candles (no key). Saves [ts, open, high, low, close, volume] ascending."""
import json, sys, time, urllib.request, datetime as dt
prod, gran, start = sys.argv[1], int(sys.argv[2]), sys.argv[3]
t = int(dt.datetime.fromisoformat(start).replace(tzinfo=dt.timezone.utc).timestamp())
end_all = int(time.time()) // gran * gran
rows = {}
while t < end_all:
    e = min(t + 300 * gran, end_all)
    url = (f"https://api.exchange.coinbase.com/products/{prod}/candles?granularity={gran}"
           f"&start={dt.datetime.fromtimestamp(t, dt.timezone.utc).replace(tzinfo=None).isoformat()}&end={dt.datetime.fromtimestamp(e, dt.timezone.utc).replace(tzinfo=None).isoformat()}")
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "apex-research"})
            data = json.loads(urllib.request.urlopen(req, timeout=30).read())
            break
        except Exception as ex:
            time.sleep(1 + attempt)
    else:
        raise SystemExit(f"failed at {t}: {ex}")
    for ts, lo, hi, op, cl, vol in data:
        rows[int(ts)] = (int(ts), float(op), float(hi), float(lo), float(cl), float(vol))
    t = e
    time.sleep(0.15)
out = [rows[k] for k in sorted(rows)]
json.dump(out, open(f"{prod}_{gran}.json", "w"))
print(prod, gran, len(out), dt.datetime.utcfromtimestamp(out[0][0]), dt.datetime.utcfromtimestamp(out[-1][0]))
