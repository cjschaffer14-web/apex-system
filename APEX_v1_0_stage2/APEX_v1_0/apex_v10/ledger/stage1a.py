"""Stage 1A trial-ledger evidence closure.

Extends, never edits, the accepted Stage 1 ledger.  It attaches frozen forensic-reproduction outcomes to the 148
metric-only historical trials, stores only exactly reconciled paths, adds selection-family/objective/comparable-set
metadata, prepares DSR inputs, and emits aligned CSCV-ready matrices.  It does not compute a DSR/PBO verdict.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from scipy import stats

from ..data.archive import gzip_deterministic
from ..interfaces import ReturnsStatus, TrialKind, TrialRecord, canonical_json
from ..interfaces_1a import ComparableSet, SelectionFamily, TrialRecord1A
from .io import load_ledger, read_returns, equivalence_id

STAGE1_LEDGER_REL = "ledger/trial_ledger.jsonl"
LEDGER_1A_REL = "ledger/trial_ledger_1a.jsonl"
SUMMARY_1A_REL = "ledger/LEDGER_SUMMARY_1A.json"
RETURNS_1A_REL = "ledger/returns_1a"
DSR_INPUTS_REL = "reports/dsr_inputs_1a.csv"
FAMILIES_REL = "reports/selection_families_1a.json"
COMPARABLE_REL = "reports/comparable_sets_1a.json"
MATRICES_REL = "reports/cscv_matrices_1a"
FORENSIC_FILES = {
    "adhoc-2026-10-02": "stage1a/forensic_adhoc_outcomes.json",
    "owner_ideas_2026-10-03": "stage1a/forensic_owner_outcomes.json",
    "v0.5": "stage1a/forensic_v05_outcomes.json",
    "v0.5.1": "stage1a/forensic_v051_outcomes.json",
}
GLOBAL_N = 1483


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _slug(s: str) -> str:
    x = re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_")
    return x[:140] + "_" + hashlib.sha256(s.encode()).hexdigest()[:12]


def _write_series(root: Path, trial_id: str, series: dict) -> tuple[str, str, str]:
    ts, ret = series["ts"], series["ret"]
    if len(ts) != len(ret) or not ts or not np.all(np.isfinite(np.asarray(ret, float))):
        raise ValueError(f"invalid forensic series {trial_id}")
    text = "ts,ret\n" + "".join(f"{int(t)},{float(r)!r}\n" for t, r in zip(ts, ret))
    raw = gzip_deterministic(text.encode())
    rel = f"{RETURNS_1A_REL}/{_slug(trial_id)}.csv.gz"
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(raw)
    return rel, _sha(raw), equivalence_id(ts, ret)


def _load_outcomes(root: Path) -> dict[str, dict]:
    out = {}
    for source, rel in FORENSIC_FILES.items():
        p = root / rel
        if not p.exists():
            raise FileNotFoundError(f"Stage 1A forensic output missing: {rel}")
        rows = json.loads(p.read_text())
        for r in rows:
            if r["trial_id"] in out:
                raise ValueError(f"duplicate forensic outcome {r['trial_id']}")
            out[r["trial_id"]] = r
    return out


def _objective(r: TrialRecord) -> str:
    # Normalize strategy selection objectives so controls/candidates from the same research batch stay in the same
    # family even when one frozen artifact stored ``sharpe`` directly and another nested it under ``full``.
    if r.family == "v09.geometry_target_cell": return "target_before_invalidation_statistic"
    if r.family == "v09.conditional_expert_state": return "conditional_forward_return_statistic"
    if r.family == "v09.state_forward_distribution": return "state_forward_distribution_statistic"
    if r.family == "adhoc.fibonacci_levels": return "fibonacci_placebo_test"
    if r.kind == TrialKind.HYPOTHESIS_TEST: return "hypothesis_test_statistic"
    m = r.metrics
    if "oos_sharpe" in m or "sharpe" in m or (isinstance(m.get("full"), dict) and "sharpe" in m["full"]) \
            or (isinstance(m.get("rule"), dict) and "sharpe" in m["rule"]):
        return "annualized_sharpe"
    return "reported_performance_metric"


def _selection_family(r: TrialRecord, objective: str) -> str:
    if r.family == "adhoc.fibonacci_levels":
        gran = str(r.parameters.get("granularity", "unknown"))
        return "|".join((r.source_version, r.family, r.asset, gran, objective))
    return "|".join((r.source_version, r.family, r.asset, r.cost_model_id, objective))

def _is_investable(r: TrialRecord) -> bool:
    return r.kind != TrialKind.HYPOTHESIS_TEST and r.returns_status == ReturnsStatus.STORED and \
           r.returns_frequency in ("daily", "weekly", "hourly")


def _annual_factor(freq: str) -> float:
    return {"daily": 365.0, "weekly": 52.0, "hourly": 365.0 * 24.0}[freq]


def _sharpe(ret: Iterable[float], freq: str) -> float:
    a = np.asarray(list(ret), float)
    sd = float(a.std())
    return 0.0 if sd <= 0 else float(a.mean() / sd * math.sqrt(_annual_factor(freq)))


def _family_alt_count(members: list[TrialRecord1A]) -> int:
    # Explicit compressed experiments: one random-level aggregate represents 40 evaluated ratio sets plus the named
    # and thirds alternatives.  Keep this information in family N even though it is not a CSCV strategy family.
    if members and members[0].family == "adhoc.fibonacci_levels":
        return max(len(members), 42)
    # Owner level tests use 400 null grids, but those are permutation/placebo draws inside a hypothesis test rather
    # than selectable trading policies; they are not inflated into a Sharpe-selection N.
    return len(members)


def _make_1a_record(root: Path, r: TrialRecord, outcome: dict | None) -> TrialRecord1A:
    vals = {f: getattr(r, f) for f in r.__dataclass_fields__}
    reproduction: dict[str, Any]
    if r.returns_status in (ReturnsStatus.STORED, ReturnsStatus.RECONSTRUCTABLE):
        reproduction = {"status": "stage1_reconciled", "stage1_returns_status": r.returns_status.value}
    elif outcome is None:
        reproduction = {"status": "not_reproducible", "reason": "no Stage 1A forensic outcome"}
    else:
        st = outcome["status"]
        reproduction = {"status": st, "method": outcome.get("method"), "n_fields_compared": outcome.get("n_fields_compared", 0),
                        "mismatches": outcome.get("mismatches", []), "note": outcome.get("note", ""),
                        "series_check": outcome.get("series_check"), "code": outcome.get("code", {})}
        if st == "reproduced_series":
            ref, sha, eq = _write_series(root, r.trial_id, outcome["series"])
            vals.update(returns_status=ReturnsStatus.STORED, returns_frequency=outcome["series"]["frequency"],
                        returns_ref=ref, returns_sha256=sha, return_equivalence_id=eq)
        elif st in ("reproduced_statistic_only", "mismatch", "not_reproducible"):
            # Keep the historical trial in N, but never invent a path.
            vals.update(returns_status=ReturnsStatus.UNAVAILABLE, returns_frequency="none", returns_ref=None,
                        returns_sha256=None, return_equivalence_id=None)
        else:
            raise ValueError(f"unknown forensic status {st} for {r.trial_id}")
    # Build once without comparable_set_id; a second pass assigns only sets with >=2 distinct return paths.
    base = TrialRecord(**vals)
    obj = _objective(base)
    fam = _selection_family(base, obj)
    return TrialRecord1A(**{f: getattr(base, f) for f in base.__dataclass_fields__}, selection_family_id=fam,
                         objective_metric=obj, comparable_set_id=None, investable=_is_investable(base), reproduction=reproduction)


def _read_any_returns(root: Path, r: TrialRecord1A) -> tuple[list[int], list[float]]:
    # Stage 1 helper works for any relative return file and validates the hash.
    return read_returns(root, r)


def _build_comparable_sets(root: Path, records: list[TrialRecord1A]) -> tuple[list[TrialRecord1A], list[dict]]:
    groups: dict[tuple, list[TrialRecord1A]] = defaultdict(list)
    for r in records:
        if (not r.investable or r.returns_status != ReturnsStatus.STORED
                or r.objective_metric != "annualized_sharpe"):
            continue
        # The family identifies the actual selection batch/objective. Asset, frequency and cost are repeated here
        # deliberately so no future family-id refactor can accidentally mix incomparable columns.
        groups[(r.selection_family_id, r.asset, r.returns_frequency, r.cost_model_id)].append(r)
    assignments = {}
    reports = []
    outdir = root / MATRICES_REL
    outdir.mkdir(parents=True, exist_ok=True)
    for key, members in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if len(members) < 2:
            continue
        series = {r.trial_id: _read_any_returns(root, r) for r in members}
        common = sorted(set.intersection(*(set(ts) for ts, _ in series.values())))
        if len(common) < 16:
            continue
        maps = {tid: dict(zip(*series[tid])) for tid in series}
        # Collapse identical realized columns by return_equivalence_id, but retain alias trial ids in metadata.
        byeq: dict[str, list[TrialRecord1A]] = defaultdict(list)
        for r in members:
            byeq[r.return_equivalence_id].append(r)
        if len(byeq) < 2:
            continue
        reps = [sorted(v, key=lambda r: r.trial_id)[0] for _, v in sorted(byeq.items())]
        sid = "cscv:" + hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()[:16]
        text = "ts," + ",".join(r.trial_id for r in reps) + "\n"
        for t in common:
            text += str(t) + "," + ",".join(repr(float(maps[r.trial_id][t])) for r in reps) + "\n"
        gz = gzip_deterministic(text.encode())
        rel = f"{MATRICES_REL}/{sid.replace(':','_')}.csv.gz"
        (root / rel).write_bytes(gz)
        aliases = {r.trial_id: sorted(x.trial_id for x in byeq[r.return_equivalence_id]) for r in reps}
        reports.append({"set_id": sid, "selection_family_id": key[0], "asset": key[1], "frequency": key[2],
                        "cost_model_id": key[3], "members": sorted(r.trial_id for r in members),
                        "representative_columns": [r.trial_id for r in reps], "equivalence_aliases": aliases,
                        "rows": len(common), "first_ts": common[0], "last_ts": common[-1],
                        "distinct_columns": len(reps), "matrix_ref": rel, "matrix_sha256": _sha(gz)})
        for r in members:
            assignments[r.trial_id] = sid
    updated = []
    for r in records:
        sid = assignments.get(r.trial_id)
        vals = {f: getattr(r, f) for f in r.__dataclass_fields__}
        vals["comparable_set_id"] = sid
        updated.append(TrialRecord1A(**vals))
    return updated, reports


def build(root: Path) -> dict:
    root = Path(root)
    stage1 = load_ledger(root / STAGE1_LEDGER_REL)
    if len(stage1) != GLOBAL_N:
        raise RuntimeError(f"accepted Stage 1 ledger has {len(stage1)} records, expected {GLOBAL_N}")
    outcomes = _load_outcomes(root)
    unavailable = {r.trial_id for r in stage1 if r.returns_status == ReturnsStatus.UNAVAILABLE}
    if set(outcomes) != unavailable:
        missing, extra = sorted(unavailable - set(outcomes)), sorted(set(outcomes) - unavailable)
        raise RuntimeError(f"forensic outcomes must cover exactly the 148 unavailable Stage 1 trials; missing={missing[:5]} extra={extra[:5]}")
    records = [_make_1a_record(root, r, outcomes.get(r.trial_id)) for r in stage1]
    records, comp = _build_comparable_sets(root, records)

    # Selection family registry.
    byfam: dict[str, list[TrialRecord1A]] = defaultdict(list)
    for r in records:
        byfam[r.selection_family_id].append(r)
    families = []
    family_n = {}
    for fid, members in sorted(byfam.items()):
        nalt = _family_alt_count(members)
        sharpe_obj = members[0].objective_metric == "annualized_sharpe" and all(r.investable for r in members)
        fam = SelectionFamily(fid, members[0].objective_metric, f"{members[0].source_version} / {members[0].family} / {members[0].asset} / {members[0].cost_model_id}",
                              len(members), nalt, sharpe_obj,
                              "Family N counts compressed alternatives where explicitly known; global N remains 1,483.")
        families.append(asdict(fam)); family_n[fid] = nalt
    (root / FAMILIES_REL).write_text(json.dumps(families, indent=2, sort_keys=True))
    (root / COMPARABLE_REL).write_text(json.dumps(comp, indent=2, sort_keys=True))

    # DSR inputs only: no DSR calculation or verdict in Stage 1A.
    dsr_rows = []
    for r in records:
        if (not r.investable or r.returns_status != ReturnsStatus.STORED
                or r.objective_metric != "annualized_sharpe"):
            continue
        ts, ret = _read_any_returns(root, r)
        a = np.asarray(ret, float)
        if len(a) < 3 or float(a.std()) <= 0:
            continue
        dsr_rows.append({"trial_id": r.trial_id, "selection_family_id": r.selection_family_id,
                         "objective_metric": r.objective_metric, "global_n": GLOBAL_N, "family_n": family_n[r.selection_family_id],
                         "T": len(a), "frequency": r.returns_frequency, "observed_sharpe_recomputed": _sharpe(a, r.returns_frequency),
                         "skew": float(stats.skew(a, bias=False)), "kurtosis_pearson": float(stats.kurtosis(a, fisher=False, bias=False)),
                         "return_equivalence_id": r.return_equivalence_id, "comparable_set_id": r.comparable_set_id or ""})
    p = root / DSR_INPUTS_REL; p.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dsr_rows[0]) if dsr_rows else []
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(dsr_rows)

    # Canonical extended ledger.
    lines = [canonical_json(r) for r in records]
    (root / LEDGER_1A_REL).write_text("\n".join(lines) + "\n")
    forensic_counts = Counter((r.reproduction or {}).get("status") for r in records)
    status_counts = Counter(r.returns_status.value for r in records)
    eq = {r.return_equivalence_id for r in records if r.return_equivalence_id}
    summary = {"stage": "1A", "parent_stage1_ledger_sha256": hashlib.sha256((root/STAGE1_LEDGER_REL).read_bytes()).hexdigest(),
               "ledger": LEDGER_1A_REL, "ledger_sha256": hashlib.sha256((root/LEDGER_1A_REL).read_bytes()).hexdigest(),
               "records": len(records), "global_conservative_n": GLOBAL_N, "selection_families": len(families),
               "comparable_sets": len(comp), "dsr_input_rows": len(dsr_rows), "returns_status": dict(status_counts),
               "return_equivalence_classes": len(eq), "reproduction_status": {str(k):v for k,v in forensic_counts.items()},
               "forensic_paths_recovered": sum(1 for r in records if (r.reproduction or {}).get("status") == "reproduced_series"),
               "forensic_statistic_only": sum(1 for r in records if (r.reproduction or {}).get("status") == "reproduced_statistic_only"),
               "forensic_unavailable": sum(1 for r in records if (r.reproduction or {}).get("status") in ("mismatch","not_reproducible")),
               "rule": "No DSR or PBO verdict is computed in Stage 1A. Global N=1,483 is retained; family N and aligned CSCV matrices are prepared separately."}
    (root / SUMMARY_1A_REL).write_text(json.dumps(summary, indent=2, sort_keys=True))
    return summary
