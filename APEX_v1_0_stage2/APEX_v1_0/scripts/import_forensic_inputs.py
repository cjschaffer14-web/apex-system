#!/usr/bin/env python3
"""One-off (Stage 1A): archive the ORIGINAL inputs and code of the APEX v0.5 / v0.5.1 / ad hoc research runs of
2-3 Oct 2026, so the 148 metric-only historical trials can be reproduced forensically on any machine.

The originals exist only on the build machine where those runs happened. This script copies them, byte for byte,
into data_v10/imports/apex_v05/forensic/ and writes FORENSIC_INPUTS.json (SHA-256 of every original byte stream,
size, original path and modification time). Data files are stored deterministically gzipped. Nothing is
regenerated, re-fetched or edited. Run once; afterwards the archive is the source and this script refuses to
overwrite it. Secrets are never copied (the runs' state/ folders, which hold keys, are excluded by construction).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apex_v10.data.archive import gzip_deterministic   # noqa: E402

DEST_REL = "data_v10/imports/apex_v05/forensic"
SCRATCH = Path("/tmp/claude-0/-home-claude/8df26588-3f8e-543c-829b-2ca810af8eb3/scratchpad")
BUILD = Path("/home/claude/build/APEX_v0_4")

PLAN = [   # (origin, destination relative to the forensic root, role, gzip?)
    *[(p, f"inputs/coinbase_2026-10-02/{p.name}.gz", "Coinbase Exchange candles fetched 2 Oct 2026 21:47-21:50 EDT by "
       "research_2026-10-02/fetch.py; read by baseline.py, fib.py, xsec.py, six.py", True)
      for p in sorted((SCRATCH / "real").glob("*-USD_*.json"))],
    (BUILD / "research/owner_ideas_2026-10-03/media_data.json", "inputs/owner_ideas_2026-10-03/media_data.json.gz",
     "media.py cache (Coin Metrics Community + GDELT), fetched 2 Oct 2026 23:16 EDT", True),
    (SCRATCH / "real/six.py", "scripts/research_2026-10-02/six.py", "six-cycle calendar check (withdrawn)", False),
    (SCRATCH / "real/six.json", "scripts/research_2026-10-02/six.json", "its archived output", False),
    (SCRATCH / "real/v05run.py", "scripts/research_2026-10-02/v05run.py", "manual driver of research_v05 on the JSON "
     "inputs (reference only; the governed v0.5 trials ran inside the organism on the v0.5 store)", False),
    *[(SCRATCH / "real" / n, f"logs/research_2026-10-02/{n}", "console log of the original run", False)
      for n in ("daily.log", "hourly.log", "fib.log", "six.log")],
    *[(SCRATCH / n, f"logs/{n}", "console log of the original run", False)
      for n in ("real_v05.log", "real_v05b.log", "real_v05c.log", "real_v051.log", "real_v051b.log", "real_v051c.log",
                "real_v051d.log", "levels.log", "levels_power.log")],
    *[(p, f"code/v051_run/hypotheses/{p.name}", "owner hypothesis registration file", False)
      for p in sorted((SCRATCH / "xv51/hypotheses").glob("*.json"))],
]
CODE_TREES = [(SCRATCH / "xv5b/apex", "code/v05_run/apex", "code tree that ran the governed v0.5 research and "
               "hypotheses (2 Oct 2026 22:39 EDT, v0.5 store sha 3b1d1bf6)"),
              (SCRATCH / "xv51/apex", "code/v051_run/apex", "code tree that ran the v0.5.1 hypotheses (store = the frozen "
               "v0.9 database, sha ac53b123); the ad hoc and owner-idea scripts import the identical crypto_pack")]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    dest = ROOT / DEST_REL
    if (dest / "FORENSIC_INPUTS.json").exists():
        print(f"{DEST_REL}/FORENSIC_INPUTS.json exists; the archive is the source now (not overwritten)")
        return 0
    files = []
    plan = list(PLAN)
    for src_root, rel_root, role in CODE_TREES:
        for p in sorted(src_root.rglob("*.py")):
            if "__pycache__" not in p.parts:
                plan.append((p, f"{rel_root}/{p.relative_to(src_root).as_posix()}", role, False))
    for src, rel, role, gz in plan:
        if not src.exists():
            raise SystemExit(f"missing original: {src}")
        body = src.read_bytes()
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(gzip_deterministic(body) if gz else body)
        files.append({"path": rel, "sha256": sha(body), "bytes": len(body), "gzip": gz, "role": role,
                      "original_path": str(src),
                      "original_mtime_utc": dt.datetime.fromtimestamp(src.stat().st_mtime, dt.timezone.utc)
                      .isoformat(timespec="seconds")})
    man = {"purpose": "original inputs and code of the APEX v0.5/v0.5.1/ad hoc research runs (2-3 Oct 2026), "
                      "archived for Stage 1A forensic reproduction", "files": files,
           "note": "sha256 is of the original (uncompressed) bytes"}
    (dest / "FORENSIC_INPUTS.json").write_text(json.dumps(man, indent=1))
    print(f"archived {len(files)} files, {sum(f['bytes'] for f in files):,} original bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
