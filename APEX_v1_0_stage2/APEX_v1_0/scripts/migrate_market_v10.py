#!/usr/bin/env python3
"""Stage 1, step 1: byte-copy the frozen v0.9 database to data_v10/ and apply the additive v1.0 schema.
The frozen file is hashed before and after; it is never opened for writing.

    python3 scripts/migrate_market_v10.py [--force]
"""
import argparse, json, sys
from pathlib import Path
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apex_v10.data import build  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--force", action="store_true"); a = ap.parse_args()
    r = build.migrate(ROOT, force=a.force)
    print(json.dumps(r, indent=2))
    sys.exit(0 if r["source_unchanged"] else 1)
