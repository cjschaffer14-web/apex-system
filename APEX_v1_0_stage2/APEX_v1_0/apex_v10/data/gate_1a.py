"""Stage 1A evidence-grade point-in-time and coverage gate.

Stage 1 timing-quality coverage remains available for exploratory work.  This module fails closed: evidence-grade
rows must have an admissible availability-time quality AND an admissible value-vintage quality.  Latest-vintage,
edited-after-release, unverified, or approximate rows count as missing for evidence-grade coverage.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass
from typing import Iterable, Literal, Optional

from ..interfaces import AvailabilityQuality, CoverageResult, CoverageStatus, QUALITY_RANK
from ..interfaces_1a import EVIDENCE_TIMING, EVIDENCE_VINTAGES
from .coverage import DAY, STANDARD_WINDOWS, Family, _expected, discover_families
from .timeutil import UTC

VINTAGE_VALUES = tuple(x.value for x in EVIDENCE_VINTAGES)
TIMING_VALUES = tuple(x.value for x in EVIDENCE_TIMING)


def _policy(con: sqlite3.Connection, family: str) -> tuple[str, str, int, str]:
    r = con.execute("SELECT value_vintage_quality,revision_status,evidence_eligible,rationale FROM vintage_policy WHERE family=?",
                    (family,)).fetchone()
    return r if r else ("unverified", "unverified", 0, "no Stage 1A vintage policy")


def evidence_times(con: sqlite3.Connection, f: Family) -> list[int]:
    vq, _rs, eligible, _why = _policy(con, f.family)
    if not eligible:
        return []
    if f.kind == "macro":
        q = f"SELECT {f.time_col} FROM {f.table} WHERE {f.where} AND availability_quality IN ({','.join('?'*len(TIMING_VALUES))}) AND value_vintage_quality IN ({','.join('?'*len(VINTAGE_VALUES))}) ORDER BY {f.time_col}"
        args = (*f.params, *TIMING_VALUES, *VINTAGE_VALUES)
        return [int(r[0]) * f.time_scale for r in con.execute(q, args)]
    if f.kind == "funding":
        q = f"SELECT {f.time_col} FROM {f.table} WHERE {f.where} AND availability_quality IN ({','.join('?'*len(TIMING_VALUES))}) AND value_vintage_quality IN ({','.join('?'*len(VINTAGE_VALUES))}) ORDER BY {f.time_col}"
        args = (*f.params, *TIMING_VALUES, *VINTAGE_VALUES)
        return [int(r[0]) * f.time_scale for r in con.execute(q, args)]
    if f.kind == "candles":
        # The family policy is the vintage decision; Stage 1 fixed timing is source_timestamp.
        return [int(r[0]) * f.time_scale for r in con.execute(
            f"SELECT {f.time_col} FROM {f.table} WHERE {f.where} ORDER BY {f.time_col}", f.params)]
    return []  # legacy readings are deliberately non-evidence-grade in Stage 1A


def _worst_timing(con: sqlite3.Connection, f: Family, s: int, e: int) -> AvailabilityQuality:
    if f.kind == "candles":
        return AvailabilityQuality.SOURCE_TIMESTAMP
    if f.kind in ("macro", "funding"):
        rows = con.execute(
            f"SELECT DISTINCT availability_quality FROM {f.table} WHERE {f.where} AND {f.time_col} BETWEEN ? AND ? "
            f"AND value_vintage_quality IN ({','.join('?'*len(VINTAGE_VALUES))})",
            (*f.params, s // f.time_scale, e // f.time_scale, *VINTAGE_VALUES)).fetchall()
        if rows:
            return max((AvailabilityQuality(x[0]) for x in rows), key=lambda q: QUALITY_RANK[q])
    return AvailabilityQuality.APPROXIMATE


def _effective_family(f: Family) -> Family:
    if f.family.startswith("macro:fed_h41_first_release:") and f.cadence != "weekly":
        return Family(f.family, f.kind, f.table, f.where, f.params, f.time_col, f.time_scale, "weekly", f.quality,
                      f.third_party, f.description)
    return f


def evaluate(con: sqlite3.Connection, f: Family, start: str | int, end: str | int) -> CoverageResult:
    f = _effective_family(f)
    s = start if isinstance(start, int) else int(dt.datetime.fromisoformat(start).replace(tzinfo=UTC).timestamp())
    e = end if isinstance(end, int) else int(dt.datetime.fromisoformat(end).replace(tzinfo=UTC).timestamp()) + DAY - 1
    ts = evidence_times(con, f)
    if not ts:
        vq, rs, _ok, why = _policy(con, f.family)
        return CoverageResult(f.family, s, e, None, None, 0.0, AvailabilityQuality.APPROXIMATE, CoverageStatus.FAIL,
                              f"no evidence-grade observations (vintage={vq}, revision_status={rs}; {why})")
    inside = [t for t in ts if s <= t <= e]
    expected, tol = _expected(f, s, e, inside)
    frac = min(1.0, len(inside) / expected) if expected > 0 else 0.0
    reasons = []
    if not inside or frac < 0.5:
        status = CoverageStatus.FAIL
        reasons.append("no evidence-grade overlap with the requested window" if not inside else f"only {frac:.0%} of expected evidence-grade data")
    else:
        if ts[0] > s + tol:
            reasons.append(f"evidence starts {dt.datetime.fromtimestamp(ts[0], UTC).date()} (after requested start)")
        if ts[-1] < e - tol:
            reasons.append(f"evidence ends {dt.datetime.fromtimestamp(ts[-1], UTC).date()} (before requested end)")
        if frac < 0.98:
            reasons.append(f"evidence-grade coverage {frac:.1%} of expected observations")
        status = CoverageStatus.PARTIAL if reasons else CoverageStatus.PASS
    return CoverageResult(f.family, s, e, ts[0], ts[-1], round(frac, 6), _worst_timing(con, f, s, e), status,
                          "; ".join(reasons))


class EvidenceCoverageError(RuntimeError):
    pass


def require(con: sqlite3.Connection, families: Iterable[str], start: str, end: str,
            on_partial: Literal["fail", "shorten", "ablate"] = "fail",
            on_fail: Literal["fail", "shorten", "ablate"] = "fail") -> dict:
    reg = {f.family: f for f in discover_families(con)}
    req_s = int(dt.datetime.fromisoformat(start).replace(tzinfo=UTC).timestamp())
    req_e = int(dt.datetime.fromisoformat(end).replace(tzinfo=UTC).timestamp()) + DAY - 1
    decision = {"grade": "evidence", "requested": [start, end], "window": [start, end], "families": {}, "ablated": [],
                "policy": {"on_partial": on_partial, "on_fail": on_fail}}
    shorten = []
    for name in families:
        if name not in reg:
            raise EvidenceCoverageError(f"unknown family {name}")
        r = evaluate(con, reg[name], start, end)
        vq, rs, _ok, why = _policy(con, name)
        decision["families"][name] = {"status": r.status.value, "coverage": r.coverage_fraction, "reason": r.reason,
                                        "value_vintage_quality": vq, "revision_status": rs, "policy_rationale": why}
        if r.status == CoverageStatus.PASS:
            continue
        policy = on_fail if r.status == CoverageStatus.FAIL else on_partial
        if policy == "ablate":
            decision["ablated"].append(name)
        elif policy == "shorten" and r.available_start_ts is not None and r.available_end_ts is not None:
            shorten.append(r)
        else:
            raise EvidenceCoverageError(f"{name}: {r.status.value} ({r.reason})")
    if shorten:
        s2 = max([req_s] + [r.available_start_ts for r in shorten])
        e2 = min([req_e] + [r.available_end_ts for r in shorten])
        if e2 <= s2:
            raise EvidenceCoverageError("no common evidence-grade window remains")
        ns, ne = dt.datetime.fromtimestamp(s2, UTC).date().isoformat(), dt.datetime.fromtimestamp(e2, UTC).date().isoformat()
        for name in decision["families"]:
            if name in decision["ablated"]:
                continue
            r2 = evaluate(con, reg[name], ns, ne)
            decision["families"][name]["shortened_status"] = r2.status.value
            if r2.status != CoverageStatus.PASS:
                raise EvidenceCoverageError(f"{name}: still {r2.status.value} after shortening")
        decision["window"] = [ns, ne]
        decision["shortened"] = True
    return decision


@dataclass(frozen=True)
class EvidenceAsOfValue:
    value: float
    observation_ts: int
    published_ts: int
    availability_time_quality: str
    value_vintage_quality: str
    provenance_id: str


def macro_asof(con: sqlite3.Connection, source: str, series_id: str, decision_ts: int) -> Optional[EvidenceAsOfValue]:
    row = con.execute(
        f"SELECT value,observation_ts,published_ts,availability_quality,value_vintage_quality,provenance_id "
        f"FROM macro_observations WHERE source=? AND series_id=? AND published_ts<=? "
        f"AND availability_quality IN ({','.join('?'*len(TIMING_VALUES))}) "
        f"AND value_vintage_quality IN ({','.join('?'*len(VINTAGE_VALUES))}) "
        f"ORDER BY observation_ts DESC,published_ts DESC LIMIT 1",
        (source, series_id, decision_ts, *TIMING_VALUES, *VINTAGE_VALUES)).fetchone()
    return EvidenceAsOfValue(*row) if row else None


def gate_report(con: sqlite3.Connection, windows: dict[str, tuple[str, str]] = STANDARD_WINDOWS) -> dict:
    out = {"grade": "evidence", "windows": windows, "families": {}}
    for f in discover_families(con):
        vq, rs, ok, why = _policy(con, f.family)
        rows = {}
        for name, (s, e) in windows.items():
            r = evaluate(con, f, s, e)
            rows[name] = {"status": r.status.value, "coverage": r.coverage_fraction, "reason": r.reason}
        ts = evidence_times(con, f)
        out["families"][f.family] = {"kind": f.kind, "value_vintage_quality": vq, "revision_status": rs,
                                      "family_policy_evidence_eligible": bool(ok), "policy_rationale": why,
                                      "evidence_rows": len(ts), "windows": rows}
    return out
