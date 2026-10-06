"""Stage 0 acceptance tests: the frozen v0.9 baseline verifies, its validation still passes, nothing changes."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stage0"))

import verify_baseline as vb                     # noqa: E402
import run_v09_validation as rv                  # noqa: E402

DB_SHA = "ac53b123361e5de0f4aa00530cbe1c35286cfd3959224d4e2bf845f634267596"
SPEC_SHA = "e3415de69d1ba2e56f6afeb71fd61be2feb7253b061b5cc1b61a60ffbf4b4707"


class BaselineHashes(unittest.TestCase):
    def test_both_manifests_verify(self):
        for m in (ROOT / "PACKAGE_MANIFEST.json", ROOT / "baseline_v09" / "PACKAGE_MANIFEST.json"):
            r = vb.check_manifest(ROOT, m)
            self.assertTrue(r["all_pass"], r["failures"])

    def test_database_and_frozen_spec(self):
        db = vb.check_database(ROOT)
        self.assertTrue(db["pass_"])
        self.assertEqual(db["actual_sha256"], DB_SHA)
        self.assertEqual(db["integrity_check"], "ok")
        self.assertEqual(vb.check_frozen_spec(ROOT)["actual_sha256"], SPEC_SHA)
        self.assertTrue(vb.check_checksums_txt(ROOT)["all_pass"])
        self.assertEqual(vb.unlisted_files(ROOT), [])           # no stray files (e.g. __pycache__) in the baseline


class FrozenValidation(unittest.TestCase):
    def test_v09_validation_reruns_identically_and_leaves_baseline_untouched(self):
        before = vb.tree_digest(ROOT)
        with tempfile.TemporaryDirectory() as out:          # never overwrite the delivered Stage 0 evidence
            p = subprocess.run([sys.executable, str(ROOT / "stage0" / "run_v09_validation.py"), "--outdir", out],
                               capture_output=True, text=True, timeout=600)
            self.assertEqual(p.returncode, 0, p.stdout[-2000:] + p.stderr[-2000:])
            rep = json.loads((Path(out) / "v09_validation_rerun_report.json").read_text())
        self.assertTrue(rep["validation"]["rerun_all_pass"])
        self.assertTrue(rep["validation"]["all_identical"])
        self.assertEqual(rep["validation"]["tests"], 11)
        self.assertTrue(rep["baseline_unchanged"])
        self.assertEqual(before, vb.tree_digest(ROOT))

    def test_path_redirect_is_exact(self):
        src = "DB='/mnt/data/market_2026-10-03.sqlite'\nOUT='/mnt/data/x.json'\n"
        out = rv.redirect(src, {"/mnt/data/market_2026-10-03.sqlite": "/tmp/db"})
        self.assertIn("'/tmp/db'", out)
        with self.assertRaises(RuntimeError):                    # a literal that is missing must stop the run
            rv.redirect(src, {"/mnt/data/missing.json": "/tmp/y"})


if __name__ == "__main__":
    unittest.main()
