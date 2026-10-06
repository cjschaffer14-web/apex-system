#!/usr/bin/env python3
"""Stage 1, step 3: rebuild per-period returns of the frozen trials (verified against the frozen results) and write
ledger/trial_ledger.jsonl, ledger/LEDGER_SUMMARY.json and reports/reconstruction_reconciliation.json.

    python3 scripts/build_trial_ledger.py
"""
import json, sys, time
from pathlib import Path
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apex_v10.ledger import build_ledger  # noqa: E402

if __name__ == "__main__":
    t = time.time()
    s = build_ledger.build(ROOT)
    s["seconds"] = round(time.time() - t, 1)
    print(json.dumps(s, indent=2))
