"""Per-block state archive for Uniswap-V2-style pools (read-only; no keys, no signing).

For every block: header (hash, parent, time, baseFee, gas), exact reserves of every tracked pool
(eth_call getReserves at that block), and every Swap/Sync log of those pools. For each tx that
swapped in a tracked pool: sender, target, gas used, effective gas price, status, which pools it
touched (a tx touching >= 2 tracked pools is flagged as a cycle/arbitrage candidate).
Pools are discovered on-chain from factory.getPair and verified (symbols read from the token
contracts), so no pool address is trusted from memory.

    python3 -m apex_v2.dexdata.collect --chain base --seconds 240 --out data/base_v2.jsonl
"""
from __future__ import annotations

import argparse
import json
import time
from typing import Dict, List, Optional

from .rpc import Rpc, RpcError

SEL = {"getReserves": "0x0902f1ac", "token0": "0x0dfe1681", "token1": "0xd21220a7",
       "decimals": "0x313ce567", "symbol": "0x95d89b41", "getPair": "0xe6a43905"}
T_SWAP = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"  # Swap(address,uint256,uint256,uint256,uint256,address)
T_SYNC = "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"  # Sync(uint112,uint112)
ZERO = "0x" + "0" * 40
CHUNK = 10  # blocks per RPC batch (Base makes ~2 blocks/s)

CHAINS = {
    "base": dict(
        chain_id=8453,
        rpcs=["https://mainnet.base.org", "https://base-rpc.publicnode.com", "https://base.drpc.org"],
        # candidate addresses; each is verified on-chain (getPair + token symbols) before use
        tokens={"WETH": "0x4200000000000000000000000000000000000006",
                "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"},
        factories={"uniswap_v2": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6",
                   "sushiswap_v2": "0x71524B4f93c58fcbF659783284E38825f0622859",
                   "baseswap": "0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB"},
    )
}


def pad(addr: str) -> str:
    return addr.lower().replace("0x", "").rjust(64, "0")


def word(hexdata: str, i: int) -> int:
    h = hexdata[2:] if hexdata.startswith("0x") else hexdata
    return int(h[64 * i:64 * (i + 1)] or "0", 16)


def dec_addr(res: str) -> str:
    return "0x" + res[-40:]


def dec_string(res: str) -> str:
    h = res[2:]
    if len(h) == 64:  # bytes32
        return bytes.fromhex(h).rstrip(b"\x00").decode(errors="replace")
    n = int(h[64:128], 16)
    return bytes.fromhex(h[128:128 + 2 * n]).decode(errors="replace")


def discover(rpc: Rpc, cfg: dict, w) -> List[dict]:
    t = cfg["tokens"]
    a, b = t["WETH"], t["USDC"]
    calls = [("eth_call", [{"to": a, "data": SEL["symbol"]}, "latest"]),
             ("eth_call", [{"to": b, "data": SEL["symbol"]}, "latest"]),
             ("eth_call", [{"to": a, "data": SEL["decimals"]}, "latest"]),
             ("eth_call", [{"to": b, "data": SEL["decimals"]}, "latest"])]
    sa, sb, da, db = rpc.batch(calls)
    for r in (sa, sb, da, db):
        if isinstance(r, Exception):
            raise RpcError(f"token verification failed: {r}")
    syms = (dec_string(sa), dec_string(sb))
    if syms != ("WETH", "USDC"):
        raise RpcError(f"token symbols on-chain are {syms}, expected WETH/USDC; refusing to continue")
    dec = {a.lower(): int(da, 16), b.lower(): int(db, 16)}
    pools = []
    for name, fac in cfg["factories"].items():
        try:
            r = rpc.call("eth_call", [{"to": fac, "data": SEL["getPair"] + pad(a) + pad(b)}, "latest"])
            pair = dec_addr(r)
        except (RpcError, TypeError) as e:
            w({"type": "skip", "dex": name, "reason": f"getPair failed: {e}"})
            continue
        if pair == ZERO or len(r) < 66:
            w({"type": "skip", "dex": name, "reason": "no WETH/USDC pair on factory (or wrong factory address)"})
            continue
        t0, t1 = rpc.batch([("eth_call", [{"to": pair, "data": SEL["token0"]}, "latest"]),
                            ("eth_call", [{"to": pair, "data": SEL["token1"]}, "latest"])])
        if isinstance(t0, Exception) or isinstance(t1, Exception) or len(t0) < 66 or len(t1) < 66:
            w({"type": "skip", "dex": name, "reason": "getPair result is not a v2 pair (token0/token1 call failed)"})
            continue
        t0, t1 = dec_addr(t0).lower(), dec_addr(t1).lower()
        if {t0, t1} != {a.lower(), b.lower()}:
            w({"type": "skip", "dex": name, "reason": "pair tokens do not match"})
            continue
        rec = {"type": "pool", "chain_id": cfg["chain_id"], "dex": name, "pool": pair.lower(), "factory": fac.lower(),
               "pool_type": "uniswap_v2_cpmm", "token0": t0, "token1": t1,
               "decimals0": dec[t0], "decimals1": dec[t1],
               "symbol0": "WETH" if t0 == a.lower() else "USDC", "symbol1": "WETH" if t1 == a.lower() else "USDC"}
        w(rec)
        pools.append(rec)
    return pools


def collect(chain: str, seconds: float, out: str) -> dict:
    cfg = CHAINS[chain]
    rpc = Rpc(cfg["rpcs"])
    f = open(out, "a", buffering=1)
    w = lambda rec: f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    cid = int(rpc.call("eth_chainId", []), 16)
    if cid != cfg["chain_id"]:
        raise RpcError(f"chain id {cid} != {cfg['chain_id']}")
    pools = discover(rpc, cfg, w)
    if not pools:
        raise RpcError("no pools verified")
    addrs = [p["pool"] for p in pools]
    head = int(rpc.call("eth_blockNumber", []), 16)
    last = head - 1
    t_end = time.time() + seconds
    stats = {"blocks": 0, "gaps": 0, "logs": 0, "rpc_disagreements": 0}
    while time.time() < t_end:
        try:
            head = int(rpc.call("eth_blockNumber", []), 16)
        except RpcError:
            time.sleep(1.0)
            continue
        if head > last + 20:  # fell far behind: record the gap honestly, jump forward
            stats["gaps"] += head - last - 1
            w({"type": "gap", "from": last + 1, "to": head - 1})
            last = head - 1
        n0 = last + 1
        while n0 <= head:
            n1 = min(head, n0 + CHUNK - 1)
            ns = list(range(n0, n1 + 1))
            calls = [("eth_getBlockByNumber", [hex(n), False]) for n in ns]
            for n in ns:
                calls += [("eth_call", [{"to": a, "data": SEL["getReserves"]}, hex(n)]) for a in addrs]
            calls += [("eth_getLogs", [{"fromBlock": hex(n0), "toBlock": hex(n1), "address": addrs, "topics": [[T_SWAP, T_SYNC]]}])]
            try:
                res = rpc.batch(calls, endpoint=n0 % len(cfg["rpcs"]))  # spread load across endpoints
            except RpcError as e:  # never crash the archive: record the hole and keep going
                w({"type": "gap", "from": n0, "to": n1, "reason": f"batch_failed: {str(e)[:120]}"})
                stats["gaps"] += len(ns)
                last = n1
                n0 = n1 + 1
                continue
            blks = res[:len(ns)]
            sts = res[len(ns):len(ns) + len(ns) * len(addrs)]
            logs_all = res[-1]
            if isinstance(logs_all, Exception):
                w({"type": "gap", "from": n0, "to": n1, "reason": "getLogs_failed"})
                stats["gaps"] += len(ns)
                last, n0 = n1, n1 + 1
                continue
            by_block: Dict[int, list] = {}
            for lg in logs_all:
                by_block.setdefault(int(lg["blockNumber"], 16), []).append(lg)
            for k, n in enumerate(ns):
                blk = blks[k]
                states = sts[k * len(addrs):(k + 1) * len(addrs)]
                if isinstance(blk, Exception) or blk is None or any(isinstance(x, Exception) for x in states):
                    w({"type": "gap", "from": n, "to": n, "reason": "rpc_error"})
                    stats["gaps"] += 1
                    continue
                w({"type": "block", "chain_id": cid, "n": n, "hash": blk["hash"], "parent": blk["parentHash"],
                   "time": int(blk["timestamp"], 16), "base_fee": int(blk.get("baseFeePerGas", "0x0"), 16),
                   "gas_used": int(blk["gasUsed"], 16), "gas_limit": int(blk["gasLimit"], 16),
                   "tx_count": len(blk["transactions"]), "recv_ns": time.time_ns()})
                for a, st in zip(addrs, states):
                    w({"type": "state", "n": n, "pool": a, "r0": word(st, 0), "r1": word(st, 1), "ts_last": word(st, 2)})
                txs: Dict[str, set] = {}
                for lg in sorted(by_block.get(n, []), key=lambda x: int(x["logIndex"], 16)):
                    topic = lg["topics"][0]
                    rec = {"type": "log", "n": n, "pool": lg["address"].lower(), "tx": lg["transactionHash"],
                           "tx_index": int(lg["transactionIndex"], 16), "log_index": int(lg["logIndex"], 16)}
                    if topic == T_SYNC:
                        rec.update(kind="sync", r0=word(lg["data"], 0), r1=word(lg["data"], 1))
                    elif topic == T_SWAP:
                        rec.update(kind="swap", in0=word(lg["data"], 0), in1=word(lg["data"], 1),
                                   out0=word(lg["data"], 2), out1=word(lg["data"], 3),
                                   sender=dec_addr(lg["topics"][1]), to=dec_addr(lg["topics"][2]))
                        txs.setdefault(lg["transactionHash"], set()).add(rec["pool"])
                    else:
                        continue
                    stats["logs"] += 1
                    w(rec)
                if txs:
                    hs = list(txs)
                    try:
                        got = rpc.batch([("eth_getTransactionByHash", [h]) for h in hs] +
                                        [("eth_getTransactionReceipt", [h]) for h in hs])
                    except RpcError:
                        got = [RpcError("tx fetch failed")] * (2 * len(hs))
                        w({"type": "gap", "from": n, "to": n, "reason": "tx_fetch_failed"})
                    for i, h in enumerate(hs):
                        tx, rc = got[i], got[len(hs) + i]
                        if isinstance(tx, Exception) or isinstance(rc, Exception) or not tx or not rc:
                            continue
                        w({"type": "tx", "n": n, "tx": h, "from": tx["from"].lower(), "to": (tx.get("to") or "").lower(),
                           "tx_index": int(rc["transactionIndex"], 16), "status": int(rc["status"], 16),
                           "gas_used": int(rc["gasUsed"], 16), "eff_gas_price": int(rc.get("effectiveGasPrice", "0x0"), 16),
                           "max_priority_fee": int(tx.get("maxPriorityFeePerGas", "0x0"), 16),
                           "pools_touched": sorted(txs[h]), "multi_pool": len(txs[h]) >= 2,
                           "input_len": (len(tx["input"]) - 2) // 2})
                if n % 10 == 0 and len(cfg["rpcs"]) > 1:  # independent-RPC cross-check of the block hash
                    try:
                        other = rpc.call("eth_getBlockByNumber", [hex(n), False], endpoint=(n + 1) % len(cfg["rpcs"]))
                    except RpcError:
                        other = None
                    if other and other["hash"] != blk["hash"]:
                        stats["rpc_disagreements"] += 1
                        w({"type": "rpc_disagreement", "n": n, "a": blk["hash"], "b": other["hash"]})
                stats["blocks"] += 1
            last, n0 = n1, n1 + 1
        time.sleep(0.4)
    f.close()
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--chain", default="base", choices=list(CHAINS))
    ap.add_argument("--seconds", type=float, default=240)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    print(collect(a.chain, a.seconds, a.out))
