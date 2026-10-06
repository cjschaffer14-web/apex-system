#!/usr/bin/env python3
"""APEX v1.0 Stage 1A evidence closure. Stops before Stage 2."""
from __future__ import annotations
import argparse, hashlib, json, os, sqlite3, subprocess, sys, time
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.dont_write_bytecode=True; os.environ['PYTHONDONTWRITEBYTECODE']='1'
from apex_v10.data import stage1a as DB1A
from apex_v10.data.gate_1a import gate_report
from apex_v10.ledger import stage1a as L1A

PARENT_LEDGER_SHA='70661932c844e427c69ca7afb46fdc0a135920987129e77cea1f0ef02b529d3e'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def vintage_report(db):
 con=sqlite3.connect(db)
 try:
  macro=[{'source':s,'series_id':sid,'availability_time_quality':t,'value_vintage_quality':v,'rows':n}
         for s,sid,t,v,n in con.execute('SELECT source,series_id,availability_quality,value_vintage_quality,COUNT(*) FROM macro_observations GROUP BY 1,2,3,4 ORDER BY 1,2,3,4')]
  funding=[{'venue':ve,'symbol':sy,'availability_time_quality':t,'value_vintage_quality':v,'rows':n}
           for ve,sy,t,v,n in con.execute('SELECT venue,symbol,availability_quality,value_vintage_quality,COUNT(*) FROM funding_events GROUP BY 1,2,3,4 ORDER BY 1,2,3,4')]
  rev={'rows':con.execute('SELECT COUNT(*) FROM macro_revisions').fetchone()[0],
       'first_to_second_changed':con.execute('SELECT COUNT(*) FROM macro_revisions WHERE second_release_value IS NOT NULL AND second_release_value!=first_release_value').fetchone()[0],
       'first_to_latest_changed':con.execute('SELECT COUNT(*) FROM macro_revisions WHERE latest_value IS NOT NULL AND latest_value!=first_release_value').fetchone()[0]}
  policies=[{'family':a,'value_vintage_quality':b,'revision_status':c,'evidence_eligible':bool(d),'rationale':e}
            for a,b,c,d,e in con.execute('SELECT * FROM vintage_policy ORDER BY family')]
 finally: con.close()
 return {'macro':macro,'funding':funding,'h41_revision_audit':rev,'policies':policies,
         'note':'market_record is admissible as a canonical source event/history record; it is not claimed equivalent to a verified first release. TGA remains unverified and excluded.'}

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--reproduce-forensics',action='store_true'); a=ap.parse_args()
 t=time.time()
 parent_db=ROOT/DB1A.STAGE1_DB_REL
 if not parent_db.exists(): raise SystemExit('accepted Stage 1 database missing; restore/rebuild it before Stage 1A')
 if sha(parent_db)!=DB1A.STAGE1_FILE_SHA256: raise SystemExit('Stage 1 parent DB hash mismatch')
 if sha(ROOT/'ledger/trial_ledger.jsonl')!=PARENT_LEDGER_SHA: raise SystemExit('Stage 1 parent ledger hash mismatch')
 if a.reproduce_forensics:
  subprocess.run([sys.executable,str(ROOT/'scripts/run_forensics_1a.py')],cwd=ROOT,check=True)
 dbm=DB1A.build(ROOT,force=True)
 con=sqlite3.connect(ROOT/DB1A.TARGET_DB_REL)
 try: gate=gate_report(con)
 finally: con.close()
 (ROOT/'reports/coverage_gate_evidence_v10_1a.json').write_text(json.dumps(gate,indent=2,sort_keys=True))
 vr=vintage_report(ROOT/DB1A.TARGET_DB_REL)
 (ROOT/'reports/vintage_quality_v10_1a.json').write_text(json.dumps(vr,indent=2,sort_keys=True))
 ledger=L1A.build(ROOT)
 statuses=Counter(w['status'] for f in gate['families'].values() for w in f['windows'].values())
 out={'stage':'1A','db':dbm,'ledger':ledger,'evidence_gate_status_counts':dict(statuses),
      'vintage_report_sha256':sha(ROOT/'reports/vintage_quality_v10_1a.json'),
      'coverage_gate_sha256':sha(ROOT/'reports/coverage_gate_evidence_v10_1a.json'),
      'forensics_reproduced':a.reproduce_forensics,'seconds':round(time.time()-t,1),'stage2_started':False}
 (ROOT/'STAGE1A_OUTPUTS.json').write_text(json.dumps(out,indent=2,sort_keys=True))
 print(json.dumps({'db_file_sha256':dbm['file_sha256'],'db_logical_sha256':dbm['logical_sha256'],
                   'ledger_sha256':ledger['ledger_sha256'],'forensic_paths_recovered':ledger['forensic_paths_recovered'],
                   'forensic_unavailable':ledger['forensic_unavailable'],'comparable_sets':ledger['comparable_sets'],
                   'gate':dict(statuses),'seconds':out['seconds']},indent=2))
 return 0
if __name__=='__main__': raise SystemExit(main())
