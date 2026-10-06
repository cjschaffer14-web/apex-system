"""Build the research trial ledger: one TrialRecord per genuinely evaluated hypothesis or parameterization.

Sources
  frozen v0.9 package   v0.6 batch (runs + 50 placebos per asset), v0.8 real runs, v0.7-code neural ablation,
                        v0.9 experts / mixtures at 6, 25, 85 bps, Matrix Kelly, expert-by-state conditional cells,
                        geometry target cells, state forward distributions
  APEX v0.5 / v0.5.1    governed research trials and owner hypotheses (hash-chained ledger extract) and the
                        research scripts run on the same Coinbase candles (2-3 Oct 2026)

Rules (Stage 0 review)
  * distinct hypotheses stay distinct even when their returns are identical; they share `return_equivalence_id`
  * only duplicate artifact rows of the same trial collapse, into `artifact_refs`
  * controls, placebos, cost sensitivities, failed and withdrawn trials stay in the ledger
  * a return series is stored only after its recomputed summary reproduces the frozen numbers
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

import numpy as np

from ..data.archive import gzip_deterministic
from ..interfaces import ReturnsStatus as RS
from ..interfaces import TrialKind as K
from ..interfaces import TrialRecord, TrialStatus, canonical_json
from . import reconstruct as R

RETURNS_REL = "ledger/returns"
LEDGER_REL = "ledger/trial_ledger.jsonl"
SUMMARY_REL = "ledger/LEDGER_SUMMARY.json"
RECON_REL = "reports/reconstruction_reconciliation.json"
IMPORTS_REL = "data_v10/imports/apex_v05"
BASE_DB = R.BASELINE_DB_SHA256
SPEC_V09 = "e3415de69d1ba2e56f6afeb71fd61be2feb7253b061b5cc1b61a60ffbf4b4707"
PAIRS = ("BTC-USD", "ETH-USD")
SLUG = {"BTC-USD": "btc", "ETH-USD": "eth"}


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha_file(p: Path) -> str:
    return _sha_bytes(p.read_bytes())


class Store:
    """Writes return series as deterministic gzip CSV; returns (ref, file sha, equivalence id)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        (root / RETURNS_REL).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def equivalence_id(ts, ret) -> str:
        return _sha_bytes("".join(f"{int(t)}:{float(r)!r}\n" for t, r in zip(ts, ret)).encode())

    def write(self, rel_name: str, ts, ret) -> tuple[str, str, str]:
        ret = np.asarray(ret, float)
        if not np.all(np.isfinite(ret)):
            raise ValueError(f"non-finite return in {rel_name}")
        text = "ts,ret\n" + "".join(f"{int(t)},{float(r)!r}\n" for t, r in zip(ts, ret))
        gz = gzip_deterministic(text.encode())
        rel = f"{RETURNS_REL}/{rel_name}.csv.gz"
        (self.root / rel).write_bytes(gz)
        return rel, _sha_bytes(gz), self.equivalence_id(ts, ret)

    def write_events(self, rel_name: str, header: list[str], rows: list[list[Any]]) -> tuple[str, str]:
        text = ",".join(header) + "\n" + "".join(",".join(repr(x) if isinstance(x, float) else str(x) for x in r) + "\n"
                                                 for r in rows)
        gz = gzip_deterministic(text.encode())
        rel = f"{RETURNS_REL}/{rel_name}.csv.gz"
        (self.root / rel).write_bytes(gz)
        return rel, _sha_bytes(gz)


class Recon:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, trial_id: str, ok: bool, max_abs_diff: float, what: str) -> bool:
        self.rows.append({"trial_id": trial_id, "pass": bool(ok), "max_abs_diff": max_abs_diff, "compared": what})
        return ok


def _window(ts) -> dict:
    return {"full_sample": [int(ts[0]), int(ts[-1])]}


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if not (isinstance(v, float) and not math.isfinite(v))}


# =================================================================================================================
def frozen_trials(root: Path, store: Store, recon: Recon) -> list[TrialRecord]:
    fz = R.Frozen(root)
    out: list[TrialRecord] = []
    try:
        code06 = fz.code_sha256("trading_backtest_v06")
        code07 = fz.code_sha256("trading_backtest_v06", "trading_backtest_v07")
        code08 = fz.code_sha256("trading_backtest_v06", "trading_backtest_v07", "trading_backtest_v08")
        code09 = fz.code_sha256("trading_backtest_v06", "trading_backtest_v07", "trading_backtest_v08", "trading_backtest_v09")

        for pair in PAIRS:
            data = fz.data(pair)
            slug = SLUG[pair]
            # ---- v0.6 batch: 14 runs + 50 placebos ---------------------------------------------------------
            fname = f"{slug}_v06_historical_25bps.json"
            frozen = fz.results(fname)
            res, series = R.capture_v06(fz, pair, 25.0)
            same_file = json.loads(json.dumps(res)) == frozen
            recon.add(f"v0.6|{pair}|batch", same_file, 0.0 if same_file else math.inf, f"v06.batch output == {fname}")
            runs = {r["name"]: r for r in frozen["runs"]}
            plac = frozen["controls"]["T12_fibonacci_placebo"]["placebos"]
            for s in series:
                tid = f"v0.6|{pair}|{s.name}|25bps"
                stats = fz.v6.period_stats(data, s.ret, s.turn)
                if s.name.startswith("T12_placebo_"):
                    j = int(s.name.rsplit("_", 1)[1])
                    f = plac[j]
                    got = stats["full"]
                    ok = got.get("sharpe", 0.0) == f["sharpe"] and got.get("cagr", 0.0) == f["cagr"]
                    recon.add(tid, ok, 0.0 if ok else math.inf, "placebo sharpe and cagr vs controls.placebos")
                    params = {"orchestrator": "v06.batch", "cost_bps": 25.0, "seed": 20261003, "placebo_index": j,
                              "fib_anchors": list(f["anchors"])}
                    metrics = {"sharpe": f["sharpe"], "cagr": f["cagr"]}
                    kind, refs = K.CONTROL, (f"baseline_v09/results/{fname}#controls.T12_fibonacci_placebo.placebos[{j}]",)
                else:
                    ok = json.loads(json.dumps(stats)) == runs[s.name]["stats"]
                    recon.add(tid, ok, 0.0 if ok else math.inf, "period_stats (full/pre/post) vs frozen run")
                    params = {"orchestrator": "v06.batch", "cost_bps": 25.0, "seed": 20261003}
                    metrics = runs[s.name]["stats"]
                    kind = K.CONTROL if (s.name in ("hold", "sma200") or "_control_" in s.name) else K.CANDIDATE
                    refs = (f"baseline_v09/results/{fname}#runs[{s.name}]", f"baseline_v09/results/{slug}_v06_historical_25bps.md")
                st = RS.STORED if ok else RS.UNAVAILABLE
                ref = sha = eq = None
                if ok:
                    ref, sha, eq = store.write(f"v06_{slug}_{s.name}_25bps", s.ts, s.ret)
                out.append(TrialRecord(tid, "v0.6", "v06." + s.name.split("_")[0], s.name, kind, params, pair,
                                       "coinbase", "spot", code06, None, BASE_DB, _window(s.ts), "v06.flat_bps:25",
                                       metrics, st, "daily" if ok else "none", ref, sha, eq, artifact_refs=refs))

            # ---- v0.8 real runs ----------------------------------------------------------------------------
            fname = f"{slug}_real_v08_25bps.json"
            frozen = fz.results(fname)
            res, series = R.capture_v08(fz, pair, 25.0)
            same_file = json.loads(json.dumps(res)) == frozen
            recon.add(f"v0.8|{pair}|run_real_single", same_file, 0.0 if same_file else math.inf, f"output == {fname}")
            ladder = {(r["pair"], r["name"]): r for r in csv.DictReader(open(root / "baseline_v09/results/frozen_ladder_v08_25bps.csv"))}
            for row, s in zip(frozen["runs"], series):
                tid = f"v0.8|{pair}|{s.name}|25bps"
                stats = fz.v6.stats(s.ret)
                keys = [k for k in stats if k in row]
                ok, diff = R.stats_equal(stats, row, keys)
                recon.add(tid, ok, diff, "v06.stats vs frozen run row")
                refs = [f"baseline_v09/results/{fname}#runs[{s.name}]"]
                lad = ladder.get((pair, s.name))
                if lad and abs(float(lad["sharpe"]) - row["sharpe"]) < 1e-12:
                    refs.append(f"baseline_v09/results/frozen_ladder_v08_25bps.csv#{pair},{s.name}")
                kind = K.CONTROL if "placebo" in s.name.lower() else K.CANDIDATE
                ref = sha = eq = None
                if ok:
                    ref, sha, eq = store.write(f"v08_{slug}_{s.name}_25bps", s.ts, s.ret)
                out.append(TrialRecord(tid, "v0.8", "v08." + s.name.split("_")[0], s.name, kind,
                                       {"orchestrator": "v08.run_real_single", "cost_bps": 25.0, "seed": 20261003},
                                       pair, "coinbase", "spot", code08, None, BASE_DB, _window(s.ts), "v08.flat_bps:25",
                                       _clean({k: v for k, v in row.items() if k != "name"}), RS.STORED if ok else RS.UNAVAILABLE,
                                       "daily" if ok else "none", ref, sha, eq, artifact_refs=tuple(refs)))

            # ---- neural ablation (v0.7 code, real data, 25 bps) ---------------------------------------------
            na = fz.results("neural_ablation_real_25bps.json")[pair]
            na_csv = [r for r in csv.DictReader(open(root / "baseline_v09/results/neural_ablation_real_25bps.csv")) if r["pair"] == pair]
            variants = [("NN_generic", False, False, (.382, .5, .618)), ("NN_fractal", True, False, (.382, .5, .618)),
                        ("NN_fractal_namedFib", True, True, (.382, .5, .618)),
                        ("NN_fractal_placeboFib", True, True, (.271, .447, .733))]   # table frozen in v07.run_sweep
            frozen_runs = {r["name"]: r for r in na["runs"]}
            for name, fr, fb, anchors in variants:
                tid = f"v0.7nn|{pair}|{name}|25bps"
                e, p, nm = fz.v7.walkforward_mlp_exposure(data, fr, fb, anchors, seed=20261003)
                net, turn, _ = fz.v6.run_vector(data, e, 25.0)
                stats = fz.v6.period_stats(data, net, turn)
                f = frozen_runs[name]
                ok = json.loads(json.dumps(stats)) == f["stats"] and len(nm) == f["features"] \
                    and float(np.mean(e > 0)) == f["signal_rate"]
                recon.add(tid, ok, 0.0 if ok else math.inf, "period_stats + feature count + signal rate vs frozen")
                ts = data["ts"][1:]
                ref = sha = eq = None
                if ok:
                    ref, sha, eq = store.write(f"v07nn_{slug}_{name}_25bps", ts, net)
                refs = (f"baseline_v09/results/neural_ablation_real_25bps.json#{pair}.runs[{name}]",
                        f"baseline_v09/results/neural_ablation_real_25bps.csv#{pair},{name}")
                out.append(TrialRecord(tid, "v0.7-nn", "v07.walkforward_mlp", name,
                                       K.CONTROL if "placebo" in name.lower() else K.CANDIDATE,
                                       {"use_fractal": fr, "use_fib": fb, "fib_anchors": list(anchors) if fb else None,
                                        "seed": 20261003, "cost_bps": 25.0, "generator": "v07.run_sweep variant table"},
                                       pair, "coinbase", "spot", code07, None, BASE_DB, _window(ts), "v06.flat_bps:25",
                                       f["stats"], RS.STORED if ok else RS.UNAVAILABLE, "daily" if ok else "none",
                                       ref, sha, eq, artifact_refs=refs,
                                       notes="generator script not in the package; reconstructed from the frozen v0.7 code"))

            # ---- v0.9 experts, mixtures, conditional cells, geometry, state forward ------------------------
            hist = fz.results("historical_v09_results.json")[pair]
            states = R.capture_v09_states(fz, pair)
            mix_csv = {(r["pair"], r["cost_bps"], r["mixture"]): r for r in
                       csv.DictReader(open(root / "baseline_v09/results/mixture_cost_sensitivity.csv"))}
            primary: dict[str, str] = {}
            for cost in (25.0, 6.0, 85.0):
                c = str(int(cost))
                cr = hist["cost_runs"][c]
                for s in R.capture_v09_asset(fz, pair, cost):
                    kind_name, nm = s.name.split(":", 1)
                    frozen_stats = cr["experts"][nm] if kind_name == "expert" else cr[nm]
                    stats = fz.v6.stats(s.ret)
                    ok, diff = R.stats_equal(stats, frozen_stats, tol=1e-12)
                    tid = f"v0.9|{pair}|{nm}|{c}bps"
                    recon.add(tid, ok, diff, "v06.stats vs historical_v09_results cost run")
                    if cost == 25.0:
                        primary[nm] = tid
                        kind = K.CONTROL if nm in ("hold_long", "sma200_long") else K.CANDIDATE
                        parent = None
                    else:
                        kind, parent = K.SENSITIVITY, primary[nm]
                    refs = [f"baseline_v09/results/historical_v09_results.json#{pair}.cost_runs.{c}.{'experts.' if kind_name == 'expert' else ''}{nm}"]
                    if kind_name == "mixture" and (pair, c, nm) in mix_csv:
                        refs.append(f"baseline_v09/results/mixture_cost_sensitivity.csv#{pair},{c},{nm}")
                    ref = sha = eq = None
                    if ok:
                        ref, sha, eq = store.write(f"v09_{slug}_{nm}_{c}bps", s.ts, s.ret)
                    out.append(TrialRecord(tid, "v0.9", f"v09.{kind_name}", nm, kind,
                                           {"cost_bps": cost, "frozen_spec": "FROZEN_SPEC_v09.json"}, pair, "coinbase", "spot",
                                           code09, SPEC_V09, BASE_DB, _window(s.ts), f"v06.flat_bps:{c}", frozen_stats,
                                           RS.STORED if ok else RS.UNAVAILABLE, "daily" if ok else "none", ref, sha, eq,
                                           parent_trial_id=parent, artifact_refs=tuple(refs)))
                    # conditional (expert x previous-day state) cells, from the same series
                    if kind_name == "expert":
                        s_prev = states[:-1]
                        for cell in cr["conditional"]:
                            if cell["expert"] != nm:
                                continue
                            mask = s_prev == cell["state"]
                            sub = s.ret[mask]
                            okc = len(sub) == cell["n"] and float(np.mean(sub)) == cell["mean_daily"]
                            ctid = f"v0.9|{pair}|cond:{nm}|state={cell['state']}|{c}bps"
                            recon.add(ctid, okc, 0.0 if okc else abs(float(np.mean(sub)) - cell["mean_daily"]),
                                      "conditional n and mean vs frozen")
                            ckind = K.HYPOTHESIS_TEST if cost == 25.0 else K.SENSITIVITY
                            cparent = None if cost == 25.0 else f"v0.9|{pair}|cond:{nm}|state={cell['state']}|25bps"
                            out.append(TrialRecord(ctid, "v0.9", "v09.conditional_expert_state", f"{nm}|{cell['state']}", ckind,
                                                   {"expert": nm, "state": cell["state"], "cost_bps": cost,
                                                    "rule": "returns on days whose previous close was in this state"},
                                                   pair, "coinbase", "spot", code09, SPEC_V09, BASE_DB, _window(s.ts),
                                                   f"v06.flat_bps:{c}", cell,
                                                   RS.RECONSTRUCTABLE if okc else RS.UNAVAILABLE, "none",
                                                   f"derived:{tid}?prev_state={cell['state']}" if okc else None,
                                                   parent_trial_id=cparent,
                                                   artifact_refs=(f"baseline_v09/results/historical_v09_results.json#{pair}.cost_runs.{c}.conditional",)))

            # geometry target cells (event-based hypothesis tests)
            g = hist["geometry"]
            ev = sorted(g["events"], key=lambda e: (e["horizon"], e["scale"], e["ref"], e["ratio"], e["t"]))
            header = ["horizon", "scale", "ref", "ratio", "t", "ts", "direction", "outcome", "signed_return", "bars"]
            rows = [[e["horizon"], e["scale"], e["ref"], float(e["ratio"]), e["t"], int(data["ts"][e["t"]]), e["direction"],
                     e["outcome"], float(e["signed_return"]), e["bars"]] for e in ev]
            gref, gsha = store.write_events(f"v09_{slug}_geometry_events", header, rows)
            cells = defaultdict(list)
            for e in ev:
                cells[(e["horizon"], e["scale"], e["ref"], float(e["ratio"]))].append(e)
            named_csv = {(r["pair"], int(r["horizon"]), r["scale"], r["ref"], float(r["ratio"])) for r in
                         csv.DictReader(open(root / "baseline_v09/results/geometry_named_vs_neighbors.csv"))}
            for cell in g["summary"]:
                key = (cell["horizon"], cell["scale"], cell["ref"], float(cell["ratio"]))
                evs = cells[key]
                vals = [float(e["signed_return"]) for e in evs]
                okg = len(vals) == cell["n"] and math.isclose(float(np.mean(vals)), cell["mean_signed_return"], rel_tol=0, abs_tol=1e-15)
                gtid = f"v0.9|{pair}|geometry|h={key[0]}|{key[1]}|{key[2]}|r={key[3]:g}"
                recon.add(gtid, okg, 0.0 if okg else math.inf, "event count and mean vs geometry summary")
                refs = [f"baseline_v09/results/historical_v09_results.json#{pair}.geometry.summary"]
                if (pair, key[0], key[1], key[2], key[3]) in named_csv:
                    refs.append(f"baseline_v09/results/geometry_named_vs_neighbors.csv#{pair},{key[0]},{key[1]},{key[2]},{key[3]:g}")
                eq = Store.equivalence_id([e["t"] for e in evs], vals) if okg else None
                out.append(TrialRecord(gtid, "v0.9", "v09.geometry_target_cell", f"h{key[0]}_{key[1]}_{key[2]}_{key[3]:g}",
                                       K.HYPOTHESIS_TEST, {"horizon_days": key[0], "scale": key[1], "reference": key[2],
                                                           "ratio": key[3], "invalidation": "0.5 ATR beyond confirmed wave-4"},
                                       pair, "coinbase", "spot", code09, SPEC_V09, BASE_DB, _window(data["ts"]), "none",
                                       _clean(cell), RS.STORED if okg else RS.UNAVAILABLE, "event" if okg else "none",
                                       f"{gref}#horizon={key[0]}&scale={key[1]}&ref={key[2]}&ratio={key[3]:g}" if okg else None,
                                       gsha if okg else None, eq, artifact_refs=tuple(refs)))

            # state forward distributions (generator not in package; reconstruct and verify against the CSV)
            c = np.asarray(data["close"], float)
            for r in csv.DictReader(open(root / "baseline_v09/results/state_forward_distributions.csv")):
                if r["pair"] != pair:
                    continue
                h, st = int(r["h"]), r["state"]
                vals = np.array([c[t + h] / c[t] - 1 for t in range(len(c) - h) if states[t] == st])
                oks = len(vals) == int(r["n"]) and len(vals) > 0 and math.isclose(float(np.mean(vals)), float(r["mean"]), rel_tol=1e-12)
                stid = f"v0.9|{pair}|state_forward|{st}|h={h}"
                recon.add(stid, oks, 0.0 if oks else math.inf, "n and mean vs state_forward_distributions.csv (rebuilt rule)")
                out.append(TrialRecord(stid, "v0.9", "v09.state_forward_distribution", f"{st}|h{h}", K.HYPOTHESIS_TEST,
                                       {"state": st, "horizon_days": h, "rule": "close[t+h]/close[t]-1 for t with state[t]"},
                                       pair, "coinbase", "spot", code09, SPEC_V09, BASE_DB, _window(data["ts"]), "none",
                                       {k: float(v) if k not in ("pair", "state") else v for k, v in r.items()},
                                       RS.RECONSTRUCTABLE if oks else RS.UNAVAILABLE, "none",
                                       f"derived:v09.classify_states|{st}|h={h}" if oks else None,
                                       artifact_refs=(f"baseline_v09/results/state_forward_distributions.csv#{pair},{st},{h}",)))

        # ---- Matrix Kelly (BTC+ETH pair) --------------------------------------------------------------------
        res, series = R.capture_v09_kelly(fz, 25.0)
        kcsv = list(csv.DictReader(open(root / "baseline_v09/results/matrix_kelly_btc_eth_25bps.csv")))
        hist_k = fz.results("historical_v09_results.json")["matrix_kelly_25bps"]["rows"]
        for i, (row, s) in enumerate(zip(hist_k, series)):
            stats = fz.v6.stats(s.ret)
            ok, diff = R.stats_equal(stats, row, [k for k in stats if k in row], tol=1e-12)
            tid = f"v0.9|BTC-USD+ETH-USD|matrix_kelly|fraction={row['fraction']:g}|25bps"
            recon.add(tid, ok, diff, "v06.stats vs historical matrix_kelly_25bps row")
            ref = sha = eq = None
            if ok:
                ref, sha, eq = store.write(f"v09_pair_matrix_kelly_f{row['fraction']:g}_25bps", s.ts, s.ret)
            out.append(TrialRecord(tid, "v0.9", "v09.matrix_kelly_pair", f"matrix_kelly_f{row['fraction']:g}", K.CANDIDATE,
                                   {"fraction": row["fraction"], "gross_cap": 3.0, "per_asset_cap": 2.0, "signal": "sma200",
                                    "ridge": 0.20, "cost_bps": 25.0}, "BTC-USD+ETH-USD", "coinbase", "pair", code09,
                                   SPEC_V09, BASE_DB, _window(s.ts), "v06.flat_bps:25", _clean(row),
                                   RS.STORED if ok else RS.UNAVAILABLE, "daily" if ok else "none", ref, sha, eq,
                                   artifact_refs=(f"baseline_v09/results/historical_v09_results.json#matrix_kelly_25bps.rows[{i}]",
                                                  f"baseline_v09/results/matrix_kelly_btc_eth_25bps.csv#row{i}")))
    finally:
        fz.close()
    return out


# =================================================================================================================
def apex_v05_trials(root: Path) -> list[TrialRecord]:
    """APEX v0.5 / v0.5.1 research history on the same Coinbase candles (returns were not saved: unavailable)."""
    imp = root / IMPORTS_REL
    out: list[TrialRecord] = []
    v05_db = "3b1d1bf6168efd92025c5f6afc3cabfc00999bebdd6e80cdcc575873b30c2e1b"   # APEX v0.5 store; candles == baseline
    code_r = _sha_file(imp / "code/research_v05.py")
    code_h = _sha_bytes((imp / "code/hypotheses_v051.py").read_bytes() + (imp / "code/research_v05.py").read_bytes())
    note_db = "run on the APEX v0.5 store, whose candles table is logically identical to the frozen v0.9 database"
    led = json.loads((imp / "apex_ledger_extract.json").read_text())["events"]

    # governed research trials (the research ran twice on the same data: one trial, two artifact rows)
    seen: dict[str, list] = defaultdict(list)
    for e in led:
        if e["event_type"] == "ResearchTrial":
            seen[e["payload"]["name"]].append(e)
    for name, evs in sorted(seen.items()):
        metrics = evs[0]["payload"]
        same = all(json.dumps(x["payload"], sort_keys=True) == json.dumps(metrics, sort_keys=True) for x in evs)
        out.append(TrialRecord(f"v0.5|universe|{name}", "v0.5", "apex.research_v05." + name.split(":")[0], name,
                               K.CANDIDATE, {"universe": "20 Coinbase USD pairs", "rebalance": "weekly", "horizon_days": 7,
                                             "min_train_weeks": 52}, "universe20", "coinbase",
                               "perp_cost_model" if "perps" in name else "spot_or_signal", code_r, None, v05_db,
                               {"full_sample": "weekly, 2015-2026"}, "apex.v05.venues", metrics, RS.UNAVAILABLE,
                               artifact_refs=tuple(f"{IMPORTS_REL}/apex_ledger_extract.json#{x['event_id']}" for x in evs),
                               notes=note_db + ("" if same else "; NOTE: the two runs reported different metrics")))
    # owner hypotheses (registered before testing)
    for e in led:
        if e["event_type"] != "HypothesisTested":
            continue
        p = e["payload"]
        spec = p["spec"]
        kind = K.CANDIDATE if spec.get("type") == "rule" else K.HYPOTHESIS_TEST
        version = "v0.5.1" if spec.get("type") in ("level", "rule", "feature") else "v0.5"
        out.append(TrialRecord(f"{version}|hypothesis|{p['id']}", version, f"apex.hypothesis.{spec.get('type')}",
                               p["name"], kind, spec, spec.get("product", "BTC-USD"), "coinbase", "spot",
                               code_h if version == "v0.5.1" else code_r, None, v05_db, {"periods": "before 2022 / from 2022"},
                               f"cost_bps:{spec.get('cost_bps', 'n/a')}", p["result"], RS.UNAVAILABLE,
                               artifact_refs=(f"{IMPORTS_REL}/apex_ledger_extract.json#{e['event_id']}",), notes=note_db))

    # research scripts of 2 Oct (pre-v0.5) and 3 Oct (owner ideas)
    def script(rel: str) -> str:
        return _sha_file(imp / rel)

    base = json.loads((imp / "research_2026-10-02/baseline.json").read_text())
    c_base = script("research_2026-10-02/baseline.py")
    for key, m in sorted(base.items()):
        pair, gran, fee = key.split()
        primary = f"adhoc-2026-10-02|{pair}|walk_forward|{gran}|fee80"
        is_primary = fee == "fee80"
        out.append(TrialRecord(primary if is_primary else f"adhoc-2026-10-02|{pair}|walk_forward|{gran}|{fee}",
                               "adhoc-2026-10-02", "v041.walk_forward", f"walk_forward_{gran}", K.CANDIDATE if is_primary else K.SENSITIVITY,
                               {"granularity": gran, "fee": fee, "rule_grid": "crypto_pack.STRATEGY_GRID (8 rules)",
                                "n_trials_arg": 6}, pair, "coinbase", "spot", c_base, None, v05_db,
                               {"walk_forward": "train 365/test 90 days (daily); 90/30 days (hourly)"}, f"v041.fee_bps:{fee[3:]}",
                               m, RS.UNAVAILABLE, parent_trial_id=None if is_primary else primary,
                               artifact_refs=(f"{IMPORTS_REL}/research_2026-10-02/baseline.json#{key}",),
                               notes="per-fold selection over the 8-rule grid happened inside each run"))
    fib = json.loads((imp / "research_2026-10-02/fib.json").read_text())
    c_fib = script("research_2026-10-02/fib.py")
    for key, m in sorted(fib.items()):
        pair, gran = key.split()
        tid = f"adhoc-2026-10-02|{pair}|fibonacci_levels|{gran}"
        out.append(TrialRecord(tid, "adhoc-2026-10-02", "adhoc.fibonacci_levels", f"fib_{gran}", K.CANDIDATE,
                               {"granularity": gran}, pair, "coinbase", "spot", c_fib, None, v05_db, {"full_sample": gran},
                               "adhoc.fib:45bps", m, RS.UNAVAILABLE,
                               artifact_refs=(f"{IMPORTS_REL}/research_2026-10-02/fib.json#{key}",)))
        for ctl in ("random_levels", "thirds_levels"):
            out.append(TrialRecord(f"{tid}|control:{ctl}", "adhoc-2026-10-02", "adhoc.fibonacci_levels", f"{ctl}_{gran}",
                                   K.CONTROL, {"granularity": gran, "control": ctl}, pair, "coinbase", "spot", c_fib, None,
                                   v05_db, {"full_sample": gran}, "adhoc.fib:gross", m, RS.UNAVAILABLE,
                                   artifact_refs=(f"{IMPORTS_REL}/research_2026-10-02/fib.json#{key}",)))
    xs = json.loads((imp / "research_2026-10-02/xsec.json").read_text())
    c_x = script("research_2026-10-02/xsec.py")
    xkind = {"long_only_top3_85bps": (K.CANDIDATE, None), "long_only_top3_45bps": (K.SENSITIVITY, "long_only_top3_85bps"),
             "long_short_3x3_perps_6bps": (K.CANDIDATE, None),
             "long_short_3x3_85bps": (K.SENSITIVITY, "long_short_3x3_perps_6bps"), "equal_weight_basket_hold": (K.CONTROL, None)}
    for key, m in sorted(xs.items()):
        kind, parent = xkind[key]
        out.append(TrialRecord(f"adhoc-2026-10-02|universe|xsec|{key}", "adhoc-2026-10-02", "adhoc.cross_sectional", key,
                               kind, {"strategy": key}, "universe20", "coinbase", "spot", c_x, None, v05_db,
                               {"full_sample": "daily"}, f"adhoc.xsec:{key}", m, RS.UNAVAILABLE,
                               parent_trial_id=f"adhoc-2026-10-02|universe|xsec|{parent}" if parent else None,
                               artifact_refs=(f"{IMPORTS_REL}/research_2026-10-02/xsec.json#{key}",)))
    out.append(TrialRecord("adhoc-2026-10-02|BTC-USD|six_cycle_calendar_checks", "adhoc-2026-10-02",
                           "adhoc.calendar_six", "six_cycle_checks_withdrawn", K.HYPOTHESIS_TEST,
                           {"hypotheses": "6th hour / 6th day / Saturday / 6-month cycle"}, "BTC-USD", "coinbase", "spot",
                           c_base, None, v05_db, {"full_sample": "hourly and daily"}, "none", {}, RS.UNAVAILABLE,
                           status=TrialStatus.FAILED,
                           notes="ad-hoc check reported in conversation on 2 Oct, withdrawn after an off-by-one label bug; "
                                 "superseded by the registered v0.5 hypotheses; script and results were not kept"))

    oi = "owner_ideas_2026-10-03"
    lv = json.loads((imp / f"{oi}/levels.json").read_text())
    c_l = script(f"{oi}/levels.py")
    for vk, v in sorted(lv["verdicts"].items()):
        fam, metric = [x.strip() for x in vk.split("|")]
        out.append(TrialRecord(f"{oi}|BTC-USD|levels|{fam}|{metric}", oi, "adhoc.price_levels", f"{fam} | {metric}",
                               K.HYPOTHESIS_TEST, {"family": fam, "metric": metric, "placebos": 400, "band": 0.005},
                               "BTC-USD", "coinbase", "spot", c_l, None, v05_db, {"periods": "2017-2021 / 2022-2026 / full"},
                               "none", v, RS.UNAVAILABLE, artifact_refs=(f"{IMPORTS_REL}/{oi}/levels.json#verdicts",)))
    oc = json.loads((imp / f"{oi}/occam.json").read_text())
    c_o = script(f"{oi}/occam.py")
    for rule, by_cost in sorted(oc["rules"].items()):
        for cost in ("85bps", "40bps"):
            tid = f"{oi}|BTC-USD|occam|{rule}|{cost}"
            primary = f"{oi}|BTC-USD|occam|{rule}|85bps"
            kind = (K.CONTROL if rule == "hold" else K.CANDIDATE) if cost == "85bps" else K.SENSITIVITY
            out.append(TrialRecord(tid, oi, "adhoc.occam_rule", rule, kind, {"rule": rule, "cost": cost},
                                   "basket" if rule.startswith("basket") else "BTC-USD", "coinbase", "spot", c_o, None,
                                   v05_db, {"full_sample": "daily 2016-2026 after 200-day warm-up"}, f"adhoc.flat:{cost}",
                                   by_cost[cost], RS.UNAVAILABLE, parent_trial_id=None if cost == "85bps" else primary,
                                   artifact_refs=(f"{IMPORTS_REL}/{oi}/occam.json#rules.{rule}.{cost}",)))
    ck = json.loads((imp / f"{oi}/occam_check.json").read_text())
    c_c = script(f"{oi}/occam_check.py")
    for pair, d in sorted(ck.items()):
        for k, v in sorted(d.items()):
            if pair == "BTC-USD" and k in ("hold", "sma200", "sma200_vt"):
                continue                                              # same trials as occam.py at 85 bps
            kind = K.HYPOTHESIS_TEST if "_vs_" in k else (K.CONTROL if k == "hold" else K.CANDIDATE)
            out.append(TrialRecord(f"{oi}|{pair}|occam_check|{k}", oi, "adhoc.occam_check", k, kind,
                                   {"test": k, "bootstrap": "stationary block, mean 20 days, 2000 resamples", "cost_bps": 85},
                                   pair, "coinbase", "spot", c_c, None, v05_db, {"full_sample": "daily after warm-up"},
                                   "adhoc.flat:85bps", v, RS.UNAVAILABLE,
                                   artifact_refs=(f"{IMPORTS_REL}/{oi}/occam_check.json#{pair}.{k}",)))
    md = json.loads((imp / f"{oi}/media.json").read_text())
    c_m = script(f"{oi}/media.py")
    for feat, by_target in sorted(md["features"].items()):
        for target, v in sorted(by_target.items()):
            out.append(TrialRecord(f"{oi}|BTC-USD|media|{feat}|{target}", oi, "adhoc.media_feature", f"{feat} -> {target}",
                                   K.HYPOTHESIS_TEST, {"feature": feat, "target": target, "lag_days": 1, "perms": 1000},
                                   "BTC-USD", "coinbase", "spot", c_m, None, v05_db, {"periods": "to 2021 / 2022 on / full"},
                                   "none", v, RS.UNAVAILABLE, artifact_refs=(f"{IMPORTS_REL}/{oi}/media.json#features",)))
    mp = json.loads((imp / f"{oi}/media_vol_partial.json").read_text())
    c_p = script(f"{oi}/media_vol_partial.py")
    for feat, v in sorted(mp.items()):
        out.append(TrialRecord(f"{oi}|BTC-USD|media_vol_partial|{feat}", oi, "adhoc.media_vol_partial", feat,
                               K.HYPOTHESIS_TEST, {"feature": feat, "target": "vol7", "controls": "7d and 28d realized vol"},
                               "BTC-USD", "coinbase", "spot", c_p, None, v05_db, {"periods": "to 2021 / 2022 on / full"},
                               "none", v, RS.UNAVAILABLE, artifact_refs=(f"{IMPORTS_REL}/{oi}/media_vol_partial.json",)))
    return out


# =================================================================================================================
def effective_trials(root: Path, records: list[TrialRecord]) -> dict:
    """Dependence diagnostic over stored daily series: participation ratio of the correlation spectrum
    (sum lambda)^2 / sum lambda^2 on the common date range. Reported alongside the conservative count, never instead."""
    series = {}
    for r in records:
        if r.returns_status == RS.STORED and r.returns_frequency == "daily":
            text = gzip.decompress((root / r.returns_ref).read_bytes()).decode().splitlines()[1:]
            series[r.trial_id] = dict((int(a), float(b)) for a, b in (x.split(",") for x in text))
    common = sorted(set.intersection(*(set(s) for s in series.values())))
    ids = sorted(series)
    M = np.array([[series[i][t] for i in ids] for t in common])
    sd = M.std(axis=0)
    keep = sd > 0
    C = np.corrcoef(M[:, keep], rowvar=False)
    lam = np.clip(np.linalg.eigvalsh(C), 0, None)
    pr = float(lam.sum() ** 2 / (lam ** 2).sum())
    return {"daily_series": len(ids), "non_constant": int(keep.sum()), "common_days": len(common),
            "from_ts": common[0], "to_ts": common[-1], "participation_ratio": round(pr, 2),
            "method": "eigenvalues of the correlation matrix of stored daily trial returns on their common dates"}


def build(root: Path) -> dict:
    root = Path(root)
    store, recon = Store(root), Recon()
    records = frozen_trials(root, store, recon) + apex_v05_trials(root)
    # collapse duplicate artifact rows of the same trial; distinct hypotheses are never merged
    by_identity: dict[str, TrialRecord] = {}
    ids = Counter(r.trial_id for r in records)
    dup_ids = [k for k, n in ids.items() if n > 1]
    if dup_ids:
        raise RuntimeError(f"trial_id collisions: {dup_ids[:5]}")
    collapsed = 0
    for r in records:
        k = r.identity_sha256()
        if k in by_identity:
            prev = by_identity[k]
            by_identity[k] = TrialRecord(**{**{f: getattr(prev, f) for f in prev.__dataclass_fields__},
                                            "artifact_refs": tuple(sorted(set(prev.artifact_refs) | set(r.artifact_refs)))})
            collapsed += 1
        else:
            by_identity[k] = r
    final = sorted(by_identity.values(), key=lambda r: r.trial_id)
    lines = [canonical_json(r) for r in final]
    (root / LEDGER_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / LEDGER_REL).write_text("\n".join(lines) + "\n")
    (root / RECON_REL).parent.mkdir(parents=True, exist_ok=True)
    rec_rows = sorted(recon.rows, key=lambda x: x["trial_id"])
    (root / RECON_REL).write_text(json.dumps({"checks": len(rec_rows), "passed": sum(x["pass"] for x in rec_rows),
                                              "failed": [x for x in rec_rows if not x["pass"]], "rows": rec_rows}, indent=1))
    eq_groups = defaultdict(list)
    for r in final:
        if r.return_equivalence_id:
            eq_groups[r.return_equivalence_id].append(r.trial_id)
    shared = {k: v for k, v in eq_groups.items() if len(v) > 1}
    real = [r for r in final if r.real_data]
    summary = {
        "ledger": LEDGER_REL, "ledger_sha256": _sha_file(root / LEDGER_REL), "records": len(final),
        "duplicate_artifact_rows_collapsed": collapsed,
        "n_conservative_all_viewed_real_data_trials": sum(1 for r in real if r.viewed_before_later_choice),
        "by_kind": dict(Counter(r.kind.value for r in final)),
        "by_source_version": dict(sorted(Counter(r.source_version for r in final).items())),
        "by_returns_status": dict(Counter(r.returns_status.value for r in final)),
        "by_status": dict(Counter(r.status.value for r in final)),
        "strategy_like_trials (candidate+control+sensitivity)": sum(1 for r in final if r.kind != K.HYPOTHESIS_TEST),
        "return_equivalence": {"series_with_id": sum(len(v) for v in eq_groups.values()), "classes": len(eq_groups),
                               "classes_shared_by_several_trials": len(shared),
                               "examples": [sorted(v) for v in list(shared.values())[:8]]},
        "dependence_diagnostic": effective_trials(root, final),
        "reconstruction": {"checks": len(rec_rows), "passed": sum(x["pass"] for x in rec_rows)},
        "counting_rule": "DSR uses the conservative count of all viewed real-data trials; the participation ratio and "
                         "equivalence classes are reported alongside, never instead (Stage 0 review).",
    }
    (root / SUMMARY_REL).write_text(json.dumps(summary, indent=2))
    return summary
