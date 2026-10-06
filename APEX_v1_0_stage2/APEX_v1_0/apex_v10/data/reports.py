"""Stage 1 reports: coverage by source/asset/date, the coverage gate, and data quality/provenance checks."""
from __future__ import annotations

import datetime as dt
import gzip
import json
import sqlite3
from collections import Counter
from pathlib import Path

from . import schema
from .build import AS_OF_TS, BASELINE_DB_REL, BASELINE_DB_SHA256, RAW_REL, TARGET_DB_REL
from .coverage import STANDARD_WINDOWS, _times, discover_families, gate_report

UTC = dt.timezone.utc


def iso(ts: int | None) -> str | None:
    return dt.datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M") if ts is not None else None


def coverage(con: sqlite3.Connection) -> dict:
    out = {}
    for f in discover_families(con):
        ts = _times(con, f)
        gaps = Counter(b - a for a, b in zip(ts, ts[1:]))
        q = Counter()
        if f.kind in ("funding", "macro"):
            q = Counter(dict(con.execute(f"SELECT availability_quality, COUNT(*) FROM {f.table} WHERE {f.where} GROUP BY 1",
                                         f.params).fetchall()))
        else:
            q = Counter({f.quality: len(ts)})
        step = int(f.cadence.split(":")[1]) if f.cadence.startswith("step:") else None
        missing = sum((g // step - 1) * n for g, n in gaps.items() if step and g > step) if step else None
        out[f.family] = {"kind": f.kind, "cadence": f.cadence, "rows": len(ts), "first": iso(ts[0]) if ts else None,
                         "last": iso(ts[-1]) if ts else None, "missing_steps": missing,
                         "most_common_spacing_s": [list(x) for x in gaps.most_common(3)],
                         "availability_quality": dict(q)}
    return out


def _raw_payloads(root: Path, source: str) -> list[tuple[dict, bytes]]:
    man = [json.loads(l) for l in (root / RAW_REL / "MANIFEST.jsonl").read_text().splitlines() if l.strip()]
    return [(m, gzip.decompress((root / RAW_REL / m["path"]).read_bytes())) for m in man if m["source"] == source]


def data_quality(root: Path, con: sqlite3.Connection) -> dict:
    q: dict = {}
    src = root / BASELINE_DB_REL
    q["frozen_db_sha256"] = schema.file_sha256(src)
    q["frozen_db_unchanged"] = q["frozen_db_sha256"] == BASELINE_DB_SHA256
    fro = sqlite3.connect(f"file:{src.as_posix()}?mode=ro&immutable=1", uri=True)
    a, b = schema.logical_digest(fro), schema.logical_digest(con)
    fro.close()
    q["legacy_tables_identical"] = {t: a[t] == b[t] for t in ("candles", "readings", "imports")}
    # keys and ordering
    dup = {}
    for t, key in (("funding_events", "venue, symbol, funding_ts"),
                   ("macro_observations", "source, series_id, observation_ts, published_ts"),
                   ("candles", "source, pair, interval, ts"), ("readings", "source, metric, ts")):
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        d = con.execute(f"SELECT COUNT(*) FROM (SELECT DISTINCT {key} FROM {t})").fetchone()[0]
        dup[t] = n - d
    q["duplicate_keys"] = dup
    q["future_rows_after_as_of"] = {
        "funding_events": con.execute("SELECT COUNT(*) FROM funding_events WHERE funding_ts > ? OR published_ts > ?",
                                      (AS_OF_TS, AS_OF_TS)).fetchone()[0],
        "macro_observations": con.execute("SELECT COUNT(*) FROM macro_observations WHERE published_ts > ?",
                                          (AS_OF_TS,)).fetchone()[0]}
    q["published_before_observation"] = con.execute(
        "SELECT COUNT(*) FROM macro_observations WHERE published_ts < observation_ts").fetchone()[0]
    # funding semantics, interval changes, stream ends, misaligned stamps
    fund = {}
    for venue, sym in con.execute("SELECT DISTINCT venue, symbol FROM funding_events ORDER BY 1,2").fetchall():
        rows = con.execute("SELECT funding_ts, interval_s, rate_semantics FROM funding_events WHERE venue=? AND symbol=? "
                           "ORDER BY funding_ts", (venue, sym)).fetchall()
        changes, prev = [], None
        for t, i, _ in rows:
            if venue == "bitmex" and i != prev:
                changes.append({"from": iso(t), "interval_s": i})
                prev = i
        gaps = Counter(b[0] - a[0] for a, b in zip(rows, rows[1:]))
        fund[f"{venue}:{sym}"] = {
            "rows": len(rows), "first": iso(rows[0][0]), "last": iso(rows[-1][0]),
            "days_stale_at_as_of": round((AS_OF_TS - rows[-1][0]) / 86400, 1),
            "rate_semantics": rows[0][2], "interval_changes": changes,
            "irregular_spacings": {str(k): v for k, v in gaps.items() if k not in (3600, 28800)},
            "non_hour_aligned_stamps": sum(1 for t, _, _ in rows if t % 3600)}
    q["funding"] = fund
    # macro timing
    mac = {}
    for s_, sid in con.execute("SELECT DISTINCT source, series_id FROM macro_observations ORDER BY 1,2").fetchall():
        lags = sorted(p - o for o, p in con.execute(
            "SELECT observation_ts, published_ts FROM macro_observations WHERE source=? AND series_id=?", (s_, sid)))
        qual = dict(con.execute("SELECT availability_quality, COUNT(*) FROM macro_observations WHERE source=? AND "
                                "series_id=? GROUP BY 1", (s_, sid)).fetchall())
        mac[f"{s_}:{sid}"] = {"rows": len(lags), "publication_lag_hours_median": round(lags[len(lags) // 2] / 3600, 2),
                              "publication_lag_hours_max": round(lags[-1] / 3600, 2), "availability_quality": qual}
    q["macro"] = mac
    # TGA layout seams: the closing balance before each seam must equal the opening balance after it
    seams = []
    payloads = _raw_payloads(root, "treasury_fiscaldata")
    rows = []
    for _, body in payloads:
        rows += json.loads(body)["data"]
    idx = {}
    for r in rows:
        idx.setdefault((r["record_date"], r["account_type"]), r)
    for last_day, last_acct, first_day, first_acct, first_field in (
            ("2021-09-30", "Federal Reserve Account", "2021-10-01", "Treasury General Account (TGA)", "open_today_bal"),
            ("2022-04-15", "Treasury General Account (TGA)", "2022-04-18", "Treasury General Account (TGA) Opening Balance",
             "open_today_bal")):
        a_ = idx.get((last_day, last_acct)) or {}
        b_ = idx.get((first_day, first_acct)) or {}
        seams.append({"seam": f"{last_day} -> {first_day}", "close_before": a_.get("close_today_bal"),
                      "open_after": b_.get(first_field), "continuous": a_.get("close_today_bal") == b_.get(first_field)})
    q["tga_layout_seams"] = seams
    # H.4.1 release mapping
    rel = con.execute("SELECT COUNT(*) FROM release_calendar WHERE source='fed_h41'").fetchone()[0]
    q["fed_h41_release_calendar_rows"] = rel
    # legacy readings
    q["legacy_reading_rules"] = [dict(zip(("source", "metric", "publish_lag_s", "publish_rule", "quality"), r)) for r in
                                 con.execute("SELECT source, metric, publish_lag_s, publish_rule, availability_quality "
                                             "FROM reading_availability ORDER BY 1,2")]
    q["not_ingested"] = {
        "binance_funding": "HTTP 451 'restricted location' from a US network; not circumvented",
        "bybit_funding": "HTTP 403 (geo-blocked) from a US network; not circumvented",
        "dxy_equity_indexes": "deferred from Stage 1 (no free originator source; third-party provenance would be weak)",
        "fred": "not used (direct sources preferred by owner decision)"}
    return q


SOURCE_RULES = {   # what each provenance source is, and how its availability time is set (see the adapter docstrings)
    "bitmex": ("BitMEX public REST /api/v1/funding (originator)", "funding settlement events XBTUSD/ETHUSD; interval "
               "from the per-event `fundingInterval` field; available at the settlement timestamp (source_timestamp)"),
    "deribit": ("Deribit public API get_funding_rate_history (originator)", "continuous funding sampled hourly "
                "(interest_1h); not discrete settlements; available at the sample timestamp (source_timestamp)"),
    "kraken_futures": ("Kraken Futures /derivatives/api/v4/historicalfundingrates (originator)", "hourly relative "
                       "funding rate; interval derived from spacing; the API returns about 12 months"),
    "coinbase_intx": ("Coinbase International /api/v1/instruments/{id}/funding (originator)", "hourly funding with mark "
                      "price; interval derived from spacing; history from March 2023"),
    "fed_h41": ("Federal Reserve Data Download Program, H.4.1 package + H.4.1 release-date archive (originator)",
                "RESPPMA_N.WW Wednesday level; available 16:30 ET on the release date listed by the Fed (exact_release); "
                "value is the latest vintage at retrieval"),
    "nyfed": ("NY Fed Markets API, reverse repo operation results (originator)", "total accepted per operation date; "
              "available at the record's same-day lastUpdated stamp (source_timestamp); records edited on a later date "
              "are tagged approximate"),
    "treasury_fiscaldata": ("US Treasury Fiscal Data API, Daily Treasury Statement operating cash balance (originator)",
                            "TGA closing balance, three account layouts spliced only at verified seams; available 17:00 ET "
                            "next federal business day (conservative_lag)"),
    "treasury_yields": ("home.treasury.gov daily par yield curve CSV (originator)", "2-year and 10-year par yields; "
                        "available 20:00 ET same day (conservative_lag)"),
    "cboe": ("CBOE VIX_History.csv (originator)", "VIX daily close; available 17:00 ET same day (conservative_lag)"),
}


def source_provenance(root: Path, con: sqlite3.Connection) -> dict:
    """Per source: originator, endpoints, payloads and bytes in the raw archive, retrieval window, rows, span, quality."""
    man = [json.loads(l) for l in (root / RAW_REL / "MANIFEST.jsonl").read_text().splitlines() if l.strip()]
    out = {}
    for src, n, r0, r1, third in con.execute("SELECT source, COUNT(*), MIN(retrieved_ts), MAX(retrieved_ts), "
                                             "SUM(third_party) FROM provenance GROUP BY source ORDER BY source"):
        ids = [r[0] for r in con.execute("SELECT provenance_id FROM provenance WHERE source=?", (src,))]
        marks = ",".join("?" * len(ids))
        rows, q, span, series = 0, Counter(), [None, None], set()
        for table, tcol, scol in (("funding_events", "funding_ts", "venue || ':' || symbol"),
                                  ("macro_observations", "observation_ts", "source || ':' || series_id")):
            for s_, k, a, b, qual in con.execute(
                    f"SELECT {scol}, COUNT(*), MIN({tcol}), MAX({tcol}), availability_quality FROM {table} "
                    f"WHERE provenance_id IN ({marks}) GROUP BY 1, 5", ids):
                rows += k
                q[qual] += k
                series.add(s_)
                span = [a if span[0] is None else min(span[0], a), b if span[1] is None else max(span[1], b)]
        endpoints = sorted({m["url"].split("?")[0] for m in man if m["source"] == src})
        origin, rule = SOURCE_RULES.get(src, ("unknown", "unknown"))
        out[src] = {"originator": origin, "timing_and_semantics": rule, "third_party": bool(third),
                    "endpoints": endpoints, "payloads": n,
                    "payload_bytes": sum(m["bytes"] for m in man if m["source"] == src),
                    "retrieved_utc": [iso(r0), iso(r1)], "rows": rows, "series": sorted(series),
                    "first": iso(span[0]), "last": iso(span[1]), "availability_quality": dict(q),
                    "payloads_contributing_no_rows": n - len({r[0] for t in ("funding_events", "macro_observations") for r in
                                                        con.execute(f"SELECT DISTINCT provenance_id FROM {t} "
                                                                    f"WHERE provenance_id IN ({marks})", ids)})}
    return {"as_of_utc": iso(AS_OF_TS), "raw_archive": RAW_REL, "raw_manifest_entries": len(man),
            "note": "payloads_contributing_no_rows: empty windows before a venue's history starts (Deribit before "
                    "2019-04-30), the H.4.1 release-date file, and the TGA seam-validation request",
            "rule": "every funding and macro row names a provenance_id; every provenance_id names an archived raw "
                    "payload (sha256 + path); no value is entered by hand and no source is spliced across venues",
            "sources": out}


def coverage_md(cov: dict, gate: dict) -> str:
    lines = ["# Coverage by source, asset and date (v1.0 database)", "",
             f"Snapshot as of {iso(AS_OF_TS)} UTC. Every family listed with its span, gaps and availability quality.",
             "", "| Family | Rows | First | Last | Missing steps | Availability quality |", "|---|---|---|---|---|---|"]
    for k, v in cov.items():
        qual = ", ".join(f"{a}: {b}" for a, b in v["availability_quality"].items())
        lines.append(f"| {k} | {v['rows']:,} | {v['first']} | {v['last']} | "
                     f"{'' if v['missing_steps'] is None else v['missing_steps']} | {qual} |")
    lines += ["", "# Coverage gate (PASS / PARTIAL / FAIL)", "", "Windows: " +
              "; ".join(f"`{k}` {a} to {b}" for k, (a, b) in STANDARD_WINDOWS.items()), "",
              "| Family | " + " | ".join(STANDARD_WINDOWS) + " |", "|---|" + "---|" * len(STANDARD_WINDOWS)]
    for fam, v in gate["families"].items():
        lines.append(f"| {fam} | " + " | ".join(v["windows"][w]["status"] for w in STANDARD_WINDOWS) + " |")
    lines += ["", "Reasons for every PARTIAL/FAIL are in `reports/coverage_gate_v10.json`."]
    return "\n".join(lines) + "\n"


def write_all(root: Path) -> dict:
    con = sqlite3.connect(f"file:{(root / TARGET_DB_REL).as_posix()}?mode=ro", uri=True)
    try:
        cov = coverage(con)
        gate = gate_report(con)
        dq = data_quality(root, con)
        prov = source_provenance(root, con)
    finally:
        con.close()
    rep = root / "reports"
    rep.mkdir(exist_ok=True)
    (rep / "source_provenance_v10.json").write_text(json.dumps(prov, indent=1))
    (rep / "coverage_v10.json").write_text(json.dumps(cov, indent=1))
    (rep / "coverage_gate_v10.json").write_text(json.dumps(gate, indent=1))
    (rep / "data_quality_v10.json").write_text(json.dumps(dq, indent=1))
    (rep / "coverage_v10.md").write_text(coverage_md(cov, gate))
    status = Counter(w["status"] for f in gate["families"].values() for w in f["windows"].values())
    return {"families": len(cov), "gate_status_counts": dict(status), "frozen_db_unchanged": dq["frozen_db_unchanged"],
            "legacy_tables_identical": dq["legacy_tables_identical"], "duplicate_keys": dq["duplicate_keys"],
            "future_rows_after_as_of": dq["future_rows_after_as_of"]}
