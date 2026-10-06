"""Stage 1A forensic reproductions of the 148 metric-only historical trials (APEX v0.5 / v0.5.1 governed runs, the
ad hoc research of 2 Oct 2026 and the owner-idea research of 3 Oct 2026).

Each group re-executes the archived script or archived module UNMODIFIED, on the archived original inputs, and
compares every archived number with the number the rerun produces. A trial's return path is accepted only if
  (a) every archived metric of that trial reproduces exactly (as rounded and stored by the original run), and
  (b) the captured path, fed through the script's own summary function, gives the same metric.
Otherwise the trial stays `unavailable`. Trials whose definition has no return path (statistical tests, placebo
aggregates) are reproduced as statistics only. No parameter is chosen, tuned or changed here.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .harness import Inputs, LineProbe, Sandbox, probes, recording, script_bytes, snapshot

DAY = 86400
FIB = (0.382, 0.5, 0.618)
THIRDS = (0.333, 0.5, 0.667)


@dataclass
class Series:
    ts: list[int]
    ret: list[float]
    frequency: str


@dataclass
class Outcome:
    trial_id: str
    status: str                    # reproduced_series | reproduced_statistic_only | mismatch | not_reproducible
    method: str
    n_fields_compared: int = 0
    mismatches: list = field(default_factory=list)
    series: Optional[Series] = None
    series_check: Optional[dict] = None
    code: dict = field(default_factory=dict)
    note: str = ""


# ---------------------------------------------------------------------------------------------------------------
def _jsonish(x: Any) -> Any:
    return json.loads(json.dumps(x, default=float))


def compare(archived: Any, reproduced: Any, path: str = "") -> tuple[int, list]:
    """(number of leaf values compared, list of differences). Exact equality; NaN equals NaN."""
    if isinstance(archived, dict) and isinstance(reproduced, dict):
        n, bad = 0, []
        for k in sorted(set(archived) | set(reproduced), key=str):
            if k not in archived or k not in reproduced:
                bad.append({"field": f"{path}.{k}".lstrip("."), "archived": archived.get(k, "<absent>"),
                            "reproduced": reproduced.get(k, "<absent>")})
                n += 1
                continue
            m, b = compare(archived[k], reproduced[k], f"{path}.{k}")
            n, bad = n + m, bad + b
        return n, bad
    if isinstance(archived, list) and isinstance(reproduced, list) and len(archived) == len(reproduced):
        n, bad = 0, []
        for i, (a, b_) in enumerate(zip(archived, reproduced)):
            m, b = compare(a, b_, f"{path}[{i}]")
            n, bad = n + m, bad + b
        return n, bad
    same = archived == reproduced or (isinstance(archived, float) and isinstance(reproduced, float)
                                      and math.isnan(archived) and math.isnan(reproduced))
    return 1, ([] if same else [{"field": path.lstrip("."), "archived": archived, "reproduced": reproduced}])


def _outcome(tid: str, method: str, archived: Any, reproduced: Any, series: Optional[Series] = None,
             check: Optional[dict] = None, code: Optional[dict] = None, note: str = "") -> Outcome:
    n, bad = compare(_jsonish(archived), _jsonish(reproduced))
    if bad:
        status = "mismatch"
    elif series is not None:
        status = "reproduced_series" if check and check.get("equal") else "mismatch"
    else:
        status = "reproduced_statistic_only"
    return Outcome(tid, status, method, n, bad, series if status == "reproduced_series" else None, check, code or {},
                   note)


class _Store:
    """The minimal object the archived APEX functions read from: `.db`, a read-only connection to the store."""

    def __init__(self, path: Path) -> None:
        self.db = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro&immutable=1", uri=True)

    def close(self) -> None:
        self.db.close()


def _first_ts(body: bytes) -> int:
    return int(json.loads(body)[0][0])


# =================================================================================================================
# 1. ad hoc research, 2 Oct 2026 (baseline walk-forward, Fibonacci levels, cross-sectional momentum, six-cycle)
# =================================================================================================================
COINBASE = "inputs/coinbase_2026-10-02"


def adhoc_2026_10_02(root: Path, inputs: Inputs, script_sha: dict[str, str]) -> list[Outcome]:
    out: list[Outcome] = []
    arch = {n: json.loads((root / f"data_v10/imports/apex_v05/research_2026-10-02/{n}.json").read_text())
            for n in ("baseline", "fib", "xsec")}
    files = [r for r in inputs.index if r.startswith(COINBASE + "/")]
    with Sandbox(inputs, "v051_run") as sb:
        first_ts = {}
        for rel in files:
            body = inputs.read(rel)
            name = Path(rel).name[:-3]                                   # "<prod>_<gran>.json"
            sb.place(name, body)
            first_ts[name[:-5]] = _first_ts(body)
        code_in = {"code_tree": "v051_run (crypto_pack sha 6d5aef02)",
                   "inputs": sorted(inputs.sha(r)[:12] + " " + Path(r).name for r in files)}
        cp = sb.module("apex.ext.crypto_pack")

        # -- baseline.py: v0.4.1 walk-forward, 2 products x 2 granularities x 3 fees ---------------------------
        sb.place("baseline.py", script_bytes(root, "research_2026-10-02/baseline.py", script_sha["baseline.py"]))
        folds: list[dict] = []
        runs: list[dict] = []
        keyed: dict[str, dict] = {}

        def rec_sim(args, kwargs, res, caller):
            state = args[6] if len(args) > 6 else kwargs.get("state")
            if caller.f_code.co_name == "walk_forward" and state is not None:      # an out-of-sample fold
                folds.append({"start": args[3], "returns": list(res["returns"])})

        def rec_wf(args, kwargs, res, caller):
            spans = [(f["start"], len(f["returns"])) for f in folds]
            contiguous = bool(spans) and spans[0][0] == args[2] and all(a + n == b for (a, n), (b, _) in zip(spans, spans[1:]))
            runs.append({"train": args[2], "bpy": args[1].bars_per_year, "fee": args[1].fee_bps,
                         "net": [r for f in folds for r in f["returns"]], "contiguous": contiguous, "result": res})
            folds.clear()

        def at_key(frame):                    # module-level names live in the frame's globals
            g_ = frame.f_globals
            keyed[g_["key"]] = {"prod": g_["prod"], "gran": g_["gran"], "run": runs[-1]}

        with recording(cp, "simulate", rec_sim), recording(cp, "walk_forward", rec_wf):
            sb.run_script("baseline.py", probe_list=(LineProbe("", "<module>", "out[key] = {k: (round(r[k], 3)", at_key),))
        rep = sb.read_json("baseline.json")
        for key, a in arch["baseline"].items():
            prod, gran_name, fee = key.split()
            tid = f"adhoc-2026-10-02|{prod}|walk_forward|{gran_name}|{fee}"
            k = keyed.get(key)
            if k is None or key not in rep:
                out.append(Outcome(tid, "not_reproducible", "baseline.py rerun", note="key not produced by the rerun"))
                continue
            r, gran = k["run"], k["gran"]
            contiguous = r["contiguous"]
            ts0 = first_ts[f"{prod}_{gran}"]
            s = Series([ts0 + (r["train"] + i + 1) * gran for i in range(len(r["net"]))], r["net"],
                       "daily" if gran == DAY else "hourly")
            sh = cp.sharpe(s.ret, r["bpy"])
            check = {"metric": "oos_sharpe", "from_series": sh, "reported": r["result"]["oos_sharpe"],
                     "oos_bars": len(s.ret), "contiguous_folds": contiguous,
                     "equal": sh == r["result"]["oos_sharpe"] and len(s.ret) == r["result"]["oos_bars"] and contiguous}
            out.append(_outcome(tid, "baseline.py rerun; out-of-sample fold returns of cp.walk_forward", a, rep[key], s,
                                check, {"script": "research_2026-10-02/baseline.py", **code_in},
                                "return keyed by the bar it is earned in (bar open ts); gaps carried flat as in the "
                                "original load(); the last daily bar of the inputs is the partial 3 Oct 2026 bar"))

        # -- fib.py: retracement signal vs 40 random level sets and thirds --------------------------------------
        sb.place("fib.py", script_bytes(root, "research_2026-10-02/fib.py", script_sha["fib.py"]))
        sims: list[dict] = []

        def at_run_return(frame):
            g_ = frame.f_globals                  # run() is called from the module-level loop over prod/gran
            sims.append({"prod": g_["prod"], "gran": g_["gran"], "ratios": tuple(frame.f_locals["ratios"]),
                         "bpy": frame.f_locals["bpy"], **snapshot(frame, ("r",))})

        sb.run_script("fib.py", probe_list=(LineProbe("", "run", 'return cp.sharpe(r["returns"], bpy), cp.sharpe(r["gross"], bpy)',
                                                      at_run_return),))
        rep = sb.read_json("fib.json")
        for key, a in arch["fib"].items():
            prod, gran_name = key.split()
            gran = DAY if gran_name == "daily" else 3600
            base = f"adhoc-2026-10-02|{prod}|fibonacci_levels|{gran_name}"
            mine = [x for x in sims if x["prod"] == prod and x["gran"] == gran]
            code = {"script": "research_2026-10-02/fib.py", **code_in}
            if key not in rep or len(mine) != 42:
                for tid in (base, f"{base}|control:random_levels", f"{base}|control:thirds_levels"):
                    out.append(Outcome(tid, "not_reproducible", "fib.py rerun", note="rerun did not produce this key"))
                continue
            ts0 = first_ts[f"{prod}_{gran}"]
            freq = "daily" if gran == DAY else "hourly"
            fib = next(x for x in mine if x["ratios"] == FIB)
            thirds = next(x for x in mine if x["ratios"] == THIRDS)
            controls = [x for x in mine if x["ratios"] not in (FIB, THIRDS)]
            def path(x, which):
                rr = x["r"][which]
                return Series([ts0 + (61 + i) * gran for i in range(len(rr))], list(rr), freq)
            own = ("fib_gross_sharpe", "fib_net_sharpe_45bps", "fib_trades")
            s = path(fib, "returns")
            net = round(cp.sharpe(s.ret, fib["bpy"]), 3)
            out.append(_outcome(base, "fib.py rerun; net path of the named-ratio signal (fee 40 bps; the original key "
                                "says 45bps)", {k: a[k] for k in own}, {k: rep[key][k] for k in own}, s,
                                {"metric": "fib_net_sharpe_45bps", "from_series": net, "reported": rep[key]["fib_net_sharpe_45bps"],
                                 "equal": net == rep[key]["fib_net_sharpe_45bps"] and fib["r"]["trades"] == rep[key]["fib_trades"]},
                                code, "the archived JSON key reads '45bps' but the script charges fee=40 bps; the path "
                                "is the 40 bps net path the script actually computed"))
            s = path(thirds, "gross")
            g = round(cp.sharpe(s.ret, thirds["bpy"]), 3)
            out.append(_outcome(f"{base}|control:thirds_levels", "fib.py rerun; gross path of the (0.333, 0.5, 0.667) control",
                                {"thirds_levels_gross": a["thirds_levels_gross"]}, {"thirds_levels_gross": rep[key]["thirds_levels_gross"]},
                                s, {"metric": "thirds_levels_gross", "from_series": g, "reported": rep[key]["thirds_levels_gross"],
                                    "equal": g == rep[key]["thirds_levels_gross"]}, code))
            gross = sorted(cp.sharpe(x["r"]["gross"], x["bpy"]) for x in controls)
            fg = cp.sharpe(fib["r"]["gross"], fib["bpy"])
            stat = {"random_levels_median_gross": round(gross[len(gross) // 2], 3),
                    "fib_percentile_among_random": round(sum(1 for c in gross if c < fg) / len(gross), 2)}
            out.append(_outcome(f"{base}|control:random_levels", "fib.py rerun; median and percentile over the 40 seeded "
                                "random level sets (an aggregate of 40 paths, not one path)",
                                {k: a[k] for k in stat}, {k: rep[key][k] for k in stat}, None, None, code,
                                f"recomputed from the 40 captured control paths: {stat}"))

        # -- xsec.py: weekly cross-sectional momentum on the 18-coin universe ------------------------------------
        sb.place("xsec.py", script_bytes(root, "research_2026-10-02/xsec.py", script_sha["xsec.py"]))
        appends: list[int] = []
        books: list[dict] = []

        def at_append_run(frame):
            appends.append((frame.f_locals["t"] + frame.f_locals["j"] + 1) * DAY)

        def at_append_basket(frame):
            appends.append((frame.f_locals["t"] + 1) * DAY)

        def rec_sharpe(args, kwargs, res, caller):
            if caller.f_code.co_name in ("run", "basket") and caller.f_code.co_filename.endswith("xsec.py"):
                books.append({"fn": caller.f_code.co_name, "ret": list(args[0]), "ts": list(appends),
                              "args": {k: caller.f_locals.get(k) for k in ("k", "look", "hold", "cost_bps", "long_short")}})
                appends.clear()

        with recording(cp, "sharpe", rec_sharpe):
            sb.run_script("xsec.py", probe_list=(
                LineProbe("", "run", "rets.append(day_r - (turnover * c if j == 0 else 0.0))", at_append_run),
                LineProbe("", "basket", "rets.append(sum(rs) / len(rs))", at_append_basket)))
        rep = sb.read_json("xsec.json")
        order = ["long_only_top3_85bps", "long_only_top3_45bps", "long_short_3x3_perps_6bps", "long_short_3x3_85bps",
                 "equal_weight_basket_hold"]
        expected_args = [(85.0, False), (45, False), (6, True), (85, True), None]
        for key, b, exp in zip(order, books, expected_args):
            tid = f"adhoc-2026-10-02|universe|xsec|{key}"
            args_ok = exp is None or (b["args"]["cost_bps"] == exp[0] and b["args"]["long_short"] == exp[1])
            s = Series(b["ts"], b["ret"], "daily")
            sh = round(cp.sharpe(s.ret, 365.0), 3)
            out.append(_outcome(tid, "xsec.py rerun; daily book returns", arch["xsec"][key], rep.get(key), s,
                                {"metric": "sharpe", "from_series": sh, "reported": rep.get(key, {}).get("sharpe"),
                                 "days": len(s.ret), "call_arguments_match": args_ok,
                                 "equal": args_ok and len(s.ts) == len(s.ret) and sh == rep.get(key, {}).get("sharpe")
                                 and len(s.ret) == rep.get(key, {}).get("days")},
                                {"script": "research_2026-10-02/xsec.py", **code_in},
                                "universe = the 18 coins fetched on 2 Oct 2026 (incl. MATIC-USD, which the frozen "
                                "database does not hold); survivorship-biased as the script says"))

    # -- six.py: the withdrawn six-cycle calendar check (statistics only) -------------------------------------------
    with Sandbox(inputs, None) as sb:
        for n in ("BTC-USD_3600.json", "BTC-USD_86400.json", "ETH-USD_3600.json", "ETH-USD_86400.json"):
            sb.place(n, inputs.read(f"{COINBASE}/{n}.gz"))
        sb.place("six.py", inputs.read("scripts/research_2026-10-02/six.py"))
        sb.run_script("six.py")
        rep = sb.read_json("six.json")
    archived_six = json.loads(inputs.read("scripts/research_2026-10-02/six.json"))
    out.append(_outcome("adhoc-2026-10-02|BTC-USD|six_cycle_calendar_checks", "six.py rerun (permutation tests)",
                        archived_six, rep, None, None,
                        {"script": "forensic/scripts/research_2026-10-02/six.py", "inputs": "coinbase_2026-10-02 BTC/ETH"},
                        "withdrawn check (status failed in the ledger); statistics only"))
    return out


# =================================================================================================================
# 2. owner ideas, 3 Oct 2026 (levels, Occam rules, Occam check, media, media volatility partials)
# =================================================================================================================
def owner_2026_10_03(root: Path, inputs: Inputs, frozen_db: Path, script_sha: dict[str, str]) -> list[Outcome]:
    out: list[Outcome] = []
    rel = "owner_ideas_2026-10-03"
    arch = {n: json.loads((root / f"data_v10/imports/apex_v05/{rel}/{n}.json").read_text())
            for n in ("levels", "occam", "occam_check", "media", "media_vol_partial")}
    db = str(frozen_db)
    code_in = {"code_tree": "v051_run (crypto_pack sha 6d5aef02)", "store": "frozen v0.9 database (sha ac53b123), "
               "byte-identical to the v0.5.1 store the scripts read"}
    with Sandbox(inputs, "v051_run") as sb:
        for n in ("levels", "occam", "occam_check", "media", "media_vol_partial"):
            sb.place(f"{n}.py", script_bytes(root, f"{rel}/{n}.py", script_sha[f"{n}.py"]))
        sb.place("media_data.json", inputs.read("inputs/owner_ideas_2026-10-03/media_data.json.gz"))

        # -- levels.py (statistics) --------------------------------------------------------------------------------
        sb.run_script("levels.py", argv=(db,))
        rep = sb.read_json("levels.json")
        n_all, bad_all = compare(_jsonish(arch["levels"]), _jsonish(rep))
        for key, v in arch["levels"]["verdicts"].items():
            name, metric = key.split(" | ")
            tid = f"owner_ideas_2026-10-03|BTC-USD|levels|{name}|{metric}"
            a = {"verdict": v, **{p: arch["levels"][p][name][metric] for p in ("2017-2021", "2022-2026", "full")},
                 "real": {p: arch["levels"][p][name]["real"] for p in ("2017-2021", "2022-2026", "full")}}
            b = {"verdict": rep["verdicts"].get(key), **{p: rep[p][name][metric] for p in ("2017-2021", "2022-2026", "full")},
                 "real": {p: rep[p][name]["real"] for p in ("2017-2021", "2022-2026", "full")}}
            out.append(_outcome(tid, "levels.py rerun (400 seeded placebos per family and period)", a, b, None, None,
                                {"script": f"{rel}/levels.py", **code_in},
                                f"whole levels.json: {n_all} values compared, {len(bad_all)} differ"))

        # -- occam.py: nine simple rules at 85 and 40 bps -----------------------------------------------------------
        cap: dict[tuple[str, int], dict] = {}

        def at_row(frame):
            loc = frame.f_locals
            cap[(loc["name"], loc["cost"])] = {"net": [float(x) for x in loc["net"]], "d": [int(x) for x in loc["d"]],
                                               "n_trials": loc["n_trials"]}

        g = sb.run_script("occam.py", argv=(db,), probe_list=(
            LineProbe("", "main", 'row[f"{cost}bps"] = {"full": stats(net, n_trials)', at_row),))
        rep = sb.read_json("occam.json")
        import numpy as np
        for rule, costs in arch["occam"]["rules"].items():
            for cost_key, a in costs.items():
                tid = f"owner_ideas_2026-10-03|BTC-USD|occam|{rule}|{cost_key}"
                c = cap.get((rule, int(cost_key[:-3])))
                b = rep["rules"].get(rule, {}).get(cost_key)
                if c is None or b is None:
                    out.append(Outcome(tid, "not_reproducible", "occam.py rerun", note="not produced by the rerun"))
                    continue
                full = g["stats"](np.array(c["net"]), c["n_trials"])
                s = Series([d * DAY for d in c["d"]], c["net"], "daily")
                out.append(_outcome(tid, "occam.py rerun; daily net returns after the 200-day warm-up", a, b, s,
                                    {"metric": "full", "from_series": full, "reported": b["full"],
                                     "equal": full == b["full"] and len(s.ts) == len(s.ret)
                                     and not any(math.isnan(x) for x in s.ret)},
                                    {"script": f"{rel}/occam.py", **code_in}))
        occam_btc = {r: cap.get((r, 85)) for r in ("hold", "sma200", "sma200_vt")}

        # -- occam_check.py: block bootstrap vs hold, and the same rule on ETH ------------------------------------
        chk: dict[str, dict] = {}

        def at_check(frame):
            loc = frame.f_locals
            chk[loc["asset"]] = {"nets": {k: [float(x) for x in v] for k, v in loc["nets"].items()},
                                 "days": [int(x) for x in loc["days"]], "first": int(loc["first"])}

        sb.run_script("occam_check.py", argv=(db,), probe_list=(
            LineProbe("", "main", 'row = {k: {"sharpe": round(sharpe(v), 3), "max_drawdown": round(mdd(v), 3),', at_check),))
        rep = sb.read_json("occam_check.json")
        consistent = all(chk["BTC-USD"]["nets"][r] == occam_btc[r]["net"] for r in occam_btc if occam_btc[r])
        for asset in ("BTC-USD", "ETH-USD"):
            for test in ("sma200_vs_hold", "sma200_vt_vs_hold"):
                tid = f"owner_ideas_2026-10-03|{asset}|occam_check|{test}"
                out.append(_outcome(tid, "occam_check.py rerun (2,000 seeded block-bootstrap resamples)",
                                    arch["occam_check"][asset][test], rep[asset][test], None, None,
                                    {"script": f"{rel}/occam_check.py", **code_in}))
        e = chk["ETH-USD"]
        for rule, kind in (("hold", "hold"), ("sma200", "sma200"), ("sma200_vt", "sma200_vt")):
            tid = f"owner_ideas_2026-10-03|ETH-USD|occam_check|{kind}"
            net = e["nets"][rule]
            # occam.run aligns returns to t+1 on the asset's own series c = px[first:]; nets keep net[200:]
            ts = [e["days"][e["first"] + 201 + m] * DAY for m in range(len(net))]
            s = Series(ts, net, "daily")
            sh = round(float(np.mean(net) / np.std(net) * math.sqrt(365)), 3) if np.std(net) > 0 else 0.0
            out.append(_outcome(tid, "occam_check.py rerun; ETH daily net returns at 85 bps",
                                arch["occam_check"]["ETH-USD"][rule], rep["ETH-USD"][rule], s,
                                {"metric": "sharpe", "from_series": sh, "reported": rep["ETH-USD"][rule]["sharpe"],
                                 "btc_paths_equal_occam_85bps": consistent,
                                 "equal": consistent and sh == rep["ETH-USD"][rule]["sharpe"]},
                                {"script": f"{rel}/occam_check.py", **code_in},
                                "dates follow occam.run's documented t+1 alignment; the same alignment applied to "
                                "BTC reproduces occam.py's own dated BTC paths exactly"))

        # -- media.py and media_vol_partial.py (statistics) ----------------------------------------------------------
        sb.run_script("media.py", argv=(db,))
        rep = sb.read_json("media.json")
        for feat, targets in arch["media"]["features"].items():
            for target, a in targets.items():
                tid = f"owner_ideas_2026-10-03|BTC-USD|media|{feat}|{target}"
                out.append(_outcome(tid, "media.py rerun (1,000 seeded permutations per test; archived data cache)", a,
                                    rep["features"].get(feat, {}).get(target), None, None,
                                    {"script": f"{rel}/media.py", **code_in, "cache": "forensic/inputs/media_data.json"}))
        sb.run_script("media_vol_partial.py", argv=(db,))
        rep = sb.read_json("media_vol_partial.json")
        for feat, a in arch["media_vol_partial"].items():
            tid = f"owner_ideas_2026-10-03|BTC-USD|media_vol_partial|{feat}"
            out.append(_outcome(tid, "media_vol_partial.py rerun", a, rep.get(feat), None, None,
                                {"script": f"{rel}/media_vol_partial.py", **code_in}))
    return out


# =================================================================================================================
# 3. governed APEX v0.5 research and hypotheses (ledger extract), and 4. v0.5.1 hypotheses
# =================================================================================================================
def _events(root: Path) -> list[dict]:
    return json.loads((root / "data_v10/imports/apex_v05/apex_ledger_extract.json").read_text())["events"]


def apex_v05(root: Path, inputs: Inputs, frozen_db: Path) -> list[Outcome]:
    out: list[Outcome] = []
    ev = _events(root)
    payloads: dict[str, dict] = {}
    for e in ev:
        if e["event_type"] == "ResearchTrial":
            payloads.setdefault(e["payload"]["name"], e["payload"])
    hyps = [e["payload"] for e in ev if e["event_type"] == "HypothesisTested"
            and e["payload"]["spec"].get("type") in ("calendar", "cycle")]          # the v0.5 registry (2 Oct)
    code_in = {"code_tree": "v05_run (research_v05 sha daf4f6a6; data_v05 4f5e1870)",
               "store": "frozen v0.9 database; its candles table equals the v0.5 store's (forensic/derived/v05_store_digest.json)"}
    with Sandbox(inputs, "v05_run") as sb:
        rv, dv = sb.module("apex.ext.research_v05"), sb.module("apex.ext.data_v05")
        cp = sb.module("apex.ext.crypto_pack")
        store = _Store(frozen_db)
        try:
            grid: dict = {}

            def at_rebal(frame):
                grid["rebal"] = list(frame.f_locals["rebal"])

            probe = LineProbe(rv.__file__, "run_research", "sigs = compute_signals(panel, rebal)", at_rebal)
            probe.resolve(Path(rv.__file__).read_text())
            panel = rv.Panel.from_store(store, list(dv.UNIVERSE))
            with probes([probe]):
                res = rv.run_research(panel, prior_trials=0, min_train=52)    # organism_v05 (v0.5) call, verbatim
            rows = res["evidence"]["rows"]
            rebal = grid["rebal"]
            for t in res["trials"]:
                tid = f"v0.5|universe|{t.name}"
                pl = payloads.get(t.name)
                if pl is None:
                    continue
                pairs = [((panel.days[i] + rv.HORIZON) * DAY, r) for i, r in zip(rebal, t.weekly) if r is not None]
                s = Series([a for a, _ in pairs], [b for _, b in pairs], "weekly")
                sh = round(cp.sharpe(s.ret, 52.0), 3)
                archived = {k: v for k, v in pl.items() if k != "name"}
                reproduced = {k: rows[t.name].get(k) for k in archived}
                out.append(_outcome(tid, "research_v05.run_research(Panel.from_store(store, UNIVERSE), prior_trials=0, "
                                    "min_train=52) as organism_v05 called it; weekly book returns",
                                    archived, reproduced, s,
                                    {"metric": "sharpe", "from_series": sh, "reported": rows[t.name]["sharpe"],
                                     "weeks": len(s.ret), "equal": sh == rows[t.name]["sharpe"] and len(s.ret) == rows[t.name]["weeks"]},
                                    {"module": "apex.ext.research_v05", **code_in},
                                    "weekly return realized 7 days after each rebalance; keyed by that day's candle ts"))
            for h in hyps:
                tid = f"v0.5|hypothesis|{h['id']}"
                r = rv.test_hypothesis(store, h["spec"])                       # organism_v05 (v0.5) call, verbatim
                out.append(_outcome(tid, "research_v05.test_hypothesis(store, spec) (300 seeded permutations)",
                                    h["result"], r, None, None, {"module": "apex.ext.research_v05", **code_in}))
        finally:
            store.close()
    return out


def apex_v051(root: Path, inputs: Inputs, frozen_db: Path) -> list[Outcome]:
    out: list[Outcome] = []
    ev = _events(root)
    tested = [e["payload"] for e in ev if e["event_type"] == "HypothesisTested"]
    v05 = [h for h in tested if h["spec"].get("type") in ("calendar", "cycle")]
    v051 = [h for h in tested if h["spec"].get("type") in ("level", "rule", "feature")]
    prior = len({e["payload"]["name"] for e in ev if e["event_type"] == "ResearchTrial"}) + len(v05)
    code_in = {"code_tree": "v051_run (hypotheses_v051 sha d3cfc227)", "store": "frozen v0.9 database (sha ac53b123) = "
               "the v0.5.1 store after the run"}
    with Sandbox(inputs, "v051_run") as sb:
        hv = sb.module("apex.ext.hypotheses_v051")
        store = _Store(frozen_db)
        try:
            for k, h in enumerate(v051, start=1):
                tid = f"v0.5.1|hypothesis|{h['id']}"
                n_trials = prior + k            # organism_v05.test_pending_hypotheses: n_prior counts every prior trial
                cap: dict = {}

                def at_rule(frame):
                    cap.update(net=list(frame.f_locals["net"]), days=list(frame.f_locals["days"]))

                probe = LineProbe(hv.__file__, "test_rule",
                                  'res: dict[str, Any] = {"rule": _summary(net), "hold": _summary(hold), "cost_bps": cost,',
                                  at_rule)
                probe.resolve(Path(hv.__file__).read_text())
                with probes([probe]):
                    r = hv.test_hypothesis(store, h["spec"], n_trials=n_trials)
                if h["spec"].get("type") == "rule" and cap:
                    s = Series([int(x) for x in cap["days"]], cap["net"], "daily")
                    summ = hv._summary(s.ret)
                    out.append(_outcome(tid, f"hypotheses_v051.test_hypothesis(store, spec, n_trials={n_trials}); daily "
                                        "net returns of the rule", h["result"], r, s,
                                        {"metric": "rule summary", "from_series": summ, "reported": r.get("rule"),
                                         "equal": summ == r.get("rule") and len(s.ts) == len(s.ret)},
                                        {"module": "apex.ext.hypotheses_v051", **code_in},
                                        f"n_trials={n_trials}: 21 trials before the v0.5.1 run plus this hypothesis's "
                                        "position in the registry order"))
                else:
                    out.append(_outcome(tid, f"hypotheses_v051.test_hypothesis(store, spec, n_trials={n_trials})",
                                        h["result"], r, None, None, {"module": "apex.ext.hypotheses_v051", **code_in}))
        finally:
            store.close()
    return out
