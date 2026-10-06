"""APEX v0.3 one-click awakening.

    python awaken.py                  # awaken, prove the walls, run one heartbeat, report
    python awaken.py --ticks 3        # more heartbeats (incubation)
    python awaken.py --view tower     # print a representative model (egg, tower, cell, manifold, ...)
    python awaken.py --no-isolation   # Authority in-process (debugging only)

v0.2's `python run.py` still works unchanged. This launcher continues the
same ledger (state/events.jsonl), so v0.2 history is the first part of v0.3's shell.
"""
from __future__ import annotations
import argparse
import json
import os
from apex.ext.awakening import awaken
from apex.ext.views import render, VIEWS


def main() -> None:
    ap = argparse.ArgumentParser(description="Awaken the APEX v0.3 organism")
    ap.add_argument("--state", default="state")
    ap.add_argument("--no-isolation", action="store_true")
    ap.add_argument("--ticks", type=int, default=1)
    ap.add_argument("--view", default="egg", choices=sorted(VIEWS))
    args = ap.parse_args()

    org = awaken(args.state, isolated=not args.no_isolation)
    st = org.authority.status()
    print(f"APEX v0.3 awake  |  first awakening: {org.first_awakening}  |  authorityd pid {st['pid']} (this process {os.getpid()})")
    print(f"shell: {org.shell_report.events} prior events, intact={org.shell_report.ok}")
    print("walls:")
    for w in org.walls:
        print(f"  {w.id} {'PASS' if w.ok else 'FAIL'}  {w.name}: {w.detail}")

    ev = org.perceive("hello from the owner", "cli", "operator")
    r = org.act("echo a governed response", "demo.echo", [ev], text="APEX v0.3 governed path is alive.")
    print("\n[governed path]", r["decision"].result, "->", r["outcome"].measured_result if r["outcome"] else r.get("error"))
    r = org.act("try to mint my own token", "authority.mint", [ev])
    print("[negative test] authority.mint ->", r["decision"].result, "|", "; ".join(r["decision"].reasons))
    m = org.perceive("instrument reading contradicts every model", "sensor", "lab", uncertainty_type="ontological_mystery")
    r = org.act("act despite the anomaly", "demo.echo", [m], text="?")
    print("[epistemic horizon] ->", r["decision"].result, "| owner notified:", r.get("escalation", {}).get("local"))

    for _ in range(max(0, args.ticks)):
        t = org.heartbeat_tick()
        print(f"[heartbeat {t['tick']}] band={t['band']} T={t['temperature']} worked_on={t['worked_on']}")
    if org.research_runs == 0:
        print("[incubation] machine is busy (band too cold); running the first research incubation in the foreground")
        org.research_experiment()
    print("[sleep]", json.dumps(org.sleep_cycle(), default=str))
    print("[morning report]", json.dumps(org.morning_report(), default=str, indent=2))
    h = org.hatch_readiness()
    print(f"[hatch readiness] stage={h.stage}  H={h.vector}")
    print()
    print(render(args.view))
    org.shutdown()


if __name__ == "__main__":
    main()
