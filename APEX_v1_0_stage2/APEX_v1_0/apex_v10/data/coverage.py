"""CoverageGate: a formal definition of "full database" for every data family and requested window.

  PASS     the family covers the window (start/end within tolerance, >= 98% of expected observations present) and
           at most 1% of its rows have only approximate availability timing (the rest exact, source-stamped or
           conservative)
  PARTIAL  it overlaps the window but starts late, ends early, has holes, or its availability is only approximate
  FAIL     no overlap, or less than half the expected observations

A trial that depends on a family must clear the gate for its declared window. A FAIL or PARTIAL family stops the
trial unless the trial explicitly shortens its declared window (the shorter window must then PASS) or runs a named
ablation without that family (`require`). Nothing is silently shortened or filled.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import statistics
from dataclasses import dataclass
from typing import Iterable, Literal, Optional

from ..interfaces import AvailabilityQuality, CoverageResult, CoverageStatus, QUALITY_RANK
from .timeutil import UTC, business_days

DAY = 86400
GOOD_QUALITY = {AvailabilityQuality.EXACT_RELEASE, AvailabilityQuality.SOURCE_TIMESTAMP,
                AvailabilityQuality.CONSERVATIVE_LAG}

STANDARD_WINDOWS = {   # requested evaluation periods used by the v0.6-v0.9 research and planned v1.0 work
    "v09_btc_full": ("2015-07-20", "2026-10-02"),
    "v09_eth_full": ("2016-05-18", "2026-10-02"),
    "pre_2022": ("2015-07-20", "2021-12-31"),
    "post_2022": ("2022-01-01", "2026-10-02"),
    "hourly_2017_on": ("2017-01-01", "2026-10-02"),
    "funding_era_2019_on": ("2019-01-01", "2026-10-02"),
}


@dataclass(frozen=True)
class Family:
    family: str
    kind: str                  # candles | readings | funding | macro
    table: str
    where: str                 # SQL predicate selecting the family's rows
    params: tuple
    time_col: str              # column holding the time each value describes (days for legacy readings)
    time_scale: int            # multiply time_col by this to get epoch seconds
    cadence: str               # "step:<seconds>" | "business_daily" | "weekly" | "event"
    quality: Optional[str]     # fixed quality, or None to read availability_quality per row
    third_party: bool = False
    description: str = ""


def discover_families(con: sqlite3.Connection) -> list[Family]:
    fams: list[Family] = []
    for src, pair, interval in con.execute("SELECT DISTINCT source, pair, interval FROM candles ORDER BY 1,2,3"):
        fams.append(Family(f"candles:{src}:{pair}:{interval}", "candles", "candles",
                           "source=? AND pair=? AND interval=?", (src, pair, interval), "ts", 1, f"step:{interval * 60}",
                           "source_timestamp", False, f"{src} {pair} {interval}-minute OHLCV bars"))
    for src, metric in con.execute("SELECT DISTINCT source, metric FROM readings ORDER BY 1,2"):
        # legacy readings carry a day number only; their availability rules are approximate by construction
        fams.append(Family(f"readings:{src}:{metric}", "readings", "readings", "source=? AND metric=?", (src, metric),
                           "ts", DAY, f"step:{DAY}", "approximate", False, f"legacy {src} reading {metric} (day-stamped)"))
    if _table_exists(con, "funding_events"):
        for venue, sym in con.execute("SELECT DISTINCT venue, symbol FROM funding_events ORDER BY 1,2"):
            fams.append(Family(f"funding:{venue}:{sym}", "funding", "funding_events", "venue=? AND symbol=?",
                               (venue, sym), "funding_ts", 1, "event", None, False, f"{venue} {sym} funding events"))
    if _table_exists(con, "macro_observations"):
        for src, sid in con.execute("SELECT DISTINCT source, series_id FROM macro_observations ORDER BY 1,2"):
            cadence = "weekly" if src == "fed_h41" else "business_daily"
            fams.append(Family(f"macro:{src}:{sid}", "macro", "macro_observations", "source=? AND series_id=?",
                               (src, sid), "observation_ts", 1, cadence, None, False, f"{src} {sid}"))
    return fams


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _times(con: sqlite3.Connection, f: Family) -> list[int]:
    return [r[0] * f.time_scale for r in
            con.execute(f"SELECT {f.time_col} FROM {f.table} WHERE {f.where} ORDER BY {f.time_col}", f.params)]


APPROXIMATE_TOLERANCE = 0.01      # up to 1% of a window's rows may carry approximate timing before it turns PARTIAL


def _quality(con: sqlite3.Connection, f: Family, s: int, e: int) -> tuple[AvailabilityQuality, float]:
    """(worst quality in the window, share of rows whose timing is only approximate)."""
    if f.quality:
        q = AvailabilityQuality(f.quality)
        return q, 1.0 if q == AvailabilityQuality.APPROXIMATE else 0.0
    rows = con.execute(
        f"SELECT availability_quality, COUNT(*) FROM {f.table} WHERE {f.where} AND {f.time_col} BETWEEN ? AND ? "
        f"GROUP BY 1", (*f.params, s // f.time_scale, e // f.time_scale)).fetchall()
    if not rows:
        return AvailabilityQuality.APPROXIMATE, 1.0
    total = sum(n for _, n in rows)
    approx = sum(n for q, n in rows if q == "approximate")
    worst = max((AvailabilityQuality(q) for q, _ in rows), key=lambda q: QUALITY_RANK[q])
    return worst, approx / total


def _expected(f: Family, s: int, e: int, inside: list[int]) -> tuple[float, int]:
    """(expected observation count in [s, e], tolerance in seconds for start/end)."""
    if f.cadence.startswith("step:"):
        step = int(f.cadence.split(":")[1])
        return (e - s) // step + 1, 2 * step
    ds, de = dt.datetime.fromtimestamp(s, UTC).date(), dt.datetime.fromtimestamp(e, UTC).date()
    if f.cadence == "business_daily":
        return business_days(ds, de), 4 * DAY
    if f.cadence == "weekly":
        return ((e - s) // DAY + 1) / 7.0, 8 * DAY
    gaps = [b - a for a, b in zip(inside, inside[1:])]
    med = statistics.median(gaps) if gaps else DAY
    return (e - s) / med + 1, int(2 * med)


def evaluate(con: sqlite3.Connection, f: Family, start: str | int, end: str | int) -> CoverageResult:
    s = start if isinstance(start, int) else int(dt.datetime.fromisoformat(start).replace(tzinfo=UTC).timestamp())
    e = end if isinstance(end, int) else int(dt.datetime.fromisoformat(end).replace(tzinfo=UTC).timestamp()) + DAY - 1
    ts = _times(con, f)
    if not ts:
        return CoverageResult(f.family, s, e, None, None, 0.0, AvailabilityQuality.APPROXIMATE, CoverageStatus.FAIL,
                              "no observations")
    inside = [t for t in ts if s <= t <= e]
    expected, tol = _expected(f, s, e, inside)
    frac = min(1.0, len(inside) / expected) if expected > 0 else 0.0
    q, approx_share = _quality(con, f, s, e)
    reasons = []
    if not inside or frac < 0.5:
        status = CoverageStatus.FAIL
        reasons.append("no overlap with the requested window" if not inside else f"only {frac:.0%} of expected data")
    else:
        if ts[0] > s + tol:
            reasons.append(f"starts {dt.datetime.fromtimestamp(ts[0], UTC).date()} (after requested start)")
        if ts[-1] < e - tol:
            reasons.append(f"ends {dt.datetime.fromtimestamp(ts[-1], UTC).date()} (before requested end)")
        if frac < 0.98:
            reasons.append(f"coverage {frac:.1%} of expected observations")
        if approx_share > APPROXIMATE_TOLERANCE:
            reasons.append(f"approximate availability timing ({approx_share:.0%} of rows)")
        status = CoverageStatus.PARTIAL if reasons else CoverageStatus.PASS
    return CoverageResult(f.family, s, e, ts[0], ts[-1], round(frac, 6), q, status, "; ".join(reasons))


class CoverageError(RuntimeError):
    pass


def require(con: sqlite3.Connection, families: Iterable[str], start: str, end: str,
            on_partial: Literal["fail", "shorten", "ablate"] = "fail",
            on_fail: Literal["fail", "shorten", "ablate"] = "fail",
            ablate_on_fail: bool = False) -> dict:
    """Gate a planned trial. Returns the decision record to be stored with the trial; raises CoverageError otherwise.

    For each family that does not PASS over the requested window the trial must say what happens: "fail" (default:
    the trial stops), "shorten" (the declared window becomes the common span, which must then PASS for every family
    still used), or "ablate" (the family is dropped and the ablation is named in the decision record).
    `ablate_on_fail=True` is shorthand for on_fail="ablate"."""
    if ablate_on_fail:
        on_fail = "ablate"
    req_s = int(dt.datetime.fromisoformat(start).replace(tzinfo=UTC).timestamp())
    req_e = int(dt.datetime.fromisoformat(end).replace(tzinfo=UTC).timestamp()) + DAY - 1
    reg = {f.family: f for f in discover_families(con)}
    decision: dict = {"requested": [start, end], "families": {}, "ablated": [], "window": [start, end],
                      "policy": {"on_partial": on_partial, "on_fail": on_fail}}
    keep: list[CoverageResult] = []
    for name in families:
        if name not in reg:
            raise CoverageError(f"unknown data family {name!r}")
        r = evaluate(con, reg[name], start, end)
        decision["families"][name] = {"status": r.status.value, "reason": r.reason, "quality": r.worst_quality.value,
                                      "coverage": r.coverage_fraction}
        if r.status == CoverageStatus.PASS:
            continue
        policy = on_fail if r.status == CoverageStatus.FAIL else on_partial
        if policy == "ablate":
            decision["ablated"].append(name)
        elif policy == "shorten":
            if r.available_start_ts is None or r.available_end_ts < req_s or r.available_start_ts > req_e:
                raise CoverageError(f"{name}: {r.status.value} with no data inside {start}..{end}; it cannot be "
                                    "shortened, only failed or ablated")
            keep.append(r)
        else:
            raise CoverageError(f"{name}: {r.status.value} ({r.reason}); fail the trial, shorten the window or "
                                "declare an explicit ablation")
    if keep:
        # the shortened window is the intersection of the request with every kept family's span; it must then PASS
        # for every family still in use, or the trial stops (shortening cannot fix holes or approximate timing)
        new_s = max([req_s] + [r.available_start_ts for r in keep])
        new_e = min([req_e] + [r.available_end_ts for r in keep])
        ns = dt.datetime.fromtimestamp(new_s, UTC).date().isoformat()
        ne = dt.datetime.fromtimestamp(new_e, UTC).date().isoformat()
        if new_e <= new_s:
            raise CoverageError(f"no common window remains after shortening ({ns} .. {ne})")
        for name in decision["families"]:
            if name in decision["ablated"]:
                continue
            r2 = evaluate(con, reg[name], ns, ne)
            decision["families"][name]["shortened_status"] = r2.status.value
            if r2.status != CoverageStatus.PASS:
                raise CoverageError(f"{name}: still {r2.status.value} in the shortened window {ns}..{ne} ({r2.reason}); "
                                    "declare an ablation instead")
        decision["window"] = [ns, ne]
        decision["shortened"] = True
    return decision


def gate_report(con: sqlite3.Connection, windows: dict[str, tuple[str, str]] = STANDARD_WINDOWS) -> dict:
    out = {"definition": __doc__.strip().splitlines()[0], "windows": windows, "families": {}}
    for f in discover_families(con):
        rows = {}
        for wname, (s, e) in windows.items():
            r = evaluate(con, f, s, e)
            rows[wname] = {"status": r.status.value, "coverage": r.coverage_fraction,
                           "quality": r.worst_quality.value, "reason": r.reason}
        ts = _times(con, f)
        out["families"][f.family] = {"kind": f.kind, "description": f.description,
                                     "first": dt.datetime.fromtimestamp(ts[0], UTC).isoformat() if ts else None,
                                     "last": dt.datetime.fromtimestamp(ts[-1], UTC).isoformat() if ts else None,
                                     "rows": len(ts), "windows": rows}
    return out
