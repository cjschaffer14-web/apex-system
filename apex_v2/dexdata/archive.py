"""Load a dexdata archive, run the acceptance audit, and measure opportunities/competition.

Acceptance test (per the review): from archived state, reproduce every swap exactly.
  * completeness: contiguous blocks, no gaps, parent-hash chain intact, RPC disagreements counted;
  * state continuity: replaying a block's Sync/Swap logs from the previous block's reserves must land on
    the archived end-of-block reserves (catches missed logs and non-swap reserve changes);
  * swap exactness: for each swap the contract's K invariant must hold under the inferred fee, and
    for router-style swaps amount_out must equal getAmountOut(amount_in, pre-swap reserves) exactly.

Opportunity measurement (read-only): at every block end, for each ordered pool pair on the same token pair,
exact integer optimal WETH->USDC->WETH cycle; profit gross and net of L2 execution gas (base fee x assumed gas
units; L1 data fee NOT included); and whether a multi-pool tx (a cycle/arbitrage candidate) hit both pools in the
next block.

    python3 -m apex_v2.dexdata.archive data/base_v2.jsonl
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

from .univ2 import best_cycle_input, get_amount_out, invariant_ok

FEE_CANDIDATES = [(997, 1000), (9975, 10000), (998, 1000), (9970, 10000), (999, 1000), (9900, 10000), (9950, 10000), (9980, 10000)]
CYCLE_GAS_UNITS = 250_000  # assumed L2 execution gas for a 2-pool cycle (assumption, not measured)


def load(path: str) -> dict:
    A = {"pools": {}, "blocks": {}, "state": defaultdict(dict), "logs": defaultdict(list), "txs": {},
         "gaps": [], "disagree": [], "skips": []}
    with open(path) as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            t = r["type"]
            if t == "pool":
                A["pools"][r["pool"]] = r
            elif t == "block":
                A["blocks"][r["n"]] = r
            elif t == "state":
                A["state"][r["pool"]][r["n"]] = (r["r0"], r["r1"])
            elif t == "log":
                A["logs"][(r["pool"], r["n"])].append(r)
            elif t == "tx":
                A["txs"][r["tx"]] = r
            elif t == "gap":
                A["gaps"].append(r)
            elif t == "rpc_disagreement":
                A["disagree"].append(r)
            elif t == "skip":
                A["skips"].append(r)
    return A


def infer_fee(A: dict, pool: str):
    """Pick the fee ratio under which swaps satisfy K tightly (router swaps are exact => slack ~ 0)."""
    swaps = []
    for (p, n), logs in A["logs"].items():
        if p != pool:
            continue
        prev = A["state"][pool].get(n - 1)
        running = prev
        pending = None
        for lg in sorted(logs, key=lambda x: x["log_index"]):
            if lg["kind"] == "sync":
                pending = (lg["r0"], lg["r1"])
            elif lg["kind"] == "swap" and running and pending:
                swaps.append((running, pending, lg))
                running = pending
    best = None
    for num, den in FEE_CANDIDATES:
        ok = sum(invariant_ok(r0, r1, b0, b1, lg["in0"], lg["in1"], num, den) for (r0, r1), (b0, b1), lg in swaps)
        # exact output match: router swaps request exactly getAmountOut under the true fee
        exact = 0
        for (r0, r1), (b0, b1), lg in swaps:
            if lg["in0"] > 0 and lg["out1"] > 0:
                exact += get_amount_out(lg["in0"], r0, r1, num, den) == lg["out1"]
            elif lg["in1"] > 0 and lg["out0"] > 0:
                exact += get_amount_out(lg["in1"], r1, r0, num, den) == lg["out0"]
        score = (ok, exact)
        if best is None or score > best[0]:
            best = (score, (num, den))
    return (best[1] if best else (997, 1000)), len(swaps), (best[0] if best else (0, 0))


def audit(A: dict) -> dict:
    out = {"pools": len(A["pools"]), "blocks": len(A["blocks"])}
    ns = sorted(A["blocks"])
    missing = [n for n in range(ns[0], ns[-1] + 1) if n not in A["blocks"]] if ns else []
    bad_parent = [n for n in ns if n - 1 in A["blocks"] and A["blocks"][n]["parent"] != A["blocks"][n - 1]["hash"]]
    out.update(block_range=(ns[0], ns[-1]) if ns else None, missing_blocks=len(missing), parent_hash_breaks=len(bad_parent),
               rpc_disagreements=len(A["disagree"]), recorded_gaps=len(A["gaps"]))
    fees, per_pool = {}, {}
    cont_ok = cont_bad = 0
    for pool in A["pools"]:
        fee, n_sw, (ok, exact) = infer_fee(A, pool)
        fees[pool] = fee
        per_pool[pool] = {"dex": A["pools"][pool]["dex"], "swaps_replayed": n_sw, "inferred_fee": f"{fee[0]}/{fee[1]}",
                          "k_invariant_holds": ok, "exact_getAmountOut_match": exact}
        for n in ns:
            if n - 1 not in A["state"][pool] or n not in A["state"][pool]:
                continue
            logs = sorted(A["logs"].get((pool, n), []), key=lambda x: x["log_index"])
            syncs = [lg for lg in logs if lg["kind"] == "sync"]
            end = (syncs[-1]["r0"], syncs[-1]["r1"]) if syncs else A["state"][pool][n - 1]
            if end == A["state"][pool][n]:
                cont_ok += 1
            else:
                cont_bad += 1
    out.update(pool_audit=per_pool, state_continuity_ok=cont_ok, state_continuity_broken=cont_bad)
    out["_fees"] = fees
    return out


def opportunities(A: dict, fees: Dict[str, Tuple[int, int]]) -> dict:
    """Per-block exact best 2-pool cycle (start & end in WETH) and what happened next block."""
    pools = list(A["pools"].values())
    weth = next((p["token0"] if p["symbol0"] == "WETH" else p["token1"] for p in pools), None)
    rows = []
    for n in sorted(A["blocks"]):
        blk = A["blocks"][n]
        for pa in pools:
            for pb in pools:
                if pa["pool"] == pb["pool"] or n not in A["state"][pa["pool"]] or n not in A["state"][pb["pool"]]:
                    continue
                legs = []
                for p, tin_is_weth in ((pa, True), (pb, False)):
                    r0, r1 = A["state"][p["pool"]][n]
                    weth_is_0 = p["symbol0"] == "WETH"
                    rw, ru = (r0, r1) if weth_is_0 else (r1, r0)
                    rin, rout = (rw, ru) if tin_is_weth else (ru, rw)
                    # leg A: spend WETH on pool pa to get USDC?  buy cheap USDC-per-WETH pool b last; see below
                    legs.append((rin, rout, *fees[p["pool"]]))
                # Direction: WETH -> USDC on pa, USDC -> WETH on pb.
                x, prof = best_cycle_input(legs)
                if prof <= 0:
                    continue
                gas_weth = CYCLE_GAS_UNITS * blk["base_fee"]  # wei
                nxt = [t for t in A["txs"].values() if t["n"] == n + 1 and t["multi_pool"]
                       and pa["pool"] in t["pools_touched"] and pb["pool"] in t["pools_touched"]]
                rows.append({"n": n, "sell_on": pa["dex"], "buy_on": pb["dex"], "size_weth": x / 1e18, "gross_weth": prof / 1e18,
                             "gas_weth": gas_weth / 1e18, "net_weth": (prof - gas_weth) / 1e18,
                             "taken_next_block": bool(nxt), "taker": nxt[0]["from"] if nxt else None})
    return {"rows": rows}


def report(path: str) -> None:
    A = load(path)
    a = audit(A)
    fees = a.pop("_fees")
    print(json.dumps(a, indent=2, default=str))
    o = opportunities(A, fees)["rows"]
    pos = [r for r in o if r["net_weth"] > 0]
    print(f"\nblock-end cycle opportunities (exact integer sizing): {len(o)} with gross>0, {len(pos)} with net>0 after L2 gas "
          f"(gas assumes {CYCLE_GAS_UNITS} units x base fee; L1 data fee not included)")
    if o:
        g = sorted(r["gross_weth"] for r in o)
        print(f"  gross WETH per opportunity: median {g[len(g)//2]:.6f}  max {g[-1]:.6f}")
    if pos:
        print(f"  net>0: total {sum(r['net_weth'] for r in pos):.6f} WETH; taken by a multi-pool tx in the next block: "
              f"{sum(r['taken_next_block'] for r in pos)}/{len(pos)}")
    multi = [t for t in A["txs"].values() if t["multi_pool"]]
    print(f"\nmulti-pool (cycle-candidate) txs: {len(multi)}; distinct senders: {len({t['from'] for t in multi})}; "
          f"top senders: {Counter(t['from'] for t in multi).most_common(3)}")
    if multi:
        print(f"  median priority fee (wei): {sorted(t['max_priority_fee'] for t in multi)[len(multi)//2]}; "
              f"reverted: {sum(t['status'] == 0 for t in multi)}")


if __name__ == "__main__":
    report(sys.argv[1])
