#!/usr/bin/env python3
"""Hash every v1.0 file added on top of the frozen handoff package (add-only outputs and code).

    python3 scripts/write_stage_manifest.py --stage 1      -> stage1/STAGE1_MANIFEST.json

Each entry: path, bytes, sha256. The manifest names its version and the parent baseline (frozen database and
package manifest hashes). The frozen package itself (baseline_v09/, handoff/, reviews/, README.md,
PACKAGE_MANIFEST.json) is verified separately by stage0/verify_baseline.py and is not listed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN = {"baseline_v09", "handoff", "reviews", "README.md", "PACKAGE_MANIFEST.json"}
SKIP_PARTS = {"__pycache__", ".DS_Store"}
BASELINE_DB_SHA256 = "ac53b123361e5de0f4aa00530cbe1c35286cfd3959224d4e2bf845f634267596"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=int, required=True)
    a = ap.parse_args()
    out_rel = f"stage{a.stage}/STAGE{a.stage}_MANIFEST.json"
    files = []
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if not p.is_file() or rel.parts[0] in FROZEN or SKIP_PARTS & set(rel.parts) or rel.as_posix() == out_rel \
                or rel.parts[0].startswith("data_v10") and "raw_previous_" in rel.as_posix():
            continue
        files.append({"path": rel.as_posix(), "bytes": p.stat().st_size, "sha256": sha256(p)})
    man = {"version": f"1.0.0-stage{a.stage}", "parent_baseline_db_sha256": BASELINE_DB_SHA256,
           "parent_package_manifest_sha256": sha256(ROOT / "PACKAGE_MANIFEST.json"),
           "parent_baseline_manifest_sha256": sha256(ROOT / "baseline_v09" / "PACKAGE_MANIFEST.json"),
           "files": files,
           "note": "the v1.0 database's file hash depends on the SQLite build; its logical hash in "
                   "data_v10/DB_MANIFEST.json is the cross-machine check"}
    (ROOT / out_rel).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / out_rel).write_text(json.dumps(man, indent=1))
    print(f"{out_rel}: {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
