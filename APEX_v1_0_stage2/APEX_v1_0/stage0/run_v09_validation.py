#!/usr/bin/env python3
"""APEX v1.0 Stage 0: run the frozen v0.9 validation, unmodified, without touching the baseline.

The v0.9 scripts were written for a different machine: they read and write under /mnt/data/. This runner
  * hashes every baseline file before and after,
  * copies the database to a scratch directory and verifies the copy's hash,
  * executes the original source of code/validate_v09.py with exactly two path literals redirected
    (database -> scratch copy, result file -> stage0/outputs/); each literal must occur exactly once,
  * compares the re-run with the frozen results/validation_v09.json, test by test.
With --reproduce-historical it also re-runs trading_backtest_v09.main() the same way (output to scratch) and
compares it with the frozen results/historical_v09_results.json. Re-running is allowed; nothing is redefined,
and no result produced here is a new performance claim.

Usage:  python3 stage0/run_v09_validation.py [--root PACKAGE_ROOT] [--reproduce-historical]
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True        # importing the frozen modules must not write __pycache__ into baseline_v09/
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from verify_baseline import sha256, tree_digest  # noqa: E402

V09_DB_LITERAL = "/mnt/data/market_2026-10-03.sqlite"
V09_VALIDATION_OUT = "/mnt/data/APEX_v09_cross_ai/validation_v09.json"
V09_HIST_OUTDIR = "/mnt/data/APEX_v09_cross_ai"


def redirect(source: str, replacements: dict[str, str]) -> str:
    for old, new in replacements.items():
        n = source.count(f"'{old}'")
        if n != 1:
            raise RuntimeError(f"expected the literal {old!r} exactly once in the frozen source, found {n}")
        source = source.replace(f"'{old}'", repr(new))
    return source


CROSS_PLATFORM_ATOL = 1e-12   # Stage 2 tolerance gate: absolute, for float leaves only (BLAS/arch last-place drift)


def equivalent_within(a, b, atol: float = CROSS_PLATFORM_ATOL) -> bool:
    """Same JSON structure; bools, ints, strings and None exactly equal; floats within `atol` (absolute only).
    A pass/fail flag can never be rescued by the tolerance: booleans are compared exactly, before numbers."""
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(equivalent_within(a[k], b[k], atol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equivalent_within(x, y, atol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool) or not (isinstance(a, float) or isinstance(b, float)):
        return type(a) is type(b) and a == b
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return False
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    if not (math.isfinite(a) and math.isfinite(b)):
        return a == b
    return abs(a - b) <= atol


def compare_validation(frozen: dict, rerun: dict, atol: float = CROSS_PLATFORM_ATOL) -> dict:
    """Exact comparison is still reported (`all_identical`); acceptance uses `all_equivalent`, which allows only
    float drift <= atol. The frozen results are never rewritten."""
    def key(t):
        return (t.get("pair"), t["test"])
    f = {key(t): t for t in frozen["tests"]}
    r = {key(t): t for t in rerun["tests"]}
    rows = []
    for k in sorted(set(f) | set(r), key=str):
        a, b = f.get(k), r.get(k)
        same = a == b
        equiv = same or (a is not None and b is not None and equivalent_within(a, b, atol))
        rows.append({"pair": k[0], "test": k[1], "frozen": a, "rerun": b, "identical": same, "equivalent": equiv,
                     "max_abs_numeric_difference": max_numeric_diff(a, b)["max"] if a is not None and b is not None else None})
    return {"identical_tests": sum(x["identical"] for x in rows), "tests": len(rows),
            "all_identical": all(x["identical"] for x in rows),
            "tolerance_atol": atol,
            "equivalent_tests": sum(x["equivalent"] for x in rows),
            "all_equivalent": all(x["equivalent"] for x in rows),
            "database_sha256_identical": frozen.get("database_sha256") == rerun.get("database_sha256"),
            "differences": [x for x in rows if not x["identical"]]}


def max_numeric_diff(a, b, path="$", out=None):
    """Walk two JSON trees; return (structurally_equal, max_abs_diff, first_mismatch_paths)."""
    out = out if out is not None else {"max": 0.0, "paths": [], "structural": []}
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            out["structural"].append(path)
        for k in set(a) & set(b):
            max_numeric_diff(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out["structural"].append(f"{path} (len {len(a)} vs {len(b)})")
        for i, (x, y) in enumerate(zip(a, b)):
            max_numeric_diff(x, y, f"{path}[{i}]", out)
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        if a != b and not (isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b)):
            d = abs(a - b) if all(map(math.isfinite, (a, b))) else math.inf
            if d > out["max"]:
                out["max"] = d
            if len(out["paths"]) < 10:
                out["paths"].append({"path": path, "frozen": a, "rerun": b})
    elif a != b:
        out["structural"].append(path)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(HERE.parent))
    ap.add_argument("--reproduce-historical", action="store_true")
    ap.add_argument("--outdir", default=None, help="where to write the rerun outputs (default: stage0/outputs)")
    a = ap.parse_args()
    root = Path(a.root).resolve()
    base = root / "baseline_v09"
    code = base / "code"
    outdir = Path(a.outdir).resolve() if a.outdir else root / "stage0" / "outputs"
    outdir.mkdir(parents=True, exist_ok=True)

    before = tree_digest(root)
    report: dict = {"stage": 0, "python": sys.version.split()[0]}
    try:
        import numpy, pandas, sklearn, scipy  # noqa: F401
        report["packages"] = {m.__name__: m.__version__ for m in (numpy, pandas, sklearn, scipy)}
    except ImportError as e:                  # document the blocker instead of masking it
        report["blocker"] = f"missing dependency: {e}"
        (outdir / "v09_validation_rerun_report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        return 2

    with tempfile.TemporaryDirectory(prefix="apex_v09_scratch_") as tmp:
        tmp = Path(tmp)
        db_src = base / "data" / "market_2026-10-03.sqlite"
        db_copy = tmp / "market_2026-10-03.sqlite"
        shutil.copyfile(db_src, db_copy)
        report["db_copy_sha256"] = sha256(db_copy)
        report["db_copy_matches_baseline"] = report["db_copy_sha256"] == sha256(db_src)

        sys.path.insert(0, str(code))                      # the frozen modules, imported in place, read-only
        val_src_path = code / "validate_v09.py"
        report["validate_v09_sha256"] = sha256(val_src_path)
        rerun_path = outdir / "v09_validation_rerun.json"
        src = redirect(val_src_path.read_text(), {V09_DB_LITERAL: str(db_copy), V09_VALIDATION_OUT: str(rerun_path)})
        t0 = time.time()
        exec(compile(src, str(val_src_path), "exec"), {"__name__": "__main__", "__file__": str(val_src_path)})
        report["validation_seconds"] = round(time.time() - t0, 1)
        frozen = json.loads((base / "results" / "validation_v09.json").read_text())
        rerun = json.loads(rerun_path.read_text())
        report["validation"] = {"rerun_all_pass": rerun.get("all_pass"), **compare_validation(frozen, rerun)}

        if a.reproduce_historical:
            import trading_backtest_v09 as v9
            main_src = inspect.getsource(v9.main)
            hist_dir = tmp / "hist"
            hist_dir.mkdir()
            main_src = redirect(main_src, {V09_DB_LITERAL: str(db_copy), V09_HIST_OUTDIR: str(hist_dir)})
            ns = dict(v9.__dict__)
            exec(compile(main_src, inspect.getsourcefile(v9.main), "exec"), ns)
            t0 = time.time()
            ns["main"]()
            report["historical_seconds"] = round(time.time() - t0, 1)
            frozen_h = json.loads((base / "results" / "historical_v09_results.json").read_text())
            rerun_h = json.loads((hist_dir / "historical_v09_results.json").read_text())
            raw = (hist_dir / "historical_v09_results.json").read_bytes()
            d = max_numeric_diff(frozen_h, rerun_h)
            report["historical"] = {"byte_identical": hashlib.sha256(raw).hexdigest() == sha256(base / "results" / "historical_v09_results.json"),
                                    "rerun_sha256": hashlib.sha256(raw).hexdigest(),
                                    "structural_differences": d["structural"][:20],
                                    "n_structural_differences": len(d["structural"]),
                                    "max_abs_numeric_difference": d["max"], "first_numeric_differences": d["paths"]}

    after = tree_digest(root)
    report["baseline_files_hashed"] = len(before)
    report["baseline_unchanged"] = before == after
    report["changed_baseline_files"] = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    ok = bool(report["baseline_unchanged"] and report["db_copy_matches_baseline"]
              and report["validation"]["rerun_all_pass"] and report["validation"]["all_equivalent"]
              and report["validation"]["database_sha256_identical"])
    report["all_pass"] = ok
    (outdir / "v09_validation_rerun_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in ("all_pass", "baseline_unchanged", "validation") if k in report}
                     | ({"historical": report["historical"]} if "historical" in report else {}), indent=2, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
