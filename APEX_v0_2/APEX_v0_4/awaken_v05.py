"""APEX v0.5: one command, nothing to download by hand.

    python3 awaken_v05.py                     # awaken; download public history; research; paper-trade; report
    python3 awaken_v05.py --ticks 12          # more heartbeats (each does one piece of development, plus paper)
    python3 awaken_v05.py --readiness         # what is still needed before the single live deployment, and by whom
    python3 awaken_v05.py --hypothesis '{"name": "...", "spec": {"type": "calendar", "unit": "hour", "value": 6}}'
    python3 awaken_v05.py --say "turn on the microphone for 2 hours"   # owner input, as in v0.4
    python3 awaken_v05.py --ask "what changed in the evidence this week?"

Keep it running (or run it daily) and the paper record grows every day. Earlier launchers still work on the same
ledger. Nothing here can place a real order.
"""
from __future__ import annotations
import argparse, json, os
from apex.ext.organism_v05 import awaken_v05, VERSION


def main() -> None:
    ap = argparse.ArgumentParser(description="Awaken APEX v0.5")
    ap.add_argument("--state", default="state")
    ap.add_argument("--no-isolation", action="store_true")
    ap.add_argument("--ticks", type=int, default=8)
    ap.add_argument("--say", action="append", default=[])
    ap.add_argument("--ask", action="append", default=[])
    ap.add_argument("--hypothesis", action="append", default=[], help='JSON: {"name": ..., "spec": {...}, "rationale": ...}')
    ap.add_argument("--readiness", action="store_true")
    ap.add_argument("--hatch", action="store_true")
    args = ap.parse_args()

    org = awaken_v05(args.state, isolated=not args.no_isolation)
    print(f"APEX {VERSION} awake | authorityd pid {org.authority.status()['pid']} (this process {os.getpid()}) | "
          f"walls {'all pass' if all(w.ok for w in org.walls) else 'FAIL'} | hatch {org.hatch.stage}")
    print("leases:", ", ".join(f"{l['capability']} ({'open' if l['active'] else 'closed'})" for l in org.authority.leases()))
    for h in args.hypothesis:
        d = json.loads(h)
        print(f"[hypothesis registered] {d['name']} -> {org.submit_hypothesis(d['name'], d['spec'], d.get('rationale', ''))}")
    for u in args.say:
        r = org.command(u)
        print(f"[owner] {u!r} -> {r['intent']}: {json.dumps(r.get('result'), default=str)[:300]}")
    for q in args.ask:
        r = org.ask(q)
        print(f"[local model] {r.get('reply') or r.get('note') or r.get('error')}")
    for _ in range(max(0, args.ticks)):
        t = org.heartbeat_tick()
        print(f"[heartbeat {t['tick']}] {t['band']} worked_on={t['worked_on']}")
        if t.get("paper", {}).get("books"):
            print("   paper:", "; ".join(f"{n}: {b['days']} days, equity {b['equity']:,.0f}" for n, b in t["paper"]["books"].items()))
    if org.pending_hypotheses() and org.memory.t0 and org.memory.t0.get("passed"):
        for name, verdict in org.test_pending_hypotheses().items():
            print(f"[hypothesis tested] {name}: {verdict}")
    ev = org.evidence_summary()
    print("\nEVIDENCE (continuous; nothing passes or fails here)")
    print(f"  trials counted {ev['trials_counted']} | probability of backtest overfitting (family) {ev['pbo_family']}")
    for row in ev["top"]:
        print(f"  {row['name']:34s} Sharpe {row['sharpe']:6.2f}  deflated Sharpe {row['dsr']:.2f}  evidence {row['evidence']:.2f}")
    for name, row in ev["combined"].items():
        print(f"  {name:34s} Sharpe {row['sharpe']:6.2f}  deflated Sharpe {row['dsr']:.2f}  evidence {row['evidence']:.2f}")
    print(f"  benchmarks: {ev['benchmarks']}")
    print(f"  attention -> volatility: {ev['attention_volatility']}")
    cb = ev.get("core_book")
    if cb and cb.get("rule"):
        print(f"  BTC core trend book (backtest, 85 bps): {cb['rule']['cagr']:+.1%} a year, Sharpe {cb['rule']['sharpe']}, "
              f"worst drawdown {cb['rule']['max_drawdown']:.0%} | holding BTC: {cb['hold']['cagr']:+.1%}, Sharpe "
              f"{cb['hold']['sharpe']}, worst drawdown {cb['hold']['max_drawdown']:.0%} | {cb['verdict']}")
    for n, p in ev["paper"].items():
        print(f"  paper {n}: {p['days']} days, return {p['return']:.2%}, Sharpe {p['sharpe']}, t {p['t_stat']}")
    print("\nLADDER:", " | ".join(f"{r['rung']} {r['name']}: {r['state']}" for r in org.ladder_v05()))
    if args.hatch:
        h = org.hatch_readiness()
        print(f"[hatch] {org.hatch.stage} {h.vector}")
    if args.readiness:
        print("\nBEFORE THE SINGLE LIVE DEPLOYMENT")
        for r in org.deployment_readiness():
            print(f"  [{'x' if r['done'] else ' '}] {r['who']:6s} {r['item']}")
    org.shutdown()


if __name__ == "__main__":
    main()
