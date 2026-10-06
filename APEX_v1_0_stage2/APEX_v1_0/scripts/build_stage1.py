#!/usr/bin/env python3
"""APEX v1.0 Stage 1 - one command, any machine.

    python3 scripts/build_stage1.py                 # rebuild from the archived raw payloads (no network needed)
    python3 scripts/build_stage1.py --mode online   # fetch every source again into a NEW archive directory first

Steps: verify the frozen baseline -> clone the database and apply the v1.0 schema -> ingest funding and macro
sources -> finalize (VACUUM, hashes) -> rebuild trial returns and the ledger -> coverage / quality reports.
Writes STAGE1_OUTPUTS.json with every checksum. The frozen v0.9 package is never modified.
Requires Python >= 3.11 with numpy, pandas, scikit-learn (the frozen v0.6-v0.9 code needs them).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import warnings
from pathlib import Path

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stage0"))

import verify_baseline as vb                     # noqa: E402
from apex_v10.data import build, reports         # noqa: E402
from apex_v10.ledger import build_ledger         # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["raw", "online"], default="raw")
    a = ap.parse_args()
    t0 = time.time()
    out: dict = {"stage": 1, "mode": a.mode}
    before = vb.tree_digest(ROOT)
    v = {"package": vb.check_manifest(ROOT, ROOT / "PACKAGE_MANIFEST.json")["all_pass"],
         "baseline": vb.check_manifest(ROOT, ROOT / "baseline_v09" / "PACKAGE_MANIFEST.json")["all_pass"],
         "database": vb.check_database(ROOT)["pass_"]}
    out["baseline_verified"] = v
    if not all(v.values()):
        print(json.dumps(out, indent=2))
        return 1
    if a.mode == "online":
        raw = ROOT / build.RAW_REL
        if raw.exists():
            stamp = time.strftime("%Y%m%dT%H%M%S")
            shutil.move(str(raw), str(raw.parent / f"raw_previous_{stamp}"))
            print(f"previous archive kept as data_v10/raw_previous_{stamp}")
    print("1/5 migrate");  out["migrate"] = build.migrate(ROOT, force=True)
    print("2/5 ingest");   out["ingest"] = build.ingest(ROOT, a.mode)
    print("3/5 finalize"); out["database"] = build.finalize(ROOT)
    print("4/5 ledger")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)          # the frozen v0.9 code computes nanstd on 1-row slices
        out["ledger"] = build_ledger.build(ROOT)
    print("5/5 reports");  out["reports"] = reports.write_all(ROOT)
    after = vb.tree_digest(ROOT)
    out["baseline_unchanged"] = before == after
    out["seconds"] = round(time.time() - t0, 1)
    (ROOT / "STAGE1_OUTPUTS.json").write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({"db_file_sha256": out["database"]["file_sha256"], "db_logical_sha256": out["database"]["logical_sha256"],
                      "ledger_records": out["ledger"]["records"], "ledger_sha256": out["ledger"]["ledger_sha256"],
                      "reconstruction": out["ledger"]["reconstruction"], "gate": out["reports"]["gate_status_counts"],
                      "baseline_unchanged": out["baseline_unchanged"], "seconds": out["seconds"]}, indent=2))
    rec = out["ledger"]["reconstruction"]
    if rec["passed"] != rec["checks"]:
        print(f"WARNING: {rec['checks'] - rec['passed']} reconstruction checks failed (see "
              "reports/reconstruction_reconciliation.json); those trials are recorded as unavailable, not stored")
    return 0 if (out["baseline_unchanged"] and out["migrate"]["source_unchanged"]
                 and rec["passed"] == rec["checks"]) else 1


if __name__ == "__main__":
    sys.exit(main())
