#!/usr/bin/env python3
"""APEX v1.0 Stage 0: verify the frozen v0.9 baseline without modifying it.

Checks
  1. every file listed in the package manifest and the v0.9 baseline manifest: present, size, SHA-256
  2. research/CHECKSUMS.txt entries (written with the original /mnt/data paths; matched here by file name)
  3. the frozen-spec hash quoted in research/README_HANDOFF.md
  4. the SQLite store against research/DATA_MANIFEST.json: file hash and size, table row counts, per-series row
     counts and first/last timestamps. The database is opened read-only and immutable (SQLite never writes to it).
  5. files present in baseline_v09/ that no manifest lists
It also records, without judging them, a few data observations that Stage 1 will need (calendar gaps).

Usage:  python3 stage0/verify_baseline.py [--root PACKAGE_ROOT] [--out stage0/outputs/baseline_verification.json]
Exit code 0 only if every check passes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

ADD_ONLY_DIRS = {"apex_v10", "stage0", "tests_v10"}          # Stage 0 additions; never part of the frozen package


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check_manifest(root: Path, manifest_path: Path) -> dict:
    doc = json.loads(manifest_path.read_text())
    base = manifest_path.parent
    rows, ok = [], True
    for entry in doc["files"]:
        p = base / entry["path"]
        row = {"path": str(p.relative_to(root)), "expected_sha256": entry["sha256"], "expected_bytes": entry["bytes"]}
        if not p.exists():
            row.update(present=False, pass_=False)
        else:
            actual = sha256(p)
            row.update(present=True, actual_sha256=actual, actual_bytes=p.stat().st_size,
                       pass_=(actual == entry["sha256"] and p.stat().st_size == entry["bytes"]))
        ok &= row["pass_"]
        rows.append(row)
    return {"manifest": str(manifest_path.relative_to(root)), "files": len(rows), "all_pass": ok,
            "failures": [r for r in rows if not r["pass_"]], "rows": rows}


def check_checksums_txt(root: Path) -> dict:
    base = root / "baseline_v09"
    out, ok = [], True
    for line in (base / "research" / "CHECKSUMS.txt").read_text().splitlines():
        if not line.strip():
            continue
        digest, original = line.split(None, 1)
        name = Path(original.strip()).name
        hits = [p for p in base.rglob(name) if p.is_file()]
        actual = sha256(hits[0]) if len(hits) == 1 else None
        row = {"original_path": original.strip(), "matched": [str(h.relative_to(root)) for h in hits],
               "expected_sha256": digest, "actual_sha256": actual, "pass_": actual == digest}
        ok &= row["pass_"]
        out.append(row)
    return {"all_pass": ok, "rows": out}


def check_frozen_spec(root: Path) -> dict:
    base = root / "baseline_v09" / "research"
    quoted = re.findall(r"\b[0-9a-f]{64}\b", (base / "README_HANDOFF.md").read_text())
    actual = sha256(base / "FROZEN_SPEC_v09.json")
    return {"quoted_in_README_HANDOFF": quoted, "actual_sha256": actual, "pass_": actual in quoted}


def open_readonly(db: Path) -> sqlite3.Connection:
    # immutable=1: SQLite treats the file as unchangeable (no locks, no journal, no writes of any kind)
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro&immutable=1", uri=True)


def check_database(root: Path) -> dict:
    base = root / "baseline_v09"
    man = json.loads((base / "research" / "DATA_MANIFEST.json").read_text())
    db = base / "data" / man["file"]
    res: dict = {"file": str(db.relative_to(root)), "expected_sha256": man["sha256"], "expected_bytes": man["size_bytes"]}
    res["actual_sha256"], res["actual_bytes"] = sha256(db), db.stat().st_size
    con = open_readonly(db)
    try:
        res["integrity_check"] = con.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in man["tables"]}
        res["tables"] = {t: {"expected": man["tables"][t]["rows"], "actual": n} for t, n in tables.items()}
        cand = {(r[0], r[1]): r[2:] for r in con.execute(
            "SELECT pair, interval, COUNT(*), MIN(ts), MAX(ts) FROM candles GROUP BY pair, interval")}
        bad_c = []
        for e in man["candles"]:
            a = cand.get((e["pair"], e["interval"]))
            if a != (e["rows"], e["min_ts"], e["max_ts"]):
                bad_c.append({"expected": e, "actual": a})
        rd = {(r[0], r[1]): r[2:] for r in con.execute(
            "SELECT source, metric, COUNT(*), MIN(ts), MAX(ts) FROM readings GROUP BY source, metric")}
        bad_r = []
        for e in man["readings"]:
            a = rd.get((e["source"], e["metric"]))
            if a != (e["rows"], e["min_day"], e["max_day"]):
                bad_r.append({"expected": e, "actual": a})
        res["series_mismatches"] = {"candles": bad_c, "readings": bad_r}
        # observations for Stage 1 (not pass/fail): missing calendar steps inside each series' own span
        gaps = []
        for (pair, interval), (n, lo, hi) in sorted(cand.items()):
            step = interval * 60
            expected = (hi - lo) // step + 1
            gaps.append({"pair": pair, "interval_min": interval, "rows": n, "expected_steps": expected,
                         "missing_steps": expected - n})
        rgaps = []
        for (src, metric), (n, lo, hi) in sorted(rd.items()):
            rgaps.append({"source": src, "metric": metric, "rows": n, "span_days": hi - lo + 1,
                          "missing_days": hi - lo + 1 - n})
        res["observations"] = {"candle_calendar_gaps": gaps, "reading_calendar_gaps": rgaps,
                               "readings_timestamp_unit": "day number (days since 1970-01-01 UTC); no publication time"}
    finally:
        con.close()
    res["pass_"] = (res["actual_sha256"] == res["expected_sha256"] and res["actual_bytes"] == res["expected_bytes"]
                    and res["integrity_check"] == "ok"
                    and all(v["expected"] == v["actual"] for v in res["tables"].values())
                    and not res["series_mismatches"]["candles"] and not res["series_mismatches"]["readings"])
    return res


def unlisted_files(root: Path) -> list[str]:
    listed = set()
    for m in (root / "PACKAGE_MANIFEST.json", root / "baseline_v09" / "PACKAGE_MANIFEST.json"):
        for e in json.loads(m.read_text())["files"]:
            listed.add((m.parent / e["path"]).resolve())
    out = []
    for p in root.rglob("*"):
        if p.is_file() and p.resolve() not in listed and p.name != "PACKAGE_MANIFEST.json" \
                and p.relative_to(root).parts[0] not in ADD_ONLY_DIRS:     # a stray __pycache__ is flagged too
            out.append(str(p.relative_to(root)))
    return sorted(out)


def tree_digest(root: Path) -> dict[str, str]:
    """SHA-256 of every file under baseline_v09/ (used before/after a run to prove nothing changed)."""
    base = root / "baseline_v09"
    return {str(p.relative_to(root)): sha256(p) for p in sorted(base.rglob("*")) if p.is_file()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    root = Path(a.root).resolve()
    report = {
        "stage": 0,
        "package_manifest": check_manifest(root, root / "PACKAGE_MANIFEST.json"),
        "baseline_manifest": check_manifest(root, root / "baseline_v09" / "PACKAGE_MANIFEST.json"),
        "checksums_txt": check_checksums_txt(root),
        "frozen_spec": check_frozen_spec(root),
        "database": check_database(root),
        "unlisted_files": unlisted_files(root),
    }
    for k in ("package_manifest", "baseline_manifest"):
        report[k].pop("rows")                     # keep the report readable; failures are kept in full
    report["all_pass"] = bool(report["package_manifest"]["all_pass"] and report["baseline_manifest"]["all_pass"]
                              and report["checksums_txt"]["all_pass"] and report["frozen_spec"]["pass_"]
                              and report["database"]["pass_"])
    out = Path(a.out) if a.out else root / "stage0" / "outputs" / "baseline_verification.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: (v.get("all_pass", v.get("pass_")) if isinstance(v, dict) else v)
                      for k, v in report.items()}, indent=2))
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
