"""v0.5 data: APEX builds its own history from public sources (owner decision 1, 2 Oct 2026).

No download by the owner. Read-only GET requests, under the network.web lease, to:
  api.coinbase.com          public candles (no key): daily for the universe since 2015, hourly for BTC/ETH since 2017
  wikimedia.org             Wikipedia daily pageviews since Jul 2015 (attention)
  api.gdeltproject.org      GDELT daily news article counts since 2017 (attention)
  api.alternative.me        Crypto Fear & Greed since Feb 2018
  futures.kraken.com        perpetual funding rates (about the last 12 months; collected forward from here)

A backfill is one governed action per product and source: a single token authorizes a bounded batch of GET
requests inside the lease's hosts, paced politely. Text never crosses: responses are reduced to numbers and
short labels (timestamps and dates included) at the membrane.
"""
from __future__ import annotations
import datetime as dt
import hashlib, json, math, re, time
from typing import Any, Callable, Iterable
from . import crypto_pack as cp
from .epistemics import INSTRUCTION_LIKE

UNIVERSE = ("BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD", "DOGE-USD", "LTC-USD", "LINK-USD", "BCH-USD",
            "DOT-USD", "AVAX-USD", "XLM-USD", "ATOM-USD", "UNI-USD", "ETC-USD", "AAVE-USD", "FIL-USD", "HBAR-USD",
            "NEAR-USD", "ALGO-USD")
HOURLY = ("BTC-USD", "ETH-USD")
HISTORY_START = {"daily": "2015-07-20", "hourly": "2017-01-01"}

V05_HOSTS = cp.RATIFIED_HOSTS + ("wikimedia.org", "api.gdeltproject.org", "futures.kraken.com")

WIKI_ARTICLES = {"Bitcoin": "BTC-USD", "Ethereum": "ETH-USD", "Cryptocurrency": "market"}
GDELT_QUERIES = ("bitcoin", "cryptocurrency")
FUNDING_SYMBOLS = {"PF_XBTUSD": "BTC-USD", "PF_ETHUSD": "ETH-USD"}

GRAN = {1440: ("ONE_DAY", 86400), 60: ("ONE_HOUR", 3600)}
EXTRA_LABELS = {"timestamp", "date", "start"}
DATE_LABEL = re.compile(r"^[0-9][0-9TZ:\-.+ ]{5,39}$")          # dates and times only: digits, T, Z, : - . +


def _day(ts: float) -> int:
    return int(ts // 86400)


def iso_day(day: int) -> str:
    return dt.datetime.fromtimestamp(day * 86400, dt.timezone.utc).strftime("%Y-%m-%d")


def reduce_v5(obj: Any) -> dict:
    """cp.reduce_to_numbers, plus timestamp/date strings kept as labels (still no free text)."""
    red = cp.reduce_to_numbers(obj)

    def walk(o: Any, path: str) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                p = f"{path}.{k}" if path else str(k)
                if k in EXTRA_LABELS and isinstance(v, str) and DATE_LABEL.match(v):
                    red["labels"][p] = v
                else:
                    walk(v, p)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}.{i}" if path else str(i))
    walk(obj, "")
    return red


class PoliteBudget(cp.SourceBudget):
    """v0.4's per-host budget, but a too-soon request waits its turn instead of failing (daily caps still refuse).
    `wait=False` (tests against a fake web) records the call without sleeping."""

    def __init__(self, wait: bool = True, clock: Callable[[], float] = time.time) -> None:
        super().__init__(clock)
        self.wait = wait

    def take(self, host: str) -> None:
        src = cp.SOURCE_BY_HOST.get(host)
        hist = self.calls.get(host, [])
        if src and hist:
            gap = src.min_interval_s - (self.clock() - hist[-1])
            if gap > 0:
                if self.wait:
                    time.sleep(gap)
                else:
                    self.calls[host] = [x - gap - 1e-6 for x in hist]    # treat the gap as already elapsed
        super().take(host)


HOST_SPACING_S = {"api.gdeltproject.org": 6.0, "wikimedia.org": 1.0, "futures.kraken.com": 1.0}


def polite_opener(base: Callable[[str, dict, float], tuple[int, bytes]] | None = None, retries: int = 2,
                  sleep: Callable[[float], None] = time.sleep):
    """HTTP errors become (status, body) instead of exceptions; 429 and 5xx are retried with backoff."""
    import urllib.error
    base = base or cp._urllib_opener

    def call(url: str, headers: dict, timeout: float) -> tuple[int, bytes]:
        for attempt in range(retries + 1):
            try:
                status, body = base(url, headers, timeout)
            except urllib.error.HTTPError as e:
                status, body = e.code, e.read() if hasattr(e, "read") else b""
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                status, body = 599, str(e).encode()
            if status in (429, 500, 502, 503, 504, 599) and attempt < retries:
                sleep(10.0 * (attempt + 1))
                continue
            return status, body
        return status, body
    return call


class FetcherV5(cp.AllowlistedFetcher):
    """Same rules as v0.4 (GET only, HTTPS only, allowlisted hosts, metered, no credentials in URLs); network errors
    come back as data with their status, never as a crash."""

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        if kw.get("opener") is None:
            self.opener = polite_opener()
        self._last: dict[str, float] = {}

    def __call__(self, host: str = "", path: str = "", params: dict | None = None, key_header: str | None = None) -> dict:
        url = self.url(host, path, params)
        self.budget.take(host)
        gap = HOST_SPACING_S.get(host, 0.0) - (time.time() - self._last.get(host, 0.0))
        if gap > 0 and getattr(self.budget, "wait", True):
            time.sleep(gap)                                    # hosts that ask for slower clients get them
        self._last[host] = time.time()
        headers = {key_header: self._keys[key_header]} if key_header and key_header in self._keys else {}
        status, body = self.opener(url, headers, self.timeout)
        if len(body) > self.max_bytes:
            raise PermissionError(f"response larger than {self.max_bytes} bytes")
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = None
        reduced = reduce_v5(data) if data is not None else {"numbers": {}, "labels": {}, "dropped_text": 1}
        return {"host": host, "path": path, "status": status, "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(), **reduced}


# --- parsers (reduced responses -> rows) -------------------------------------------------------------------

def _rows(reduced: dict, pattern: str) -> dict[int, dict]:
    rows: dict[int, dict] = {}
    rx = re.compile(pattern)
    for src in (reduced["numbers"], reduced["labels"]):
        for k, v in src.items():
            m = rx.match(k)
            if m:
                rows.setdefault(int(m.group(1)), {})[m.group(2)] = v
    return rows


def parse_wikimedia(reduced: dict) -> list[tuple[int, float]]:
    out = []
    for r in _rows(reduced, r"items\.(\d+)\.(timestamp|views)$").values():
        if "timestamp" in r and "views" in r:
            d = str(int(float(r["timestamp"])))[:8]
            out.append((_day(dt.datetime.strptime(d, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()),
                        float(r["views"])))
    return sorted(out)


def parse_gdelt(reduced: dict) -> list[tuple[int, float]]:
    out = []
    for r in _rows(reduced, r"timeline\.0\.data\.(\d+)\.(date|value)$").values():
        if "date" in r and "value" in r:
            day = _day(dt.datetime.strptime(r["date"][:8], "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp())
            out.append((day, float(r["value"])))
    return sorted(out)


def parse_funding(reduced: dict) -> list[tuple[int, float]]:
    """Hourly relative funding rates -> daily sums (fraction of notional per day)."""
    daily: dict[int, float] = {}
    for r in _rows(reduced, r"rates\.(\d+)\.(timestamp|relativeFundingRate)$").values():
        if "timestamp" in r and "relativeFundingRate" in r:
            t = dt.datetime.strptime(r["timestamp"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
            daily[_day(t.timestamp())] = daily.get(_day(t.timestamp()), 0.0) + float(r["relativeFundingRate"])
    return sorted(daily.items())


# --- backfill jobs (run inside one governed token each) ----------------------------------------------------

def coinbase_windows(start_ts: int, end_ts: int, step: int, size: int = 350) -> list[tuple[int, int]]:
    out, t = [], start_ts
    while t <= end_ts:
        out.append((t, min(end_ts, t + (size - 1) * step)))
        t += size * step
    return out


def backfill_coinbase(fetch: Callable[..., dict], store: cp.MarketStore, product: str, interval: int,
                      now_ts: float | None = None, pace_s: float = 0.25, max_requests: int = 400) -> dict:
    gran_name, step = GRAN[interval]
    now_ts = int(now_ts or time.time()) // step * step
    last = store.db.execute("SELECT MAX(ts) FROM candles WHERE source='coinbase' AND pair=? AND interval=?",
                            (product, interval)).fetchone()[0]
    start = (int(last) + step) if last else int(dt.datetime.fromisoformat(
        HISTORY_START["daily" if interval == 1440 else "hourly"]).replace(tzinfo=dt.timezone.utc).timestamp())
    reqs = inserted = 0
    for a, b in coinbase_windows(start, now_ts - step, step):     # the bar still forming is never stored
        if reqs >= max_requests:
            break
        res = fetch(host="api.coinbase.com", path=f"/api/v3/brokerage/market/products/{product}/candles",
                    params={"start": str(a), "end": str(b), "granularity": gran_name, "limit": "350"})
        reqs += 1
        rows = [r for r in cp.parse_coinbase_candles(res) if r[0] <= now_ts - step]
        if rows:
            inserted += max(0, store.add_candles("coinbase", product, interval, rows))
        if pace_s:
            time.sleep(pace_s)
    return {"product": product, "interval": interval, "requests": reqs, "inserted": inserted}


def backfill_attention(fetch: Callable[..., dict], store: cp.MarketStore, now_ts: float | None = None,
                       pace_s: float = 0.5) -> dict:
    today = dt.datetime.fromtimestamp(now_ts or time.time(), dt.timezone.utc)
    out = {}
    for article in WIKI_ARTICLES:
        res = fetch(host="wikimedia.org",
                    path=f"/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{article}/daily/"
                         f"20150701/{today:%Y%m%d}")
        rows = [(f"wiki:{article}", d, v) for d, v in parse_wikimedia(res)]
        out[f"wiki:{article}"] = store.add_readings("attention", rows)
        if pace_s:
            time.sleep(pace_s)
    for q in GDELT_QUERIES:
        res = fetch(host="api.gdeltproject.org", path="/api/v2/doc/doc",
                    params={"query": q, "mode": "timelinevolraw", "format": "json",
                            "startdatetime": "20170101000000", "enddatetime": f"{today:%Y%m%d}000000"})
        out[f"gdelt:{q}"] = store.add_readings("attention", [(f"gdelt:{q}", d, v) for d, v in parse_gdelt(res)])
        if pace_s:
            time.sleep(pace_s)
    res = fetch(host="api.alternative.me", path="/fng/", params={"limit": "0", "format": "json"})
    out["fear_greed"] = store.add_readings("attention", [("fear_greed", _day(t), v) for _, t, v in cp.parse_fng(res)])
    for sym, prod in FUNDING_SYMBOLS.items():
        res = fetch(host="futures.kraken.com", path="/derivatives/api/v4/historicalfundingrates", params={"symbol": sym})
        out[f"funding:{prod}"] = store.add_readings("funding", [(f"funding:{prod}", d, v) for d, v in parse_funding(res)])
        if pace_s:
            time.sleep(pace_s)
    return out


# --- R0: the public-data seed gate --------------------------------------------------------------------------

def r0_gate(store: cp.MarketStore, min_days: float = 730.0, min_products: int = 10) -> cp.GateResult:
    cov = [c for c in store.coverage("coinbase") if c["interval"] == 1440]
    long_enough = [c for c in cov if c["span_days"] >= 365]
    longest = max((c["span_days"] for c in cov), default=0.0)
    bad = store.db.execute("SELECT COUNT(*) FROM candles WHERE source='coinbase' AND "
                           "(low > high OR close <= 0 OR open <= 0 OR volume < 0)").fetchone()[0]
    rows = sum(c["rows"] for c in cov)
    reasons = []
    if longest < min_days:
        reasons.append(f"longest daily history {longest} days < {min_days}")
    if len(long_enough) < min_products:
        reasons.append(f"{len(long_enough)} products with a year of history < {min_products}")
    if rows and bad / rows > 0.001:
        reasons.append(f"{bad} malformed candles")
    return cp.GateResult("R0", not reasons, {"products": len(cov), "products_1y": len(long_enough), "rows": rows,
                                              "longest_days": longest, "bad_rows": bad}, reasons)
