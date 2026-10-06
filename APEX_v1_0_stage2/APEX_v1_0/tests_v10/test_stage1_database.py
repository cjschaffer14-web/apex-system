"""Stage 1: properties of the built v1.0 database, its provenance, its reports, and a full rebuild from the raw archive.

Requires the Stage 1 build (python3 scripts/build_stage1.py). The rebuild test re-ingests every source from
data_v10/raw into a temporary directory and must reproduce the logical hash recorded in DB_MANIFEST.json."""
import gzip
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apex_v10.data import build, schema                     # noqa: E402
from apex_v10.data.coverage import STANDARD_WINDOWS, discover_families  # noqa: E402

DB = ROOT / build.TARGET_DB_REL
MANIFEST = ROOT / build.MANIFEST_REL
VENUES = {"bitmex", "deribit", "kraken_futures", "coinbase_intx"}


@unittest.skipUnless(DB.exists() and MANIFEST.exists(), "run scripts/build_stage1.py first")
class Database(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.man = json.loads(MANIFEST.read_text())
        cls.con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def one(self, sql, *a):
        return self.con.execute(sql, a).fetchone()[0]

    def test_frozen_database_untouched(self):
        self.assertEqual(schema.file_sha256(ROOT / build.BASELINE_DB_REL), build.BASELINE_DB_SHA256)

    def test_manifest_matches_the_file(self):
        self.assertEqual(schema.file_sha256(DB), self.man["file_sha256"])
        d = schema.logical_digest(self.con)
        self.assertEqual(d["__all__"], self.man["logical_sha256"])
        self.assertEqual({k: v for k, v in d.items() if k != "__all__"}, self.man["table_logical_sha256"])
        for t, n in self.man["row_counts"].items():
            self.assertEqual(self.one(f"SELECT COUNT(*) FROM {t}"), n, t)
        self.assertEqual(self.man["parent_db_sha256"], build.BASELINE_DB_SHA256)

    def test_integrity_and_foreign_keys(self):
        self.assertEqual(self.one("PRAGMA integrity_check"), "ok")
        self.assertEqual(self.con.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_legacy_tables_identical_to_frozen(self):
        fro = sqlite3.connect(f"file:{(ROOT / build.BASELINE_DB_REL).as_posix()}?mode=ro&immutable=1", uri=True)
        a, b = schema.logical_digest(fro), schema.logical_digest(self.con)
        fro.close()
        for t in ("candles", "readings", "imports"):
            self.assertEqual(a[t], b[t], t)

    def test_schema_version_links_parent(self):
        row = self.con.execute("SELECT version, applied_utc, parent_db_sha256 FROM schema_version").fetchall()
        self.assertEqual(row, [(build.SCHEMA_VERSION, "2026-10-03T02:00:00+00:00", build.BASELINE_DB_SHA256)])

    def test_no_future_duplicate_or_inverted_rows(self):
        self.assertEqual(self.one("SELECT COUNT(*) FROM funding_events WHERE funding_ts>? OR published_ts>?",
                                  build.AS_OF_TS, build.AS_OF_TS), 0)
        self.assertEqual(self.one("SELECT COUNT(*) FROM macro_observations WHERE published_ts>?", build.AS_OF_TS), 0)
        self.assertEqual(self.one("SELECT COUNT(*) FROM macro_observations WHERE published_ts<observation_ts"), 0)
        self.assertEqual(self.one("SELECT COUNT(*) FROM funding_events WHERE published_ts<funding_ts"), 0)
        self.assertEqual(self.one("SELECT COUNT(*) FROM (SELECT source,pair,interval,ts FROM candles GROUP BY 1,2,3,4 "
                                  "HAVING COUNT(*)>1)"), 0)

    def test_availability_quality_is_mandatory(self):
        for t in ("funding_events", "macro_observations", "release_calendar", "reading_availability", "data_families"):
            self.assertEqual(self.one(f"SELECT COUNT(*) FROM {t} WHERE availability_quality IS NULL OR availability_quality "
                                      "NOT IN ('exact_release','source_timestamp','conservative_lag','approximate')"), 0, t)
        self.assertEqual(self.one("SELECT COUNT(DISTINCT availability_quality) FROM reading_availability"), 1)
        self.assertEqual(self.one("SELECT availability_quality FROM reading_availability LIMIT 1"), "approximate")

    def test_every_value_traces_to_an_archived_payload(self):
        ids = {r[0] for r in self.con.execute("SELECT provenance_id FROM funding_events UNION "
                                              "SELECT provenance_id FROM macro_observations")}
        prov = {r[0]: r[1:] for r in self.con.execute("SELECT provenance_id, raw_payload_sha256, raw_path FROM provenance")}
        self.assertTrue(ids <= set(prov))
        for pid, (sha, path) in prov.items():
            body = gzip.decompress((ROOT / path).read_bytes())
            self.assertEqual(hashlib.sha256(body).hexdigest(), sha, pid)
            self.assertTrue(pid.endswith(sha[:16]))

    def test_every_legacy_reading_has_an_availability_rule(self):
        missing = self.con.execute("SELECT DISTINCT r.source, r.metric FROM readings r LEFT JOIN reading_availability a "
                                   "ON a.source=r.source AND a.metric=r.metric WHERE a.metric IS NULL").fetchall()
        self.assertEqual(missing, [])

    def test_funding_venues_are_separate_and_labelled(self):
        self.assertEqual({r[0] for r in self.con.execute("SELECT DISTINCT venue FROM funding_events")}, VENUES)
        self.assertEqual(self.one("SELECT COUNT(*) FROM funding_events WHERE rate_semantics='' OR interval_source=''"), 0)
        # the funding interval is never a constant: BitMEX carries it per event, the others are derived from spacing
        self.assertGreater(self.one("SELECT COUNT(DISTINCT interval_s) FROM funding_events WHERE venue='bitmex'"), 1)
        # the legacy daily funding readings are labelled as aggregates, never as settlement events
        for (sem,) in self.con.execute("SELECT semantics FROM reading_availability WHERE source='funding'"):
            self.assertIn("NOT settlement events", sem)

    def test_families_registered(self):
        reg = {r[0] for r in self.con.execute("SELECT family FROM data_families")}
        self.assertEqual(reg, {f.family for f in discover_families(self.con)})

    def test_reports_cover_every_family_and_window(self):
        gate = json.loads((ROOT / "reports/coverage_gate_v10.json").read_text())
        fams = {f.family for f in discover_families(self.con)}
        self.assertEqual(set(gate["families"]), fams)
        for fam, v in gate["families"].items():
            self.assertEqual(set(v["windows"]), set(STANDARD_WINDOWS), fam)
            for w, r in v["windows"].items():
                self.assertIn(r["status"], ("PASS", "PARTIAL", "FAIL"))
                self.assertIn(r["quality"], ("exact_release", "source_timestamp", "conservative_lag", "approximate"))
                if r["status"] != "PASS":
                    self.assertTrue(r["reason"], f"{fam}/{w} has no reason")
        dq = json.loads((ROOT / "reports/data_quality_v10.json").read_text())
        self.assertTrue(dq["frozen_db_unchanged"])
        self.assertTrue(all(dq["legacy_tables_identical"].values()))
        self.assertEqual(set(dq["duplicate_keys"].values()), {0})
        self.assertEqual(set(dq["future_rows_after_as_of"].values()), {0})
        self.assertEqual(dq["published_before_observation"], 0)
        self.assertTrue(all(s["continuous"] for s in dq["tga_layout_seams"]), dq["tga_layout_seams"])
        prov = json.loads((ROOT / "reports/source_provenance_v10.json").read_text())
        srcs = {r[0] for r in self.con.execute("SELECT DISTINCT source FROM provenance")}
        self.assertEqual(set(prov["sources"]), srcs)
        self.assertEqual(sum(v["payloads"] for v in prov["sources"].values()), prov["raw_manifest_entries"])
        self.assertEqual(sum(v["rows"] for v in prov["sources"].values()),
                         self.one("SELECT COUNT(*) FROM funding_events") + self.one("SELECT COUNT(*) FROM macro_observations"))
        self.assertTrue(all(not v["third_party"] and v["originator"] != "unknown" for v in prov["sources"].values()))


@unittest.skipUnless(DB.exists() and MANIFEST.exists() and (ROOT / build.RAW_REL / "MANIFEST.jsonl").exists(),
                     "run scripts/build_stage1.py first")
class RawRebuild(unittest.TestCase):
    def test_rebuild_from_raw_archive_reproduces_the_logical_hash(self):
        man = json.loads(MANIFEST.read_text())
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            (tmp / "data_v10").mkdir()
            for rel in ("baseline_v09", "apex_v10", build.RAW_REL):
                os.symlink(ROOT / rel, tmp / rel)
            build.migrate(tmp)
            build.ingest(tmp, "raw", log=lambda *_: None)
            m2 = build.finalize(tmp)
        self.assertEqual(m2["logical_sha256"], man["logical_sha256"])
        self.assertEqual(m2["table_logical_sha256"], man["table_logical_sha256"])
        self.assertEqual(m2["row_counts"], man["row_counts"])
        if m2["sqlite_version"] == man["sqlite_version"] and m2["code_sha256"] == man["code_sha256"]:
            self.assertEqual(m2["file_sha256"], man["file_sha256"])      # byte-identical on the same SQLite build


if __name__ == "__main__":
    unittest.main()
