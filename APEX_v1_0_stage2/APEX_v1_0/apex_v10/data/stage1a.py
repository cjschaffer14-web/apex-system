"""APEX v1.0 Stage 1A evidence-closure database build.

Add-only relative to the accepted Stage 1 snapshot: copy the accepted Stage 1 DB, add value-vintage semantics,
recover H.4.1 first prints from the Board's archived releases, and write a new manifest. No Stage 1 file is edited.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from .archive import RawArchive
from . import schema
from .build import AS_OF_TS
from .sources.common import MACRO_COLUMNS, PROVENANCE_COLUMNS
from .sources.h41_releases import fed_h41_first_release, parse_release
from .timeutil import et_ts

STAGE1_DB_REL = "data_v10/market_2026-10-03_v10.sqlite"
STAGE1_FILE_SHA256 = "2b5f420cebe5823f1e11653ffdcfaf548364d8c2ee4de923d2183d9721ac7e8e"
STAGE1_LOGICAL_SHA256 = "b6be7251b11c5a3598d4d718f9b874505c1c4ddf346250637bf653617fb76c51"
TARGET_DB_REL = "data_v10/market_2026-10-03_v10_1a.sqlite"
RAW_1A_REL = "data_v10/raw_1a"
MANIFEST_REL = "data_v10/DB_MANIFEST_1A.json"
SCHEMA_VERSION = "1.0.1-stage1a"

VINTAGES = "('first_release','unrevised_since_release','market_record','latest_vintage','edited_after_release','unverified')"
REVISION_STATUSES = "('first_release_verified','source_event_record','no_known_revision_process','later_edit_detected','latest_vintage','unverified')"

CODE_FILES = [
    "apex_v10/interfaces_1a.py",
    "apex_v10/data/stage1a.py",
    "apex_v10/data/gate_1a.py",
    "apex_v10/data/sources/h41_releases.py",
]


def _sha_file(path: Path) -> str:
    return schema.file_sha256(path)


def code_sha256(root: Path) -> str:
    h = hashlib.sha256()
    for rel in CODE_FILES:
        p = root / rel
        if p.exists():
            h.update(rel.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def _add_columns(con: sqlite3.Connection) -> None:
    # Existing Stage 1 rows receive conservative defaults, then are classified explicitly below.
    con.execute(f"ALTER TABLE macro_observations ADD COLUMN value_vintage_quality TEXT NOT NULL DEFAULT 'unverified' CHECK(value_vintage_quality IN {VINTAGES})")
    con.execute("ALTER TABLE macro_observations ADD COLUMN availability_time_quality TEXT GENERATED ALWAYS AS (availability_quality) VIRTUAL")
    con.execute(f"ALTER TABLE funding_events ADD COLUMN value_vintage_quality TEXT NOT NULL DEFAULT 'market_record' CHECK(value_vintage_quality IN {VINTAGES})")
    con.execute("ALTER TABLE funding_events ADD COLUMN availability_time_quality TEXT GENERATED ALWAYS AS (availability_quality) VIRTUAL")
    con.execute(f"ALTER TABLE data_families ADD COLUMN value_vintage_quality TEXT NOT NULL DEFAULT 'unverified' CHECK(value_vintage_quality IN {VINTAGES})")
    con.execute("ALTER TABLE data_families ADD COLUMN evidence_grade INTEGER NOT NULL DEFAULT 0 CHECK(evidence_grade IN (0,1))")
    con.executescript(f"""
    CREATE TABLE vintage_policy(
        family TEXT PRIMARY KEY,
        value_vintage_quality TEXT NOT NULL CHECK(value_vintage_quality IN {VINTAGES}),
        revision_status TEXT NOT NULL CHECK(revision_status IN {REVISION_STATUSES}),
        evidence_eligible INTEGER NOT NULL CHECK(evidence_eligible IN (0,1)),
        rationale TEXT NOT NULL
    ) WITHOUT ROWID;

    CREATE TABLE macro_revisions(
        source TEXT NOT NULL,
        series_id TEXT NOT NULL,
        observation_ts INTEGER NOT NULL,
        first_release_ts INTEGER,
        first_release_value REAL,
        first_release_provenance_id TEXT,
        second_release_ts INTEGER,
        second_release_value REAL,
        second_release_provenance_id TEXT,
        latest_value REAL,
        latest_retrieved_ts INTEGER,
        first_to_second_delta REAL,
        first_to_latest_delta REAL,
        PRIMARY KEY(source, series_id, observation_ts)
    ) WITHOUT ROWID;
    """)


def _classify_stage1_rows(con: sqlite3.Connection) -> None:
    con.execute("UPDATE macro_observations SET value_vintage_quality='latest_vintage' WHERE source='fed_h41'")
    con.execute("UPDATE macro_observations SET value_vintage_quality=CASE WHEN availability_quality='approximate' THEN 'edited_after_release' ELSE 'unrevised_since_release' END WHERE source='nyfed'")
    con.execute("UPDATE macro_observations SET value_vintage_quality='unverified' WHERE source='treasury_fiscaldata'")
    con.execute("UPDATE macro_observations SET value_vintage_quality='market_record' WHERE source IN ('treasury_yields','cboe')")
    con.execute("UPDATE funding_events SET value_vintage_quality='market_record'")


def _release_days(con: sqlite3.Connection) -> list[dt.date]:
    return [dt.date.fromisoformat(x[0]) for x in con.execute(
        "SELECT release_id FROM release_calendar WHERE source='fed_h41' ORDER BY release_ts")]


def _insert_h41_first_releases(root: Path, con: sqlite3.Connection) -> dict:
    archive = RawArchive(root / RAW_1A_REL, mode="raw")
    res, audit = fed_h41_first_release(archive, AS_OF_TS, RAW_1A_REL, _release_days(con))
    bad = [a for a in audit if a.get("status") != "ok"]
    if bad:
        raise RuntimeError(f"H.4.1 first-release recovery incomplete: {len(bad)} failures: {bad[:3]}")
    con.executemany(
        f"INSERT OR IGNORE INTO provenance ({', '.join(PROVENANCE_COLUMNS)}) VALUES ({', '.join('?' * len(PROVENANCE_COLUMNS))})",
        sorted(res.provenance),
    )
    cols = list(MACRO_COLUMNS) + ["value_vintage_quality"]
    rows = [tuple(r) + ("first_release",) for r in res.macro]
    con.executemany(
        f"INSERT INTO macro_observations ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", rows
    )
    # Save corrected audit as a Stage 1A evidence artifact.
    (root / "data_v10/raw_1a/H41_FETCH_AUDIT_1A.json").write_text(json.dumps(audit, indent=2, sort_keys=True))
    return {"rows": len(rows), "payloads": len(res.provenance), "audit_failures": 0}


def _build_h41_revisions(root: Path, con: sqlite3.Connection) -> dict:
    audit = json.loads((root / "data_v10/raw_1a/H41_FETCH_AUDIT_1A.json").read_text())
    ok = [a for a in audit if a.get("status") == "ok"]
    by_w = {dt.date.fromisoformat(a["wednesday"]): a for a in ok}
    latest = {int(o): (float(v), int(r)) for o, v, r in con.execute(
        "SELECT observation_ts,value,retrieved_ts FROM macro_observations WHERE source='fed_h41' AND series_id='RESPPMA_N.WW'")}
    first_rows = {int(o): (int(p), float(v), prov) for o, p, v, prov in con.execute(
        "SELECT observation_ts,published_ts,value,provenance_id FROM macro_observations WHERE source='fed_h41_first_release' AND series_id='RESPPMA_N.WW'")}
    rows = []
    for w, a in sorted(by_w.items()):
        obs = et_ts(w + dt.timedelta(days=1), 0, 0)
        f_pub, f_val, f_prov = first_rows[obs]
        nxt = by_w.get(w + dt.timedelta(days=7))
        s_pub = s_val = s_prov = None
        if nxt is not None:
            s_pub = int(nxt["published_ts"])
            s_val = float(nxt["implied_prior_musd"]) * 1e6
            # The next week's first-release page is the provenance of this second print.
            row = con.execute("SELECT provenance_id FROM macro_observations WHERE source='fed_h41_first_release' AND published_ts=? LIMIT 1", (s_pub,)).fetchone()
            s_prov = row[0] if row else None
        l_val, l_ret = latest.get(obs, (None, None))
        rows.append(("fed_h41", "RESPPMA_N.WW", obs, f_pub, f_val, f_prov, s_pub, s_val, s_prov, l_val, l_ret,
                     None if s_val is None else s_val - f_val,
                     None if l_val is None else l_val - f_val))
    con.executemany("INSERT INTO macro_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    changed_second = sum(1 for r in rows if r[7] is not None and r[7] != r[4])
    changed_latest = sum(1 for r in rows if r[9] is not None and r[9] != r[4])
    return {"rows": len(rows), "changed_by_second_print": changed_second, "changed_by_latest_vintage": changed_latest}


def _policies(con: sqlite3.Connection) -> list[tuple]:
    rows = []
    for fam, kind, quality in con.execute("SELECT family,kind,availability_quality FROM data_families ORDER BY family"):
        if kind == "candles":
            v, rs, ok, why = "market_record", "source_event_record", 1, "Exchange OHLCV history treated as the canonical market record; retrospective source corrections remain possible."
        elif kind == "funding":
            v, rs, ok, why = "market_record", "source_event_record", 1, "Venue-tagged funding history is a source event record; no claim of immutable vendor storage."
        elif kind == "readings":
            if ":cm:" in fam or fam.startswith("readings:onchain:"):
                v, rs, ok, why = "latest_vintage", "latest_vintage", 0, "Legacy Coin Metrics values have no stored historical vintage."
            else:
                v, rs, ok, why = "unverified", "unverified", 0, "Legacy day-stamped reading lacks a verified publication/vintage record."
        elif fam.startswith("macro:fed_h41_first_release:"):
            v, rs, ok, why = "first_release", "first_release_verified", 1, "Value parsed from the Board's archived first H.4.1 release after the observation Wednesday."
        elif fam.startswith("macro:fed_h41:"):
            v, rs, ok, why = "latest_vintage", "latest_vintage", 0, "DDP value is latest vintage even though its release time is exact."
        elif fam.startswith("macro:nyfed:"):
            v, rs, ok, why = "unrevised_since_release", "no_known_revision_process", 1, "Rows whose source lastUpdated is same-day are admissible; edited rows are downgraded row-wise."
        elif fam.startswith("macro:treasury_fiscaldata:"):
            v, rs, ok, why = "unverified", "unverified", 0, "TGA first-print archive was not available in this environment; excluded from evidence-grade use."
        elif fam.startswith("macro:treasury_yields:") or fam.startswith("macro:cboe:"):
            v, rs, ok, why = "market_record", "no_known_revision_process", 1, "Originator historical market series treated as canonical market record; no first-print archive was used."
        else:
            v, rs, ok, why = "unverified", "unverified", 0, "No Stage 1A vintage policy."
        rows.append((fam, v, rs, ok, why))
    return rows


def _register_first_release_family(con: sqlite3.Connection) -> None:
    fam = "macro:fed_h41_first_release:RESPPMA_N.WW"
    con.execute("INSERT OR REPLACE INTO data_families(family,kind,table_name,selector,cadence,availability_quality,value_vintage_quality,evidence_grade,third_party,description) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (fam, "macro", "macro_observations", json.dumps({"where":"source=? AND series_id=?","params":["fed_h41_first_release","RESPPMA_N.WW"]}, sort_keys=True),
                 "weekly", "exact_release", "first_release", 1, 0, "Federal Reserve H.4.1 total assets, first-release values from archived weekly releases"))


def _apply_family_policy(con: sqlite3.Connection) -> None:
    _register_first_release_family(con)
    rows = _policies(con)
    con.executemany("INSERT INTO vintage_policy VALUES (?,?,?,?,?)", rows)
    for fam, v, _rs, ok, _why in rows:
        con.execute("UPDATE data_families SET value_vintage_quality=?, evidence_grade=? WHERE family=?", (v, ok, fam))


def build(root: Path, force: bool = True) -> dict:
    root = Path(root)
    src, dst = root / STAGE1_DB_REL, root / TARGET_DB_REL
    if _sha_file(src) != STAGE1_FILE_SHA256:
        raise RuntimeError("accepted Stage 1 database file hash mismatch")
    # Verify the cross-machine logical hash before copying.
    c = sqlite3.connect(src)
    try:
        logical = schema.logical_digest(c)["__all__"]
    finally:
        c.close()
    if logical != STAGE1_LOGICAL_SHA256:
        raise RuntimeError(f"accepted Stage 1 logical hash mismatch: {logical}")
    if dst.exists():
        if not force:
            raise FileExistsError(dst)
        dst.unlink()
    shutil.copyfile(src, dst)
    con = sqlite3.connect(dst)
    try:
        _add_columns(con)
        _classify_stage1_rows(con)
        h41 = _insert_h41_first_releases(root, con)
        rev = _build_h41_revisions(root, con)
        _apply_family_policy(con)
        con.execute("INSERT INTO schema_version VALUES (?,?,?,?,?)",
                    (SCHEMA_VERSION, dt.datetime.fromtimestamp(AS_OF_TS, dt.timezone.utc).isoformat(timespec="seconds"),
                     STAGE1_FILE_SHA256, code_sha256(root), "Stage 1A evidence closure; parent is accepted Stage 1 DB"))
        con.commit()
        con.execute("VACUUM")
        con.commit()
        logical1a = schema.logical_digest(con)
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk = len(con.execute("PRAGMA foreign_key_check").fetchall())
        counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
                  ("candles","readings","funding_events","macro_observations","macro_revisions","provenance","data_families","vintage_policy")}
    finally:
        con.close()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "parent_stage1_file_sha256": STAGE1_FILE_SHA256,
        "parent_stage1_logical_sha256": STAGE1_LOGICAL_SHA256,
        "file": TARGET_DB_REL,
        "file_sha256": _sha_file(dst),
        "logical_sha256": logical1a["__all__"],
        "per_table_logical_sha256": {k:v for k,v in logical1a.items() if k != "__all__"},
        "counts": counts,
        "integrity_check": integrity,
        "foreign_key_violations": fk,
        "h41_first_release": h41,
        "h41_revisions": rev,
        "code_sha256": code_sha256(root),
        "as_of_ts": AS_OF_TS,
    }
    (root / MANIFEST_REL).write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
