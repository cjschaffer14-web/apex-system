"""APEX v0.4 one-click awakening.

    python awaken_v04.py                         # awaken, prove the walls, run heartbeats, sleep, report
    python awaken_v04.py --ticks 8               # more incubation
    python awaken_v04.py --say "turn on the microphone for 2 hours"
                                                 # owner input by voice or text (any modality)
    python awaken_v04.py --hatch                 # evaluate all ten hatch criteria
    python awaken_v04.py --ask "what is in this chart?" --image chart.png
                                                 # ask APEX's own local model (after setup_models.py)
    python awaken_v04.py --pairs XBTUSD,ETHUSD --intervals 1,60,1440
                                                 # day-trading research: add 1-minute candles for chosen pairs
    python awaken_v04.py --no-isolation          # Authority in-process (debugging only)

Seed for trading research (no permission needed): put Kraken's OHLCVT archive (ZIP or CSVs)
in data/kraken/. The heartbeat imports and validates it (T0); once T0 passes, the six-host
read-only web lease you pre-approved opens by itself. v0.2's run.py and v0.3's awaken.py
still work and continue the same ledger.
"""
from __future__ import annotations
import argparse
import json
import os
from apex.ext.organism_v04 import awaken_v04, VERSION
from apex.ext.views import render, VIEWS


def main() -> None:
    ap = argparse.ArgumentParser(description="Awaken the APEX v0.4 organism")
    ap.add_argument("--state", default="state")
    ap.add_argument("--data", default=None, help="data folder (default: data/ next to state/)")
    ap.add_argument("--no-isolation", action="store_true")
    ap.add_argument("--intervals", default="60,1440", help="Kraken candle sizes to import, in minutes (e.g. 1,60,1440)")
    ap.add_argument("--pairs", default="", help="limit the seed import to these pairs (e.g. XBTUSD,ETHUSD)")
    ap.add_argument("--ticks", type=int, default=6)
    ap.add_argument("--say", action="append", default=[], help="owner input, as spoken or typed")
    ap.add_argument("--modality", default="voice")
    ap.add_argument("--hatch", action="store_true")
    ap.add_argument("--ask", action="append", default=[], help="a question for the local model")
    ap.add_argument("--image", action="append", default=[], help="an image for --ask (local file)")
    ap.add_argument("--deep", action="store_true", help="use the deep model for --ask")
    ap.add_argument("--view", default=None, choices=sorted(VIEWS))
    args = ap.parse_args()

    org = awaken_v04(args.state, isolated=not args.no_isolation, data_dir=args.data,
                     seed_intervals=tuple(int(x) for x in args.intervals.split(",") if x),
                     seed_pairs=tuple(p.strip().upper() for p in args.pairs.split(",") if p.strip()) or None)
    st = org.authority.status()
    print(f"APEX {VERSION} awake | first awakening: {org.first_awakening} | authorityd pid {st['pid']} "
          f"(this process {os.getpid()})")
    print(f"shell: {org.shell_report.events} prior events, intact={org.shell_report.ok} | "
          f"memory digest {org.memory.digest()[:12]} | hatch stage {org.hatch.stage}")
    for w in org.walls:
        print(f"  {w.id} {'PASS' if w.ok else 'FAIL'}  {w.name}")
    if org.preapprovals_applied:
        print(f"pre-approvals recorded: {org.preapprovals_applied}")
    if org.migration:
        print(f"signed migration 0.3 -> {VERSION} recorded: {org.migration}")

    lm = org.llm.status()
    print(f"local models: verified={lm['verified'] or 'none'} | Apple silicon={lm['apple_silicon']}"
          + ("" if lm["verified"] else " | install once with: python3 setup_models.py"))
    for q in args.ask:
        r = org.ask(q, images=args.image or None, deep=args.deep)
        print(f"[local model {r.get('role', '-')}] {r.get('reply') or r.get('note') or r.get('error')}")

    for utterance in args.say:
        r = org.command(utterance, args.modality)
        print(f"[owner {args.modality}] {utterance!r} -> {r['intent']}: {json.dumps(r.get('result'), default=str)[:400]}")

    for _ in range(max(0, args.ticks)):
        t = org.heartbeat_tick()
        work = t["work"]
        summary = "" if work is None else json.dumps(work, default=str)[:160]
        print(f"[heartbeat {t['tick']}] band={t['band']} worked_on={t['worked_on']} {summary}")

    print("[sleep]", json.dumps(org.sleep_cycle(), default=str))
    if args.hatch:
        h = org.hatch_readiness()
        print(f"[hatch] stage={org.hatch.stage} cap={org.hatch.cap} H={h.vector}")
        for k, v in h.details.items():
            print(f"   {k}: {v}")
    print("[morning report]", json.dumps(org.morning_report(), default=str, indent=2))
    if args.view:
        print(render(args.view))
    org.shutdown()


if __name__ == "__main__":
    main()
