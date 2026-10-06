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
        # Stage 2 tolerance gate: float leaves may drift by <= 1e-12 across platforms (e.g. 3.0 vs
        # 3.0000000000000004 on arm64 vs x86_64); flags, counts and structure must still match exactly.
        self.assertTrue(rep["validation"]["all_equivalent"], rep["validation"]["differences"])
        self.assertEqual(rep["validation"]["tolerance_atol"], 1e-12)
        self.assertTrue(rep["validation"]["database_sha256_identical"])
        for d in rep["validation"]["differences"]:
            self.assertLessEqual(d["max_abs_numeric_difference"], 1e-12, d)
        self.assertEqual(rep["validation"]["tests"], 11)
        self.assertTrue(rep["baseline_unchanged"])
        self.assertEqual(before, vb.tree_digest(ROOT))

    def test_tolerance_gate_is_narrow(self):
        eq = rv.equivalent_within
        self.assertTrue(eq({"max_gross": 3.0000000000000004, "pass": True}, {"max_gross": 3.0, "pass": True}))
        self.assertFalse(eq({"max_gross": 3.0 + 1e-9}, {"max_gross": 3.0}))       # beyond 1e-12: a real change
        self.assertFalse(eq({"pass": True}, {"pass": False}))                    # flags are exact
        self.assertFalse(eq({"pass": True}, {"pass": 1}))                        # no bool/int coercion
        self.assertFalse(eq({"n": 11}, {"n": 12}))                               # integers are exact
        self.assertFalse(eq({"a": 1.0}, {"a": 1.0, "b": 2.0}))                   # structure is exact
        self.assertFalse(eq([1.0, 2.0], [1.0]))
        self.assertTrue(eq(float("nan"), float("nan")))
        self.assertFalse(eq(float("inf"), 1e308))

    def test_path_redirect_is_exact(self):
        src = "DB='/mnt/data/market_2026-10-03.sqlite'\nOUT='/mnt/data/x.json'\n"
        out = rv.redirect(src, {"/mnt/data/market_2026-10-03.sqlite": "/tmp/db"})
        self.assertIn("'/tmp/db'", out)
        with self.assertRaises(RuntimeError):                    # a literal that is missing must stop the run
            rv.redirect(src, {"/mnt/data/missing.json": "/tmp/y"})


if __name__ == "__main__":
    unittest.main()
