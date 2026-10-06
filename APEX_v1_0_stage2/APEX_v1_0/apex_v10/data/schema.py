"""v1.0 additive schema. Applied only to the copy (market_2026-10-03_v10.sqlite); legacy tables are untouched."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

QUALITIES = "('exact_release','source_timestamp','conservative_lag','approximate')"

DDL = f"""
CREATE TABLE schema_version(
    version TEXT PRIMARY KEY, applied_utc TEXT NOT NULL, parent_db_sha256 TEXT NOT NULL,
    script_sha256 TEXT NOT NULL, note TEXT) WITHOUT ROWID;

CREATE TABLE provenance(
    provenance_id TEXT PRIMARY KEY, source TEXT NOT NULL, endpoint TEXT NOT NULL, retrieved_ts INTEGER,
    raw_payload_sha256 TEXT, raw_path TEXT, third_party INTEGER NOT NULL DEFAULT 0, notes TEXT) WITHOUT ROWID;

CREATE TABLE funding_events(
    venue TEXT NOT NULL, symbol TEXT NOT NULL, funding_ts INTEGER NOT NULL, rate REAL NOT NULL,
    interval_s INTEGER, interval_source TEXT NOT NULL, rate_semantics TEXT NOT NULL,
    mark_price REAL, index_price REAL, published_ts INTEGER NOT NULL,
    availability_quality TEXT NOT NULL CHECK (availability_quality IN {QUALITIES}),
    provenance_id TEXT NOT NULL REFERENCES provenance(provenance_id),
    PRIMARY KEY (venue, symbol, funding_ts)) WITHOUT ROWID;

CREATE TABLE macro_observations(
    source TEXT NOT NULL, series_id TEXT NOT NULL, observation_ts INTEGER NOT NULL, published_ts INTEGER NOT NULL,
    retrieved_ts INTEGER NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL, vintage_or_release_id TEXT,
    raw_payload_sha256 TEXT NOT NULL,
    availability_quality TEXT NOT NULL CHECK (availability_quality IN {QUALITIES}),
    provenance_id TEXT NOT NULL REFERENCES provenance(provenance_id),
    CHECK (published_ts >= observation_ts),
    PRIMARY KEY (source, series_id, observation_ts, published_ts)) WITHOUT ROWID;

CREATE TABLE release_calendar(
    source TEXT NOT NULL, release_id TEXT NOT NULL, release_ts INTEGER NOT NULL, calendar_source TEXT NOT NULL,
    availability_quality TEXT NOT NULL CHECK (availability_quality IN {QUALITIES}),
    PRIMARY KEY (source, release_id)) WITHOUT ROWID;

CREATE TABLE reading_availability(
    source TEXT NOT NULL, metric TEXT NOT NULL, publish_lag_s INTEGER NOT NULL, publish_rule TEXT NOT NULL,
    availability_quality TEXT NOT NULL CHECK (availability_quality IN {QUALITIES}),
    semantics TEXT NOT NULL, rationale TEXT NOT NULL,
    PRIMARY KEY (source, metric)) WITHOUT ROWID;

CREATE TABLE data_families(
    family TEXT PRIMARY KEY, kind TEXT NOT NULL, table_name TEXT NOT NULL, selector TEXT NOT NULL,
    cadence TEXT NOT NULL, availability_quality TEXT NOT NULL CHECK (availability_quality IN {QUALITIES}),
    third_party INTEGER NOT NULL, description TEXT NOT NULL) WITHOUT ROWID;
"""

# Legacy `readings` carry a UTC day number only. These rules say when a day's value may be treated as known.
# None can be proven from the stored data, so all are tagged `approximate` and deliberately late.
LEGACY_READING_RULES = [
    ("attention", "wiki:Bitcoin", 2 * 86400, "day start + 48h",
     "Wikimedia daily pageviews for UTC day d (user agent), complete after d ends",
     "Wikimedia publishes daily aggregates after the day closes; exact posting time unknown"),
    ("attention", "wiki:Ethereum", 2 * 86400, "day start + 48h",
     "Wikimedia daily pageviews for UTC day d", "as above"),
    ("attention", "wiki:Cryptocurrency", 2 * 86400, "day start + 48h",
     "Wikimedia daily pageviews for UTC day d", "as above"),
    ("attention", "fear_greed", 6 * 3600, "day start + 6h",
     "alternative.me Fear & Greed value stamped at 00:00 UTC of day d",
     "the index is stamped at the start of its day; publication minutes later is plausible but unproven"),
    ("attention", "gdelt:bitcoin", 86400 + 6 * 3600, "day start + 30h",
     "GDELT DOC timeline raw article volume for UTC day d", "GDELT updates every 15 minutes; the day completes at d+1"),
    ("attention", "gdelt:cryptocurrency", 86400 + 6 * 3600, "day start + 30h",
     "GDELT DOC timeline raw article volume for UTC day d", "as above"),
    ("attention", "gdelt_tone:bitcoin", 86400 + 6 * 3600, "day start + 30h",
     "GDELT DOC timeline average tone for UTC day d", "as above"),
    ("onchain", "cm:AdrActCnt", 86400 + 12 * 3600, "day start + 36h",
     "Coin Metrics Community daily metric for UTC day d", "computed after the day closes; posting time unknown"),
    ("onchain", "cm:CapMVRVCur", 86400 + 12 * 3600, "day start + 36h", "Coin Metrics Community daily metric", "as above"),
    ("onchain", "cm:FlowInExNtv", 86400 + 12 * 3600, "day start + 36h", "Coin Metrics Community daily metric", "as above"),
    ("onchain", "cm:FlowOutExNtv", 86400 + 12 * 3600, "day start + 36h", "Coin Metrics Community daily metric", "as above"),
    ("onchain", "cm:SplyCur", 86400 + 12 * 3600, "day start + 36h", "Coin Metrics Community daily metric", "as above"),
    ("onchain", "cm:SplyExNtv", 86400 + 12 * 3600, "day start + 36h", "Coin Metrics Community daily metric", "as above"),
    ("funding", "funding:BTC-USD", 86400, "day start + 24h",
     "AGGREGATE: daily sum of Kraken Futures PF_XBTUSD hourly relativeFundingRate (written by APEX v0.5); NOT "
     "settlement events - must not drive the event-level execution engine",
     "complete when the UTC day ends"),
    ("funding", "funding:ETH-USD", 86400, "day start + 24h",
     "AGGREGATE: daily sum of Kraken Futures PF_ETHUSD hourly relativeFundingRate (written by APEX v0.5); NOT "
     "settlement events - must not drive the event-level execution engine",
     "complete when the UTC day ends"),
]


def apply(con: sqlite3.Connection) -> None:
    con.executescript(DDL)
    con.executemany("INSERT INTO reading_availability VALUES (?,?,?,?, 'approximate', ?, ?)",
                    [(s, m, lag, rule, sem, why) for s, m, lag, rule, sem, why in LEGACY_READING_RULES])


def logical_digest(con: sqlite3.Connection) -> dict[str, str]:
    """Content hash per table, independent of SQLite file layout/version: every row, ordered by all columns."""
    out = {}
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
              if r[0] != "schema_version"]                  # build-time metadata (wall-clock) is not content
    for t in tables:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
        h = hashlib.sha256()
        h.update(("|".join(cols) + "\n").encode())
        for row in con.execute(f"SELECT {', '.join(cols)} FROM {t} ORDER BY {', '.join(cols)}"):
            h.update((repr(row) + "\n").encode())
        out[t] = h.hexdigest()
    combined = hashlib.sha256("".join(f"{k}:{v}\n" for k, v in sorted(out.items())).encode()).hexdigest()
    out["__all__"] = combined
    return out


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()
