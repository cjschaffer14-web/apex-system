#!/usr/bin/env python3
"""Read frozen inputs and write separate Layer 7 statistical diagnostics."""
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from apex_v10.stage2_statistics import run
if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--out',default=str(ROOT/'stage2/ChatGPT_L7_2026-10-04'))
    args=parser.parse_args(); r=run(ROOT,args.out)
    print(f"DSR rows={r['dsr_rows']}; CSCV sets={r['cscv_sets']}; global N={r['global_research_N']}")
    print('No candidate promotion; DSR values are conditional sensitivities.')
