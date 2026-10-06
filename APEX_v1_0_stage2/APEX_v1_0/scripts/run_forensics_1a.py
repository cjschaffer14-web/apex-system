#!/usr/bin/env python3
"""Run all Stage 1A frozen forensic reproductions. No tuning or parameter changes."""
from __future__ import annotations
import contextlib, hashlib, json, os, sys, time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.dont_write_bytecode=True
os.environ['PYTHONDONTWRITEBYTECODE']='1'
from apex_v10.forensics.harness import Inputs
from apex_v10.forensics import runs as R

OUTS={
 'adhoc':'stage1a/forensic_adhoc_outcomes.json',
 'owner':'stage1a/forensic_owner_outcomes.json',
 'v05':'stage1a/forensic_v05_outcomes.json',
 'v051':'stage1a/forensic_v051_outcomes.json',
}

def _write(rel, rows):
 p=ROOT/rel; p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps([asdict(x) for x in rows],indent=2,sort_keys=True,allow_nan=True))

def main():
 inputs=Inputs(ROOT); db=ROOT/'data_v10/market_2026-10-03_v10.sqlite'
 if not db.exists(): raise FileNotFoundError('accepted Stage 1 database missing; rebuild/restore it first')
 logp=ROOT/'stage1a/forensic_reproduction.log'
 t=time.time(); summary={}
 with logp.open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
  sha={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'data_v10/imports/apex_v05/research_2026-10-02').glob('*.py')}
  rows=R.adhoc_2026_10_02(ROOT,inputs,sha); _write(OUTS['adhoc'],rows); summary['adhoc']={'n':len(rows),'status':dict(Counter(x.status for x in rows))}
  sha={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'data_v10/imports/apex_v05/owner_ideas_2026-10-03').glob('*.py')}
  rows=R.owner_2026_10_03(ROOT,inputs,db,sha); _write(OUTS['owner'],rows); summary['owner']={'n':len(rows),'status':dict(Counter(x.status for x in rows))}
  rows=R.apex_v05(ROOT,inputs,db); _write(OUTS['v05'],rows); summary['v05']={'n':len(rows),'status':dict(Counter(x.status for x in rows))}
  rows=R.apex_v051(ROOT,inputs,db); _write(OUTS['v051'],rows); summary['v051']={'n':len(rows),'status':dict(Counter(x.status for x in rows))}
 summary['seconds']=round(time.time()-t,2)
 (ROOT/'stage1a/FORENSIC_SUMMARY.json').write_text(json.dumps(summary,indent=2,sort_keys=True))
 print(json.dumps(summary,indent=2,sort_keys=True))
 return 0
if __name__=='__main__': raise SystemExit(main())
