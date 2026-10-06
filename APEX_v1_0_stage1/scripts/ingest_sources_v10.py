#!/usr/bin/env python3
"""Stage 1, step 2: ingest venue-tagged funding events and direct-source macro series into the v1.0 copy.

    python3 scripts/ingest_sources_v10.py --mode raw      # rebuild from the archived payloads (no network)
    python3 scripts/ingest_sources_v10.py --mode online   # fetch again (writes a NEW archive; see --raw-dir)
"""
import argparse, json, sys
from pathlib import Path
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apex_v10.data import build  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["raw", "online"], default="raw")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    r = build.ingest(ROOT, a.mode, a.only)
    print(json.dumps({k: v for k, v in r.items() if k != "adapters"} | {"rows": {n: x["funding_rows"] + x["macro_rows"] for n, x in r["adapters"].items()}}, indent=2))
