#!/usr/bin/env python3
"""APEX v1.0 Stage 0: can the frozen v0.6 / v0.8 result files be regenerated from the frozen code?

Stage 1's trial ledger needs per-period return series, which the frozen result files do not store (they keep
summary statistics only). If the frozen code regenerates the frozen summaries, the return paths can be rebuilt
exactly from code + data + parameters; if not, those trials must be marked "return path unavailable".

Runs the original command-line entry points (unmodified) against a hash-verified scratch copy of the database,
writes only to a scratch directory, and compares the regenerated JSON with the frozen files. Bytecode writing is
disabled so the baseline tree stays byte-identical (checked before/after).

Usage:  python3 stage0/reproduce_probe.py [--root PACKAGE_ROOT]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from verify_baseline import sha256, tree_digest          # noqa: E402
from run_v09_validation import max_numeric_diff         # noqa: E402

JOBS = [  # (frozen result file, script, args)
    ("btc_v06_historical_25bps.json", "trading_backtest_v06.py", ["--pair", "BTC-USD", "--cost-bps", "25"]),
    ("eth_v06_historical_25bps.json", "trading_backtest_v06.py", ["--pair", "ETH-USD", "--cost-bps", "25"]),
    ("btc_real_v08_25bps.json", "trading_backtest_v08.py", ["--pair", "BTC-USD", "--cost-bps", "25"]),
    ("eth_real_v08_25bps.json", "trading_backtest_v08.py", ["--pair", "ETH-USD", "--cost-bps", "25"]),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(HERE.parent))
    a = ap.parse_args()
    root = Path(a.root).resolve()
    base = root / "baseline_v09"
    before = tree_digest(root)
    out: dict = {"stage": 0, "jobs": []}
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(base / "code")}
    with tempfile.TemporaryDirectory(prefix="apex_v09_probe_") as tmp:
        tmp = Path(tmp)
        db = tmp / "market_2026-10-03.sqlite"
        shutil.copyfile(base / "data" / "market_2026-10-03.sqlite", db)
        assert sha256(db) == sha256(base / "data" / "market_2026-10-03.sqlite")
        for frozen_name, script, args in JOBS:
            target = tmp / frozen_name
            t0 = time.time()
            p = subprocess.run([sys.executable, str(base / "code" / script), "--db", str(db), "--out", str(target), *args],
                               cwd=tmp, env=env, capture_output=True, text=True)
            row = {"frozen": f"results/{frozen_name}", "command": f"{script} {' '.join(args)} --db <scratch copy>",
                   "returncode": p.returncode, "seconds": round(time.time() - t0, 1)}
            if p.returncode == 0:
                frozen = json.loads((base / "results" / frozen_name).read_text())
                rerun = json.loads(target.read_text())
                d = max_numeric_diff(frozen, rerun)
                row.update(byte_identical=sha256(target) == sha256(base / "results" / frozen_name),
                           n_structural_differences=len(d["structural"]), structural_differences=d["structural"][:10],
                           max_abs_numeric_difference=d["max"], first_numeric_differences=d["paths"][:5])
            else:
                row["stderr_tail"] = p.stderr[-800:]
            out["jobs"].append(row)
            print(json.dumps({k: row.get(k) for k in ("frozen", "returncode", "seconds", "byte_identical",
                                                      "n_structural_differences", "max_abs_numeric_difference")}), flush=True)
    after = tree_digest(root)
    out["baseline_unchanged"] = before == after
    (root / "stage0" / "outputs" / "reproduce_probe.json").write_text(json.dumps(out, indent=2))
    return 0 if out["baseline_unchanged"] else 1


if __name__ == "__main__":
    sys.exit(main())
