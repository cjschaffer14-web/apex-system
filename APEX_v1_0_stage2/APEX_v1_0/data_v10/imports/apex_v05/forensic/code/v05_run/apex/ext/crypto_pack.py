"""Crypto Data Pack (v0.4): a running start for trading research, inside the walls.

Ratified 2 Oct 2026 (APEX v0.4 Synthesis, "Running start for trading research").

  Seed (rung 1, local files, no permission): Kraken's downloadable OHLCVT
  archive, parsed and validated into a local SQLite market store. Passing the
  T0 gate (corpus validated) is the condition on which the owner's
  pre-approved six-host web lease opens.

  Live feed (one lease): network.web, read-only GET requests to the ratified
  hosts, 30-day expiry, revocable by the owner at any time.

  Trading ladder: T0 Corpus -> T1 Research -> T2 Simulation -> T3 Paper ->
  T4 Shadow -> T5 Live. Exchange keys exist only at T5, which needs a
  separate ratification. Nothing in this module can place an order.

Membrane rule (Gemini TH-01): text is reduced to numbers before it crosses
into the system. Short identifier labels survive; free text does not.
Sentiment never authorizes: it can only widen the uncertainty term sigma.

Nothing here is financial advice. Simulated results are research outputs.
"""
from __future__ import annotations
import hashlib, io, json, math, re, sqlite3, time, zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from collections import deque
from statistics import mean, pstdev
from typing import Any, Callable, Iterable, Iterator
from urllib.parse import urlencode
from ..domain.base import DomainPack
from .domain_policy import CapitalStewardshipPolicy
from .epistemics import INSTRUCTION_LIKE

# --- sources ---------------------------------------------------------------------------

# The six hosts in the owner's pre-approval. Revision 2 (owner approved, 2 Oct 2026): Coin Metrics' free
# Community API (community-api.coinmetrics.io) replaces api.coinmetrics.io, which is the paid Pro API.
RATIFIED_HOSTS = ("api.coinbase.com", "api.coingecko.com", "api.llama.fi", "community-api.coinmetrics.io",
                  "mempool.space", "api.alternative.me")

# Host corrections found while building (Coin Metrics API v4 docs). Applied in pre-approval revision 2;
# kept so a ledger that recorded revision 1 is upgraded at its next awakening.
HOST_CORRECTIONS = {
    "api.coinmetrics.io": {"use": "community-api.coinmetrics.io",
                           "why": "Community (free, no key) base URL is https://community-api.coinmetrics.io/v4; "
                                  "api.coinmetrics.io is the Pro API",
                           "status": "applied in pre-approval revision 2 (owner approved 2 Oct 2026)"},
}

CRYPTO_CHANNEL_TRUST = {"market": 0.80, "aggregated": 0.75, "onchain": 0.85, "sentiment": 0.50, "trends": 0.60}


@dataclass(frozen=True)
class DataSource:
    name: str
    host: str | None            # None: local files
    gives: str
    access: str
    terms: str
    channel: str
    trust: float
    permission: str
    attribution: str = ""
    per_day: int | None = None  # call budget per day (None: unmetered beyond min interval)
    min_interval_s: float = 0.0


SOURCES: tuple[DataSource, ...] = (
    DataSource("kraken_ohlcvt", None, "OHLCVT candles (1m to 1d) for every pair since its first trade",
               "free ZIP of CSVs; quarterly updates", "Kraken terms", "market", 0.80, "none (seed: local files)"),
    DataSource("coinbase_candles", "api.coinbase.com", "recent candles, 1 minute to 1 day",
               "no key; at most 350 candles per request", "Coinbase API terms", "market", 0.80, "web lease",
               min_interval_s=0.2),
    DataSource("coingecko_demo", "api.coingecko.com", "prices, market caps, volumes",
               "free Demo key; 100 calls/min, 10,000 calls/month", "attribution; non-commercial on Demo",
               "aggregated", 0.75, "web lease + free key", "Data provided by CoinGecko", per_day=330,
               min_interval_s=0.6),
    DataSource("defillama", "api.llama.fi", "TVL, fees and revenue, stablecoins, yields",
               "no key", "open", "aggregated", 0.75, "web lease", "DefiLlama", min_interval_s=1.0),
    DataSource("coinmetrics_community", "community-api.coinmetrics.io", "network data (free subset)",
               "no key; 10 requests per 6 s per IP", "CC BY-NC 4.0", "onchain", 0.85,
               "web lease", "Coin Metrics", min_interval_s=0.6),
    DataSource("mempool_space", "mempool.space", "hashrate, difficulty, fees, rewards",
               "no key; rate limited (HTTP 429)", "open", "onchain", 0.85, "web lease", min_interval_s=1.0),
    DataSource("alternative_fng", "api.alternative.me", "daily Crypto Fear & Greed index",
               "no key; daily", "attribution next to any display", "sentiment", 0.50, "web lease",
               "Fear & Greed Index by Alternative.me", per_day=48, min_interval_s=1.0),
)
SOURCE_BY_HOST = {s.host: s for s in SOURCES if s.host}


@dataclass(frozen=True)
class Endpoint:
    host: str
    path: str
    params: dict
    channel: str
    parser: str = "numbers"
    key_header: str | None = None


ENDPOINTS: dict[str, Endpoint] = {
    "coinbase.candles": Endpoint("api.coinbase.com", "/api/v3/brokerage/market/products/{product}/candles",
                                 {"granularity": "ONE_DAY"}, "market", "coinbase_candles"),
    "coingecko.market_chart": Endpoint("api.coingecko.com", "/api/v3/coins/{coin}/market_chart",
                                       {"vs_currency": "usd", "days": "365"}, "aggregated",
                                       key_header="x-cg-demo-api-key"),
    "defillama.fees_overview": Endpoint("api.llama.fi", "/overview/fees",
                                        {"excludeTotalDataChart": "true", "excludeTotalDataChartBreakdown": "true"},
                                        "aggregated"),
    "defillama.protocol_fees": Endpoint("api.llama.fi", "/summary/fees/{protocol}", {"dataType": "dailyFees"},
                                        "aggregated"),
    "coinmetrics.asset_metrics": Endpoint("community-api.coinmetrics.io", "/v4/timeseries/asset-metrics",
                                          {"assets": "btc", "metrics": "PriceUSD,AdrActCnt", "frequency": "1d"},
                                          "onchain"),
    "mempool.hashrate": Endpoint("mempool.space", "/api/v1/mining/hashrate/1y", {}, "onchain"),
    "mempool.difficulty": Endpoint("mempool.space", "/api/v1/difficulty-adjustment", {}, "onchain"),
    "alternative.fng": Endpoint("api.alternative.me", "/fng/", {"limit": "0", "format": "json"}, "sentiment", "fng"),
}

# --- packs -------------------------------------------------------------------------------

CRYPTO_DATA_PACK = DomainPack(
    name="crypto_data",
    schemas=["candle", "reading", "import_manifest", "gate_result", "walk_forward_report"],
    tools=["corpus.import_kraken", "data.fetch", "sim.walk_forward", "research.corpus_stats"],
    models=["walk_forward_simulator"],
    evaluators=["t0_corpus_gate", "t2_simulation_gate", "out_of_sample_sharpe", "max_drawdown"],
    risk_policy={"external_actuation": False, "live_default": False, "orders": "none below T5",
                 "exchange_keys": "T5 only, separate ratification", "network": "GET-only, ratified hosts, leased"},
    memory_rules={"provenance": "every file and response is hashed", "text": "reduced to numbers at the membrane"},
    benchmarks=["oos_sharpe", "max_drawdown", "trades"],
    capabilities=["corpus.import_kraken", "data.fetch", "sim.walk_forward", "research.corpus_stats"],
)

# Owner note (adopted as a sub-pack of Research): read-only legal research. Its output is
# research, not legal advice; decisions about legal entities go to an attorney. It has no
# pre-approved hosts: its own web lease needs the owner's verified presence.
LEGAL_RESEARCH_PACK = DomainPack(
    name="legal_research",
    schemas=["statute", "regulation", "guidance", "case_summary", "jurisdiction_tag"],
    tools=["data.fetch", "research.summarize"],
    models=["local_reader"],
    evaluators=["citation_check", "jurisdiction_check", "recency_check"],
    risk_policy={"external_actuation": False, "output": "research, not legal advice",
                 "decisions": "attorney review", "suggested_hosts": ["www.ecfr.gov", "www.federalregister.gov",
                                                                      "www.sec.gov", "www.cftc.gov", "www.irs.gov"]},
    capabilities=["data.fetch"],
)


@dataclass(frozen=True)
class Rung:
    id: str
    name: str
    gate: str
    permission: str


TRADING_LADDER = (
    Rung("T0", "Corpus", "Kraken seed parsed, hashed and validated (T0 gate)", "none: local files"),
    Rung("T1", "Research", "descriptive research on the corpus recorded with provenance",
         "none; the six-host web lease opens automatically after T0 (pre-approved)"),
    Rung("T2", "Simulation", "walk-forward, out of sample: >= 1,000 trades, positive risk-adjusted return, "
                             "max drawdown < 20%", "none (local compute)"),
    Rung("T3", "Paper", "paper orders against live prices for a full evaluation window", "market.paper_order lease"),
    Rung("T4", "Shadow", "owner ratification, capital ceiling, attorney review", "verified presence"),
    Rung("T5", "Live", "separate ratification; exchange keys exist only here", "verified presence + keys"),
)


@dataclass(frozen=True)
class CryptoTradingContract:
    """Trading-pack policy for crypto (Gemini moved sigma inflation and deleveraging here; Authority stays
    tighten-only). These shape position size inside a simulation or a later rung; they never authorize."""
    k_sentiment: float = 0.5
    drawdown_halt: float = 0.20
    stewardship: CapitalStewardshipPolicy = field(default_factory=CapitalStewardshipPolicy)

    def sentiment_sigma(self, base_sigma: float, fear_greed: float | None) -> float:
        """Sentiment can only widen uncertainty: sigma' = sigma * (1 + k * |FG - 50| / 50) >= sigma."""
        if fear_greed is None:
            return base_sigma
        extremeness = min(1.0, abs(float(fear_greed) - 50.0) / 50.0)
        return base_sigma * (1.0 + self.k_sentiment * extremeness)

    def deleverage(self, exposure: float, drawdown: float) -> float:
        """Exposure shrinks linearly to zero as drawdown approaches the halt level (v0.4.0 rule; it can lock a
        simulation in cash forever after a deep drawdown, the CPPI "cash-lock". Kept for reference.)"""
        return max(0.0, exposure * (1.0 - max(0.0, drawdown) / self.drawdown_halt))

    def brake(self, rolling_drawdown: float, floor: float = 0.25) -> float:
        """v0.4.1 drawdown brake: scale in [floor, 1] from drawdown against a ROLLING high-water mark, so the
        brake releases as the window moves on (no permanent cash-lock). The hard halt stays separate: an
        all-time drawdown at the halt level stops trading until the owner reviews it."""
        return max(floor, 1.0 - max(0.0, rolling_drawdown) / self.drawdown_halt)

    @property
    def max_exposure(self) -> float:
        return 1.0 - self.stewardship.stewardship_floor


# --- valuation helpers (Gemini, E2/E3; Trading pack only; research inputs, not advice) ---------------

def fee_value(annual_fees_usd: float, holder_share: float, discount_rate: float, growth: float = 0.0) -> float:
    """Fee-accruing tokens: Gordon growth on the holders' share of fees. Needs discount_rate > growth."""
    if discount_rate <= growth:
        raise ValueError("discount rate must exceed growth")
    cf = annual_fees_usd * holder_share
    return cf * (1 + growth) / (discount_rate - growth)


def pow_cost_of_production(hashrate_ehs: float, joules_per_th: float, usd_per_kwh: float,
                           block_subsidy_btc: float = 3.125, fees_btc_per_block: float = 0.0,
                           blocks_per_day: float = 144.0) -> float:
    """Proof-of-work coins: network electricity cost per coin produced (USD/BTC)."""
    watts = hashrate_ehs * 1e6 * joules_per_th          # EH/s -> TH/s, times J/TH = W
    usd_per_day = watts * 24 / 1000 * usd_per_kwh
    coins_per_day = blocks_per_day * (block_subsidy_btc + fees_btc_per_block)
    return usd_per_day / coins_per_day


def metcalfe_index(active_addresses: float, k: float = 1.0, exponent: float = 2.0) -> float:
    """Utility tokens: a relative network-value index from active addresses (compare over time, not across coins)."""
    return k * max(0.0, active_addresses) ** exponent


# --- market store ----------------------------------------------------------------------------

class MarketStore:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS candles(source TEXT, pair TEXT, interval INTEGER, ts INTEGER, open REAL, high REAL,
        low REAL, close REAL, volume REAL, trades INTEGER, PRIMARY KEY(source, pair, interval, ts)) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS readings(source TEXT, metric TEXT, ts INTEGER, value REAL,
        PRIMARY KEY(source, metric, ts)) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS imports(sha256 TEXT PRIMARY KEY, file TEXT, pair TEXT, interval INTEGER,
        report TEXT, imported_at REAL);
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.executescript(self.SCHEMA)

    def close(self) -> None:
        self.db.close()

    def add_candles(self, source: str, pair: str, interval: int, rows: Iterable[tuple]) -> int:
        cur = self.db.executemany(
            "INSERT OR IGNORE INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)",
            ((source, pair, interval, *r) for r in rows))
        self.db.commit()
        return cur.rowcount

    def add_readings(self, source: str, rows: Iterable[tuple[str, int, float]]) -> int:
        cur = self.db.executemany("INSERT OR REPLACE INTO readings VALUES (?,?,?,?)",
                                  ((source, m, int(t), float(v)) for m, t, v in rows))
        self.db.commit()
        return cur.rowcount

    def series(self, pair: str, interval: int, source: str = "kraken") -> list[tuple[int, float, float, float, float, float]]:
        return self.db.execute("SELECT ts, open, high, low, close, volume FROM candles WHERE source=? AND pair=? "
                               "AND interval=? ORDER BY ts", (source, pair, interval)).fetchall()

    def closes(self, pair: str, interval: int, source: str = "kraken") -> list[tuple[int, float]]:
        return self.db.execute("SELECT ts, close FROM candles WHERE source=? AND pair=? AND interval=? ORDER BY ts",
                               (source, pair, interval)).fetchall()

    def coverage(self, source: str = "kraken") -> list[dict]:
        rows = self.db.execute("SELECT pair, interval, COUNT(*), MIN(ts), MAX(ts) FROM candles WHERE source=? "
                               "GROUP BY pair, interval ORDER BY pair, interval", (source,)).fetchall()
        return [{"pair": p, "interval": i, "rows": n, "first": a, "last": b, "span_days": round((b - a) / 86400, 1)}
                for p, i, n, a, b in rows]

    def imports(self) -> list[dict]:
        return [dict(json.loads(r[0]), sha256=r[1]) for r in
                self.db.execute("SELECT report, sha256 FROM imports ORDER BY imported_at")]

    def already_imported(self, sha: str) -> bool:
        return self.db.execute("SELECT 1 FROM imports WHERE sha256=?", (sha,)).fetchone() is not None

    def record_import(self, report: "ImportReport") -> None:
        self.db.execute("INSERT OR REPLACE INTO imports VALUES (?,?,?,?,?,?)",
                        (report.sha256, report.file, report.pair, report.interval, json.dumps(asdict(report)), time.time()))
        self.db.commit()


# --- Kraken seed importer --------------------------------------------------------------------

KRAKEN_FILE = re.compile(r"(?:^|[/:])([A-Z0-9]+)_(\d+)\.csv$")


@dataclass
class ImportReport:
    file: str
    pair: str
    interval: int
    sha256: str = ""
    rows: int = 0
    inserted: int = 0
    malformed: int = 0
    bad_ohlc: int = 0
    nonpositive: int = 0
    negative_volume: int = 0
    non_monotone: int = 0
    gaps: int = 0
    first_ts: int | None = None
    last_ts: int | None = None
    skipped: str = ""

    @property
    def bad(self) -> int:
        return self.malformed + self.bad_ohlc + self.nonpositive + self.negative_volume + self.non_monotone


class KrakenSeedImporter:
    """Imports Kraken's OHLCVT CSVs (no header: timestamp, open, high, low, close, volume, trades) from a folder
    of CSVs or ZIP archives. Streams rows, hashes every file, validates every row, and is idempotent."""

    def __init__(self, store: MarketStore, pairs: Iterable[str] | None = None,
                 intervals: Iterable[int] = (60, 1440), batch: int = 50_000) -> None:
        self.store = store
        self.pairs = {p.upper() for p in pairs} if pairs else None
        self.intervals = set(int(i) for i in intervals)
        self.batch = batch

    def _wanted(self, name: str) -> tuple[str, int] | None:
        m = KRAKEN_FILE.search(name.replace("\\", "/"))
        if not m:
            return None
        pair, interval = m.group(1), int(m.group(2))
        if interval not in self.intervals or (self.pairs and pair not in self.pairs):
            return None
        return pair, interval

    def _members(self, root: Path) -> Iterator[tuple[str, Callable[[], Any]]]:
        paths = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for p in paths:
            if p.suffix.lower() == ".zip":
                zf = zipfile.ZipFile(p)
                for info in zf.infolist():
                    if not info.is_dir():
                        yield f"{p.name}:{info.filename}", (lambda zf=zf, info=info: zf.open(info))
            elif p.suffix.lower() == ".csv":
                yield str(p), (lambda p=p: p.open("rb"))

    def import_path(self, path: str | Path) -> list[ImportReport]:
        out = []
        for name, opener in self._members(Path(path)):
            want = self._wanted(name)
            if want:
                out.append(self._import_one(name, opener, *want))
        return out

    def _import_one(self, name: str, opener: Callable[[], Any], pair: str, interval: int) -> ImportReport:
        rep = ImportReport(name, pair, interval)
        h = hashlib.sha256()
        with opener() as f:          # pass 1: hash (provenance) so a re-import is a no-op
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        rep.sha256 = h.hexdigest()
        if self.store.already_imported(rep.sha256):
            rep.skipped = "already imported (same sha256)"
            return rep
        step, last, buf = interval * 60, None, []
        with opener() as f:
            for raw in f:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                rep.rows += 1
                parts = line.split(",")
                try:
                    ts = int(float(parts[0]))
                    o, hi, lo, c, v = (float(x) for x in parts[1:6])
                    n = int(float(parts[6])) if len(parts) > 6 and parts[6] else 0
                except (ValueError, IndexError):
                    rep.malformed += 1
                    continue
                if min(o, hi, lo, c) <= 0 or not all(math.isfinite(x) for x in (o, hi, lo, c, v)):
                    rep.nonpositive += 1
                    continue
                if lo > min(o, c) * (1 + 1e-9) or hi < max(o, c) * (1 - 1e-9) or lo > hi:
                    rep.bad_ohlc += 1
                    continue
                if v < 0:
                    rep.negative_volume += 1
                    continue
                if last is not None:
                    if ts <= last:
                        rep.non_monotone += 1
                        continue
                    if ts - last > step:
                        rep.gaps += 1      # Kraken omits intervals with no trades; counted, not an error
                rep.first_ts = ts if rep.first_ts is None else rep.first_ts
                rep.last_ts, last = ts, ts
                buf.append((ts, o, hi, lo, c, v, n))
                if len(buf) >= self.batch:
                    rep.inserted += max(0, self.store.add_candles("kraken", pair, interval, buf))
                    buf = []
        if buf:
            rep.inserted += max(0, self.store.add_candles("kraken", pair, interval, buf))
        self.store.record_import(rep)
        return rep


# --- T0 gate ----------------------------------------------------------------------------------

@dataclass
class GateResult:
    gate: str
    passed: bool
    metrics: dict
    reasons: list[str]

    def digest(self) -> str:
        return hashlib.sha256(json.dumps({"gate": self.gate, "passed": self.passed, "metrics": self.metrics},
                                         sort_keys=True, default=str).encode()).hexdigest()


def t0_gate(store: MarketStore, min_days: float = 730.0, max_error_rate: float = 0.001,
            min_agreement: float = 0.99, sample_days: int = 200) -> GateResult:
    """Corpus validated: files hashed, row error rate low, enough history, daily vs hourly closes agree."""
    reps = store.imports()
    rows = sum(r["rows"] for r in reps)
    bad = sum(r["malformed"] + r["bad_ohlc"] + r["nonpositive"] + r["negative_volume"] + r["non_monotone"]
              for r in reps)
    cov = store.coverage("kraken")
    longest = max((c["span_days"] for c in cov), default=0.0)
    reasons = []
    if not reps:
        reasons.append("no Kraken files imported yet (download the archive into the APEX data folder)")
    if rows and bad / rows > max_error_rate:
        reasons.append(f"row error rate {bad / rows:.4%} > {max_error_rate:.2%}")
    if longest < min_days:
        reasons.append(f"longest history {longest} days < {min_days}")
    # Cross-check: the daily close must match the last hourly close of that UTC day.
    checked = agree = 0
    for pair in sorted({c["pair"] for c in cov if c["interval"] == 1440}
                       & {c["pair"] for c in cov if c["interval"] == 60}):
        daily = store.closes(pair, 1440)[-sample_days:]
        for ts, close in daily:
            row = store.db.execute("SELECT close FROM candles WHERE source='kraken' AND pair=? AND interval=60 "
                                   "AND ts>=? AND ts<? ORDER BY ts DESC LIMIT 1", (pair, ts, ts + 86400)).fetchone()
            if row:
                checked += 1
                agree += abs(row[0] - close) <= 0.01 * close
    agreement = agree / checked if checked else None
    if agreement is not None and agreement < min_agreement:
        reasons.append(f"daily/hourly close agreement {agreement:.2%} < {min_agreement:.0%}")
    metrics = {"files": len(reps), "rows": rows, "bad_rows": bad, "pairs": len({c['pair'] for c in cov}),
               "longest_days": longest, "cross_checked_days": checked, "agreement": agreement,
               "manifest": sorted(r["sha256"] for r in reps)}
    return GateResult("T0", not reasons, metrics, reasons)


# --- membrane-safe fetch (the data.fetch organ) ------------------------------------------------

CREDENTIAL_KEYS = re.compile(r"(key|token|secret|pass|auth|session|cookie|signature)", re.I)
LABEL_KEYS = {"id", "symbol", "slug", "name", "product_id", "pair", "asset", "chain", "category",
              "value_classification", "time", "date"}
LABEL_OK = re.compile(r"^[\w .\-/()&+]{1,64}$")
NUMERIC = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")


def reduce_to_numbers(obj: Any, max_leaves: int = 200_000) -> dict:
    """TH-01: numbers cross the membrane; short identifier labels survive; free text is dropped."""
    numbers: dict[str, float] = {}
    labels: dict[str, str] = {}
    dropped = 0

    def walk(o: Any, path: str) -> None:
        nonlocal dropped
        if len(numbers) + len(labels) >= max_leaves:
            dropped += 1
            return
        if isinstance(o, bool):
            numbers[path] = float(o)
        elif isinstance(o, (int, float)):
            if math.isfinite(o):
                numbers[path] = float(o)
        elif isinstance(o, str):
            key = path.rsplit(".", 1)[-1]
            if NUMERIC.match(o.strip()):
                numbers[path] = float(o)
            elif key in LABEL_KEYS and LABEL_OK.match(o) and not INSTRUCTION_LIKE.search(o):
                labels[path] = o
            else:
                dropped += 1
        elif isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}.{i}" if path else str(i))

    walk(obj, "")
    return {"numbers": numbers, "labels": labels, "dropped_text": dropped}


class SourceBudget:
    """Meters calls per host to stay inside free tiers (per-day count and minimum spacing)."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.calls: dict[str, list[float]] = {}

    def take(self, host: str) -> None:
        src = SOURCE_BY_HOST.get(host)
        t = self.clock()
        hist = [x for x in self.calls.get(host, []) if t - x < 86400]
        if src and src.per_day is not None and len(hist) >= src.per_day:
            raise PermissionError(f"{host}: daily budget of {src.per_day} calls used")
        if src and hist and t - hist[-1] < src.min_interval_s:
            raise PermissionError(f"{host}: wait {src.min_interval_s - (t - hist[-1]):.2f}s (rate limit)")
        hist.append(t)
        self.calls[host] = hist

    def usage(self) -> dict[str, int]:
        t = self.clock()
        return {h: sum(1 for x in v if t - x < 86400) for h, v in self.calls.items()}


Opener = Callable[[str, dict, float], tuple[int, bytes]]


def _urllib_opener(url: str, headers: dict, timeout: float) -> tuple[int, bytes]:
    import urllib.request

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):  # a redirect could leave the allowlist: refuse all
            return None

    req = urllib.request.Request(url, headers={"User-Agent": "APEX-research/0.4", "Accept": "application/json",
                                               **headers}, method="GET")
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as r:
        return r.status, r.read(5_000_001)


class AllowlistedFetcher:
    """GET-only, HTTPS-only, allowlisted hosts, metered, size-capped; no credentials in URLs.

    The lease (Authority) decides whether a fetch may happen at all and which host; this organ is the
    second, independent check at the point of actuation.
    """

    def __init__(self, hosts: Iterable[str], opener: Opener | None = None, budget: SourceBudget | None = None,
                 api_keys: dict[str, str] | None = None, max_bytes: int = 5_000_000, timeout: float = 20.0) -> None:
        self.hosts = frozenset(hosts)
        self.opener = opener or _urllib_opener
        self.budget = budget or SourceBudget()
        self._keys = dict(api_keys or {})     # header name -> value, from the owner's local config only
        self.max_bytes, self.timeout = max_bytes, timeout

    def url(self, host: str, path: str, params: dict | None = None) -> str:
        if host not in self.hosts:
            raise PermissionError(f"host {host!r} is not on the allowlist")
        if not path.startswith("/") or "://" in path or "@" in path or ".." in path or "#" in path:
            raise PermissionError(f"path {path!r} is not a plain absolute path")
        params = dict(params or {})
        for k, v in params.items():
            if CREDENTIAL_KEYS.search(str(k)):
                raise PermissionError(f"parameter {k!r} looks like a credential; keys travel only in headers")
            if not isinstance(v, (str, int, float)) or len(str(v)) > 200:
                raise PermissionError(f"parameter {k!r} must be a short scalar")
        return f"https://{host}{path}" + (f"?{urlencode(params)}" if params else "")

    def __call__(self, host: str = "", path: str = "", params: dict | None = None, key_header: str | None = None) -> dict:
        url = self.url(host, path, params)
        self.budget.take(host)
        headers = {key_header: self._keys[key_header]} if key_header and key_header in self._keys else {}
        status, body = self.opener(url, headers, self.timeout)
        if len(body) > self.max_bytes:
            raise PermissionError(f"response larger than {self.max_bytes} bytes")
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = None
        reduced = reduce_to_numbers(data) if data is not None else {"numbers": {}, "labels": {}, "dropped_text": 1}
        return {"host": host, "path": path, "status": status, "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(), **reduced}


def endpoint_call(name: str, **fill: str) -> dict:
    """Resolve a catalog endpoint into fetch kwargs (host, path, params, key_header)."""
    e = ENDPOINTS[name]
    path = e.path.format(**{k: re.sub(r"[^A-Za-z0-9._-]", "", v) for k, v in fill.items()})
    return {"host": e.host, "path": path, "params": dict(e.params), "key_header": e.key_header}


def parse_coinbase_candles(reduced: dict) -> list[tuple]:
    """Rebuild (ts, o, h, l, c, v, trades) rows from a reduced Coinbase candles response."""
    nums, rows = reduced["numbers"], {}
    for k, v in nums.items():
        m = re.match(r"candles\.(\d+)\.(start|open|high|low|close|volume)$", k)
        if m:
            rows.setdefault(int(m.group(1)), {})[m.group(2)] = v
    out = [(int(r["start"]), r["open"], r["high"], r["low"], r["close"], r["volume"], 0)
           for r in rows.values() if {"start", "open", "high", "low", "close", "volume"} <= set(r)]
    return sorted(out)


def parse_fng(reduced: dict) -> list[tuple[str, int, float]]:
    nums, rows = reduced["numbers"], {}
    for k, v in nums.items():
        m = re.match(r"data\.(\d+)\.(value|timestamp)$", k)
        if m:
            rows.setdefault(int(m.group(1)), {})[m.group(2)] = v
    return sorted(("fear_greed", int(r["timestamp"]), r["value"]) for r in rows.values() if {"value", "timestamp"} <= set(r))


# --- T1 research: descriptive statistics on the corpus ------------------------------------------

def log_returns(closes: list[float]) -> list[float]:
    return [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]


def max_drawdown(equity: list[float]) -> float:
    peak, mdd = -math.inf, 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, 1 - e / peak)
    return mdd


def corpus_stats(closes: list[float], bars_per_year: float) -> dict:
    r = log_returns(closes)
    if len(r) < 3:
        return {"bars": len(closes), "note": "not enough data"}
    m, s = mean(r), pstdev(r)
    skew = (sum((x - m) ** 3 for x in r) / len(r)) / s ** 3 if s else 0.0
    kurt = (sum((x - m) ** 4 for x in r) / len(r)) / s ** 4 - 3 if s else 0.0
    ac1 = (sum((a - m) * (b - m) for a, b in zip(r, r[1:])) / len(r)) / s ** 2 if s else 0.0
    return {"bars": len(closes), "ann_return": m * bars_per_year, "ann_vol": s * math.sqrt(bars_per_year),
            "skew": skew, "excess_kurtosis": kurt, "lag1_autocorr": ac1,
            "hit_rate": sum(1 for x in r if x > 0) / len(r), "buy_hold_max_drawdown": max_drawdown(closes)}


# --- T2 simulation: walk-forward backtest -----------------------------------------------------------

def signal_series(closes: list[float], strategy: str, params: tuple = ()) -> list[float]:
    """Target long exposure in [0, 1] for every bar t, using data up to and including t (no look-ahead).
    Computed once per (strategy, params) with prefix sums, then reused by every walk-forward window."""
    n = len(closes)
    ps, pq = [0.0], [0.0]
    for c in closes:
        ps.append(ps[-1] + c)
        pq.append(pq[-1] + c * c)

    def sma(k: int, t: int) -> float | None:
        return (ps[t + 1] - ps[t + 1 - k]) / k if t + 1 >= k else None

    out, prev = [], 0.0
    for t in range(n):
        if strategy == "buy_hold":
            cur = 1.0
        elif strategy == "momentum":
            s = sma(params[0], t)
            cur = prev if s is None else float(closes[t] > s)
        elif strategy == "sma_cross":
            f, s = sma(params[0], t), sma(params[1], t)
            cur = prev if f is None or s is None else float(f > s)
        elif strategy == "mean_reversion":
            k, z_in = params
            m = sma(k, t)
            if m is None:
                cur = prev
            else:
                var = max(0.0, (pq[t + 1] - pq[t + 1 - k]) / k - m * m)
                z = (closes[t] - m) / math.sqrt(var) if var > 0 else 0.0
                cur = 1.0 if z < -z_in else 0.0 if z > 0 else prev
        else:
            raise ValueError(strategy)
        out.append(cur)
        prev = cur
    return out


STRATEGY_GRID = {
    "momentum": [(10,), (20,), (50,)],
    "sma_cross": [(5, 20), (10, 50), (20, 100)],
    "mean_reversion": [(20, 1.0), (20, 2.0)],
}


@dataclass
class SimConfig:
    fee_bps: float = 80.0          # Kraken Pro tier-1 taker fee since 9 Jul 2026 (maker 40); owner-configurable
    slippage_bps: float = 5.0
    bars_per_year: float = 365.0
    rebalance_band: float = 0.05   # ignore exposure changes smaller than this (except entering or exiting)
    carry_positions: bool = True   # v0.4.1: positions carry across walk-forward folds (v0.4.0 closed them out)
    brake: str = "rolling"         # v0.4.1 "rolling" high-water-mark brake; "peak" = v0.4.0's all-time rule
    brake_window: int | None = None  # bars in the rolling high-water mark (default: about one month)
    brake_floor: float = 0.25
    target_vol: float | None = 0.10  # v0.4.1 volatility target (annualized), half the 20% drawdown limit; None = v0.4.0 sizing
    vol_window: int | None = None    # bars in the trailing volatility estimate (default: about one month)
    contract: CryptoTradingContract = field(default_factory=CryptoTradingContract)

    @property
    def window(self) -> int:
        return int(self.brake_window or max(2, round(self.bars_per_year / 12)))

    @property
    def vwindow(self) -> int:
        return int(self.vol_window or max(20, round(self.bars_per_year / 12)))

    @property
    def cost(self) -> float:
        return (self.fee_bps + self.slippage_bps) / 1e4


V040 = dict(carry_positions=False, brake="peak", brake_floor=0.0, target_vol=None)   # reproduce v0.4.0 sizing


def trailing_vol(closes: list[float], cfg: SimConfig) -> list[float | None]:
    """Annualized volatility at bar t from the returns up to and including t (no look-ahead); None in warm-up."""
    w, ann = cfg.vwindow, math.sqrt(cfg.bars_per_year)
    ps, pq, out = [0.0], [0.0], [None]
    for i in range(1, len(closes)):
        r = closes[i] / closes[i - 1] - 1
        ps.append(ps[-1] + r)
        pq.append(pq[-1] + r * r)
        k = min(w, i)
        if k < 20:
            out.append(None)
            continue
        m = (ps[i] - ps[i - k]) / k
        out.append(math.sqrt(max(0.0, (pq[i] - pq[i - k]) / k - m * m)) * ann)
    return out


@dataclass
class SimState:
    """What carries from one out-of-sample fold to the next: money, position, drawdown memory, halt."""
    equity: float = 1.0
    peak: float = 1.0
    pos: float = 0.0
    recent: deque = field(default_factory=deque)   # monotonic (bar, equity) queue: rolling high-water mark in O(1)
    halted_at: int | None = None


def simulate(closes: list[float], signals: list[float], cfg: SimConfig, start: int = 0, end: int | None = None,
             sigma_scale: list[float] | None = None, state: SimState | None = None,
             vol: list[float | None] | None = None) -> dict:
    """Bars [start, end): long or flat, no leverage, exposure <= 1 - stewardship floor, sized to a volatility
    target, braked by rolling drawdown, halted at the drawdown limit, costs on every change of exposure.
    Returns net and gross per-bar returns, turnover, trades split by cause, and the carried state."""
    end = len(closes) - 1 if end is None else min(end, len(closes) - 1)
    st = state or SimState()
    c = cfg.contract
    if cfg.target_vol and vol is None:
        vol = trailing_vol(closes, cfg)
    net, gross, turn = [], [], []
    trades = sig_trades = braked = 0
    exposure_sum = 0.0
    for t in range(start, end):
        dd_all = 1 - st.equity / st.peak
        if st.halted_at is None and dd_all >= c.drawdown_halt:
            st.halted_at = t                     # hard halt: in live trading the owner reviews before anything resumes
        size = c.max_exposure
        if cfg.target_vol:
            v = vol[t]
            size = 0.0 if not v else min(c.max_exposure, cfg.target_vol / v)
        want = signals[t] * size
        if st.halted_at is not None:
            target = 0.0
        elif cfg.brake == "peak":
            target = c.deleverage(want, dd_all)
        else:
            hwm = max(st.recent[0][1], st.equity) if st.recent else st.equity
            scale = c.brake(1 - st.equity / hwm, cfg.brake_floor)
            braked += scale < 1.0 and want > 0
            target = want * scale
        if sigma_scale is not None:
            target /= max(1.0, sigma_scale[t])
        change = abs(target - st.pos)
        cost = 0.0
        if change > 1e-9 and (change >= cfg.rebalance_band or target == 0.0 or st.pos == 0.0):
            trades += 1
            sig_trades += t == 0 or signals[t] != signals[t - 1] or target == 0.0 or st.pos == 0.0
            cost = change * cfg.cost
            st.pos = target
        g = st.pos * (closes[t + 1] / closes[t] - 1)
        step = (1 - cost) * (1 + g) - 1
        st.equity *= 1 + step
        st.peak = max(st.peak, st.equity)
        while st.recent and st.recent[-1][1] <= st.equity:
            st.recent.pop()
        st.recent.append((t, st.equity))
        while st.recent[0][0] <= t - cfg.window:
            st.recent.popleft()
        net.append(step)
        gross.append(g)
        turn.append(change if cost else 0.0)
        exposure_sum += st.pos
    if not cfg.carry_positions and st.pos:       # v0.4.0 behaviour: close out at every fold boundary
        trades += 1
        sig_trades += 1
        cost = st.pos * cfg.cost
        st.equity *= 1 - cost
        if net:
            net[-1] = (1 + net[-1]) * (1 - cost) - 1
            turn[-1] += st.pos
        st.pos = 0.0
    n = len(net)
    return {"returns": net, "gross": gross, "turnover": turn, "trades": trades, "signal_trades": sig_trades,
            "rebalance_trades": trades - sig_trades, "braked_bars": braked, "state": st,
            "equity": st.equity, "exposure": exposure_sum / n if n else 0.0}


def sharpe(rets: list[float], bars_per_year: float) -> float:
    if len(rets) < 2:
        return 0.0
    s = pstdev(rets)
    return mean(rets) / s * math.sqrt(bars_per_year) if s else 0.0


def probabilistic_sharpe(rets: list[float], benchmark: float = 0.0) -> float:
    """Bailey & Lopez de Prado PSR: probability that the true per-bar Sharpe exceeds `benchmark`, given the
    sample length, skew and kurtosis."""
    n = len(rets)
    if n < 3:
        return 0.0
    m, s = mean(rets), pstdev(rets)
    if not s:
        return 0.0
    sr = m / s
    g3 = (sum((x - m) ** 3 for x in rets) / n) / s ** 3
    g4 = (sum((x - m) ** 4 for x in rets) / n) / s ** 4
    denom = math.sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
    z = (sr - benchmark) * math.sqrt(n - 1) / denom
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


EULER_GAMMA = 0.5772156649015329


def expected_max_sharpe(n_trials: int, n_obs: int) -> float:
    """Per-bar Sharpe that the best of `n_trials` independent no-skill tries would reach by luck
    (Bailey & Lopez de Prado 2014). One trial: 0."""
    if n_trials <= 1 or n_obs < 3:
        return 0.0
    from statistics import NormalDist
    z = NormalDist().inv_cdf
    sd = math.sqrt(1.0 / (n_obs - 1))
    return sd * ((1 - EULER_GAMMA) * z(1 - 1 / n_trials) + EULER_GAMMA * z(1 - 1 / (n_trials * math.e)))


def deflated_sharpe(rets: list[float], n_trials: int) -> float:
    """DSR: PSR against the Sharpe that luck alone would produce across every research attempt so far."""
    return probabilistic_sharpe(rets, expected_max_sharpe(n_trials, len(rets)))


def walk_forward(closes: list[float], cfg: SimConfig | None = None, train: int = 365, test: int = 90,
                 grid: dict | None = None, sigma_scale: list[float] | None = None, n_trials: int = 1) -> dict:
    """Choose parameters on each training window by net Sharpe; evaluate only on the next unseen window.
    Out-of-sample state (money, position, drawdown memory, halt) carries from fold to fold.
    `n_trials` = how many simulation runs the research program has made so far, for the deflated Sharpe."""
    cfg = cfg or SimConfig()
    grid = grid or STRATEGY_GRID
    sigs = {(st, p): signal_series(closes, st, p) for st, plist in grid.items() for p in plist}
    vol = trailing_vol(closes, cfg) if cfg.target_vol else None
    net, gross, turn, folds = [], [], [], []
    exposure = 0.0
    trades = sig_trades = braked = 0
    state = SimState()
    t = train
    while t + 1 < len(closes):
        best, best_s = None, -math.inf
        for key, sg in sigs.items():
            s = sharpe(simulate(closes, sg, cfg, t - train, t, sigma_scale, None, vol)["returns"], cfg.bars_per_year)
            if s > best_s:
                best, best_s = key, s
        res = simulate(closes, sigs[best], cfg, t, t + test, sigma_scale, state, vol)
        net += res["returns"]; gross += res["gross"]; turn += res["turnover"]
        exposure += res["exposure"] * len(res["returns"])
        trades += res["trades"]; sig_trades += res["signal_trades"]; braked += res["braked_bars"]
        folds.append({"start": t, "choice": f"{best[0]}{best[1]}", "train_sharpe": round(best_s, 3),
                      "test_sharpe": round(sharpe(res["returns"], cfg.bars_per_year), 3), "trades": res["trades"]})
        t += test
    eq, curve = 1.0, [1.0]
    for r in net:
        eq *= 1 + r
        curve.append(eq)
    geq = 1.0
    for r in gross:
        geq *= 1 + r
    asset = [closes[i + 1] / closes[i] - 1 for i in range(train, len(closes) - 1)]   # buy-and-hold, same bars
    ann = cfg.bars_per_year
    at_costs = {}
    for bps in (10, 25, 45, 85):
        c = bps / 1e4
        at_costs[bps] = round(sharpe([(1 - c * u) * (1 + g) - 1 for g, u in zip(gross, turn)], ann), 3)
    years = len(net) / ann if net else 0.0
    return {"oos_bars": len(net), "trades": trades, "signal_trades": sig_trades, "rebalance_trades": trades - sig_trades,
            "oos_sharpe": sharpe(net, ann), "gross_sharpe": sharpe(gross, ann), "oos_return": eq - 1,
            "gross_return": geq - 1, "cost_drag_per_year": (mean(gross) - mean(net)) * ann if net else 0.0,
            "turnover_per_year": sum(turn) / years if years else 0.0, "max_drawdown": max_drawdown(curve),
            "halted": state.halted_at is not None, "braked_share": braked / len(net) if net else 0.0,
            "avg_exposure": exposure / len(net) if net else 0.0,
            "psr": probabilistic_sharpe(net), "dsr": deflated_sharpe(net, n_trials), "n_trials": n_trials,
            "trials": len(sigs), "folds": folds, "buy_hold_sharpe": sharpe(asset, ann),
            "buy_hold_return": closes[-1] / closes[train] - 1 if len(closes) > train else 0.0,
            "sharpe_at_costs_bps": at_costs, "costs_bps": cfg.fee_bps + cfg.slippage_bps}


T2_METRICS = ("trades", "oos_sharpe", "gross_sharpe", "oos_return", "max_drawdown", "psr", "dsr", "n_trials", "trials",
              "buy_hold_sharpe", "cost_drag_per_year", "turnover_per_year", "avg_exposure", "sharpe_at_costs_bps",
              "costs_bps", "halted")


def t2_gate(report: dict, min_trades: int = 1000, max_dd: float = 0.20) -> GateResult:
    """The ratified T2 gate: >= 1,000 out-of-sample trades, positive Sharpe, max drawdown < 20%."""
    reasons = []
    if report["trades"] < min_trades:
        reasons.append(f"{report['trades']} out-of-sample trades < {min_trades}")
    if report["oos_sharpe"] <= 0:
        reasons.append(f"out-of-sample Sharpe {report['oos_sharpe']:.3f} is not positive")
    if report["max_drawdown"] >= max_dd:
        reasons.append(f"max drawdown {report['max_drawdown']:.1%} >= {max_dd:.0%}")
    return GateResult("T2", not reasons, {k: report[k] for k in T2_METRICS if k in report}, reasons)


def t2_strict_gate(report: dict, min_trades: int = 100, max_dd: float = 0.20, min_dsr: float = 0.95) -> GateResult:
    """Proposed T2 gate (advisory until the owner ratifies it), from the v0.4.1 gate audit:
      * skill that luck is unlikely to explain: deflated Sharpe >= 0.95 across every research run so far
        (replaces ">= 1,000 trades", which rewards turnover, the very thing costs punish);
      * value over simply holding: out-of-sample Sharpe above buy-and-hold's on the same bars;
      * risk: max drawdown < 20% and the drawdown halt never tripped;
      * a minimum sample of 100 out-of-sample trades."""
    reasons = []
    if report["trades"] < min_trades:
        reasons.append(f"{report['trades']} out-of-sample trades < {min_trades}")
    if report["max_drawdown"] >= max_dd or report.get("halted"):
        reasons.append(f"max drawdown {report['max_drawdown']:.1%} reached the {max_dd:.0%} limit")
    if report["dsr"] < min_dsr:
        reasons.append(f"deflated Sharpe {report['dsr']:.2f} < {min_dsr} (could be luck across {report['n_trials']} "
                       f"research run(s))")
    if report["oos_sharpe"] <= report["buy_hold_sharpe"]:
        reasons.append(f"Sharpe {report['oos_sharpe']:.2f} does not beat buy-and-hold {report['buy_hold_sharpe']:.2f}")
    return GateResult("T2-proposed", not reasons, {k: report[k] for k in T2_METRICS if k in report}, reasons)


def sentiment_experiment(closes: list[float], fear_greed: list[float | None], cfg: SimConfig | None = None,
                         train: int = 365, test: int = 90) -> dict:
    """The first sealed experiment: does daily sentiment improve out-of-sample risk-adjusted return?
    Sentiment enters only as sigma inflation (exposure can shrink, never grow)."""
    cfg = cfg or SimConfig()
    scale = [cfg.contract.sentiment_sigma(1.0, fg) for fg in fear_greed]
    base = walk_forward(closes, cfg, train, test)
    with_s = walk_forward(closes, cfg, train, test, sigma_scale=scale)
    return {"baseline_sharpe": base["oos_sharpe"], "sentiment_sharpe": with_s["oos_sharpe"],
            "baseline_dd": base["max_drawdown"], "sentiment_dd": with_s["max_drawdown"],
            "improves": with_s["oos_sharpe"] > base["oos_sharpe"],
            "next": "buy intraday social data only if this improves out of sample across folds"}


def controlled_closes(n: int, seed: int, vol: float = 0.006, trend: float = 0.0, trend_len: float = 500.0,
                      start: float = 100.0) -> list[float]:
    """Controlled synthetic prices for checking the gates. Log return = regime drift + noise. trend = 0 is pure
    noise (no edge exists). trend > 0 plants persistent up and down regimes (mean length `trend_len` bars) that a
    trend-following strategy can, in principle, find."""
    import random
    rng = random.Random(seed)
    out, sign = [start], 1.0
    for _ in range(n - 1):
        if trend and rng.random() < 1.0 / trend_len:
            sign = -sign
        out.append(out[-1] * math.exp(sign * trend + rng.gauss(0.0, vol)))
    return out


def gate_controls(seeds: int = 20, bars: int = 40_000, train: int = 2_160, test: int = 720, trend: float = 0.0006,
                  cfg: SimConfig | None = None) -> dict:
    """Check the gates themselves: how often does each pass on pure noise (false positives), and on data with a
    planted edge (power)? A good gate rarely passes noise and usually passes a real edge."""
    cfg = cfg or SimConfig(bars_per_year=8760.0)
    out = {}
    for name, tr in (("noise", 0.0), ("planted_trend", trend)):
        ratified = strict = 0
        sharpes, trades = [], []
        for k in range(seeds):
            rep = walk_forward(controlled_closes(bars, 1000 + k, trend=tr), cfg, train, test)
            ratified += t2_gate(rep).passed
            strict += t2_strict_gate(rep).passed
            sharpes.append(rep["oos_sharpe"])
            trades.append(rep["trades"])
        out[name] = {"ratified_pass_rate": ratified / seeds, "strict_pass_rate": strict / seeds,
                     "median_oos_sharpe": round(sorted(sharpes)[seeds // 2], 3),
                     "median_trades": sorted(trades)[seeds // 2], "seeds": seeds}
    return out


def synthetic_closes(n: int, seed: int = 7, drift: float = 0.0004, vol: float = 0.03, start: float = 100.0) -> list[float]:
    """Deterministic geometric random walk with regime changes (tests and demos only; never research input)."""
    import random
    rng = random.Random(seed)
    out, p = [start], start
    for i in range(n - 1):
        regime = 1.0 if (i // 120) % 3 else -0.5
        p *= math.exp(rng.gauss(drift * regime, vol))
        out.append(p)
    return out
