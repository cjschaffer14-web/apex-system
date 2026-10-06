"""Stage 1 database build: clone the frozen v0.9 store, add the v1.0 schema, ingest sources, finalize.

The frozen database is never opened for writing: it is hashed, byte-copied, and hashed again. Every step is
deterministic given the raw archive, so `--mode raw` reproduces the same logical content on any machine.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from . import schema
from .archive import RawArchive
from .coverage import discover_families
from .sources import funding as F
from .sources import macro as M
from .sources.common import FUNDING_COLUMNS, MACRO_COLUMNS, PROVENANCE_COLUMNS, RELEASE_COLUMNS, SourceResult

BASELINE_DB_REL = "baseline_v09/data/market_2026-10-03.sqlite"
BASELINE_DB_SHA256 = "ac53b123361e5de0f4aa00530cbe1c35286cfd3959224d4e2bf845f634267596"
TARGET_DB_REL = "data_v10/market_2026-10-03_v10.sqlite"
RAW_REL = "data_v10/raw"
MANIFEST_REL = "data_v10/DB_MANIFEST.json"
SCHEMA_VERSION = "1.0.0-stage1"
# The frozen database ends with the hourly bar opening 2026-10-03 01:00 UTC; nothing published after that bar
# closes enters the v1.0 snapshot, so a later rerun cannot leak newer data into it.
AS_OF_TS = int(dt.datetime(2026, 10, 3, 2, 0, tzinfo=dt.timezone.utc).timestamp())

ADAPTER_ORDER = [("bitmex", F.bitmex), ("deribit", F.deribit), ("kraken_futures", F.kraken_futures),
                 ("coinbase_intx", F.coinbase_intx), ("fed_h41", M.fed_h41), ("nyfed_rrp", M.nyfed_rrp),
                 ("treasury_tga", M.treasury_tga), ("treasury_yields", M.treasury_yields), ("cboe_vix", M.cboe_vix)]

CODE_FILES = ["apex_v10/interfaces.py", "apex_v10/data/build.py", "apex_v10/data/schema.py", "apex_v10/data/archive.py",
              "apex_v10/data/timeutil.py", "apex_v10/data/coverage.py", "apex_v10/data/sources/common.py",
              "apex_v10/data/sources/funding.py", "apex_v10/data/sources/macro.py"]


def code_sha256(root: Path) -> str:
    h = hashlib.sha256()
    for rel in CODE_FILES:
        h.update(rel.encode() + b"\0" + (root / rel).read_bytes() + b"\0")
    return h.hexdigest()


def migrate(root: Path, force: bool = False) -> dict:
    src = root / BASELINE_DB_REL
    dst = root / TARGET_DB_REL
    before = schema.file_sha256(src)
    if before != BASELINE_DB_SHA256:
        raise RuntimeError(f"frozen database hash mismatch: {before}")
    if dst.exists():
        if not force:
            raise FileExistsError(f"{dst} exists; pass force=True to rebuild it")
        dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)                               # byte copy; the source is only ever read
    if schema.file_sha256(dst) != BASELINE_DB_SHA256:
        raise RuntimeError("copy does not match the frozen database")
    con = sqlite3.connect(dst)
    try:
        legacy_before = schema.logical_digest(con)
        schema.apply(con)
        # applied_utc holds the snapshot's as-of time (not the wall clock), so a rebuild is byte-identical on the
        # same SQLite build; the wall-clock build time goes to DB_MANIFEST.json instead
        con.execute("INSERT INTO schema_version VALUES (?,?,?,?,?)",
                    (SCHEMA_VERSION, dt.datetime.fromtimestamp(AS_OF_TS, dt.timezone.utc).isoformat(timespec="seconds"),
                     BASELINE_DB_SHA256, code_sha256(root), "additive migration of the frozen v0.9 store"))
        con.commit()
    finally:
        con.close()
    after = schema.file_sha256(src)
    return {"source_sha256_before": before, "source_sha256_after": after, "source_unchanged": before == after,
            "legacy_logical_digest": {k: v for k, v in legacy_before.items() if k in ("candles", "readings", "imports")}}


def _insert(con: sqlite3.Connection, res: SourceResult) -> dict:
    con.executemany(f"INSERT OR IGNORE INTO provenance ({', '.join(PROVENANCE_COLUMNS)}) "
                    f"VALUES ({', '.join('?' * len(PROVENANCE_COLUMNS))})", sorted(res.provenance))
    if res.funding:
        con.executemany(f"INSERT INTO funding_events ({', '.join(FUNDING_COLUMNS)}) "
                        f"VALUES ({', '.join('?' * len(FUNDING_COLUMNS))})", sorted(res.funding, key=lambda r: r[:3]))
    if res.macro:
        con.executemany(f"INSERT INTO macro_observations ({', '.join(MACRO_COLUMNS)}) "
                        f"VALUES ({', '.join('?' * len(MACRO_COLUMNS))})", sorted(res.macro, key=lambda r: r[:4]))
    if res.releases:
        con.executemany(f"INSERT INTO release_calendar ({', '.join(RELEASE_COLUMNS)}) "
                        f"VALUES ({', '.join('?' * len(RELEASE_COLUMNS))})", sorted(res.releases))
    return {"funding_rows": len(res.funding), "macro_rows": len(res.macro), "release_rows": len(res.releases),
            "payloads": len(res.provenance), "notes": res.notes}


def ingest(root: Path, mode: str = "raw", only: list[str] | None = None, log=print) -> dict:
    archive = RawArchive(root / RAW_REL, mode=mode)
    con = sqlite3.connect(root / TARGET_DB_REL)
    report: dict = {"mode": mode, "as_of_ts": AS_OF_TS, "adapters": {}}
    try:
        for name, fn in ADAPTER_ORDER:
            if only and name not in only:
                continue
            res = fn(archive, AS_OF_TS, RAW_REL)
            report["adapters"][name] = _insert(con, res)
            con.commit()
            log(f"  {name}: {report['adapters'][name]['funding_rows'] + report['adapters'][name]['macro_rows']} rows "
                f"from {report['adapters'][name]['payloads']} payload(s)")
    finally:
        con.close()
    report["requests"] = len(archive.calls)
    return report


def finalize(root: Path) -> dict:
    dst = root / TARGET_DB_REL
    con = sqlite3.connect(dst)
    try:
        con.execute("DELETE FROM data_families")
        rows = []
        for f in discover_families(con):
            q = f.quality or "source_timestamp"
            if f.kind == "macro":
                q = max((r[0] for r in con.execute(
                    "SELECT DISTINCT availability_quality FROM macro_observations WHERE source=? AND series_id=?",
                    f.params)), key=lambda x: ["exact_release", "source_timestamp", "conservative_lag", "approximate"].index(x))
            rows.append((f.family, f.kind, f.table, json.dumps({"where": f.where, "params": list(f.params)}),
                         f.cadence, q, int(f.third_party), f.description))
        con.executemany("INSERT INTO data_families VALUES (?,?,?,?,?,?,?,?)", rows)
        con.commit()
        con.execute("VACUUM")
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        digest = schema.logical_digest(con)
        counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
                  [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]}
        sqlite_version = sqlite3.sqlite_version
    finally:
        con.close()
    manifest = {"file": TARGET_DB_REL, "file_sha256": schema.file_sha256(dst), "bytes": dst.stat().st_size,
                "logical_sha256": digest["__all__"], "table_logical_sha256": {k: v for k, v in digest.items() if k != "__all__"},
                "row_counts": counts, "integrity_check": integrity, "foreign_key_violations": len(fk),
                "parent_db_sha256": BASELINE_DB_SHA256, "schema_version": SCHEMA_VERSION, "as_of_ts": AS_OF_TS,
                "code_sha256": code_sha256(root), "sqlite_version": sqlite_version,
                "built_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "note": "file_sha256 depends on the SQLite build; logical_sha256 is the cross-machine reproducibility check"}
    (root / MANIFEST_REL).write_text(json.dumps(manifest, indent=2))
    return manifest
