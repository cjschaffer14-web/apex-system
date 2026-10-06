"""H.4.1 first-release values, recovered from the Federal Reserve Board's own archived release documents (Stage 1A).

Why: the Stage 1 H.4.1 series comes from the Data Download Program, which serves only the LATEST vintage of each
Wednesday level. Its release TIMING is exact, but the stored number is not proven to be the number published on
that release date. Each weekly H.4.1 release is archived by the Board at
    https://www.federalreserve.gov/releases/h41/YYYYMMDD/
and its "Consolidated Statement of Condition of All Federal Reserve Banks" table carries, for the Wednesday just
ended, the level of Total assets (net of eliminations from consolidation) and the change since the prior Wednesday.

For every Wednesday from 2014-01-01 this adapter reads the first release published after it (the same release
mapping as Stage 1: the first release date strictly after the Wednesday, within 7 days) and stores
    value  = Total assets, Wednesday level, as first published         -> value_vintage_quality first_release
    timing = 16:30 ET on that release date                             -> availability_time_quality exact_release
It also records the change since the prior Wednesday, which implies the prior Wednesday's value as known one week
later (a second vintage), so revisions between first print, second print and the DDP's latest value are visible.

Every page is kept in the Stage 1A raw archive (data_v10/raw_1a). A page that cannot be fetched, or whose table
does not name the expected Wednesday, is reported and never filled in.
"""
from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass
from typing import Optional

from ..archive import RawArchive
from ..timeutil import et_ts
from .common import SourceResult

SOURCE = "fed_h41_first_release"
SERIES = "RESPPMA_N.WW"
START_WEDNESDAY = dt.date(2014, 1, 1)
URL = "https://www.federalreserve.gov/releases/h41/{:%Y%m%d}/"
TABLE = "Consolidated Statement of Condition of All Federal Reserve Banks"
_DATE = re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? (\d{1,2}), (\d{4})")
_ROW = re.compile(r"Total assets \(([\d,]+)\) ([\d,]+) ([+-]) ?([\d,]+) ([+-]) ?([\d,]+)")
_MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
                                       "Dec"), start=1)}


@dataclass(frozen=True)
class Parsed:
    wednesday: dt.date
    prior_wednesday: dt.date
    total_assets_musd: int
    change_since_prior_musd: int
    eliminations_musd: int


def page_text(body: bytes) -> str:
    s = body.decode("utf-8", errors="replace")
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"[\s ]+", " ", s)


def parse_release(body: bytes) -> Parsed:
    """Total assets (Wednesday level) and its change since the prior Wednesday, from one archived release.

    A release page can mention the consolidated statement in explanatory prose before the actual table.  Earlier
    Stage 1A code used the first textual occurrence, which mis-read 15 releases whose preamble contained another
    date.  Select the occurrence whose ``Total assets`` row is nearest: that is the actual table heading.  Then
    identify the current/prior Wednesday pair from the table header by the seven-day relation, rather than by
    positional order.  This leaves the parser strict (the caller still checks the exact expected Wednesdays) while
    making it robust to release-date and footnote dates in the preamble.
    """
    t = page_text(body)
    candidates = []
    pos = 0
    while True:
        i = t.find(TABLE, pos)
        if i < 0:
            break
        m = _ROW.search(t, i)
        if m is not None:
            candidates.append((m.start() - i, i, m))
        pos = i + 1
    if not candidates:
        raise ValueError("consolidated statement table or Total assets row not found")

    _, i, m = min(candidates, key=lambda x: x[0])
    header = t[i:m.start()]
    dates = [dt.date(int(y), _MONTHS[mon], int(day)) for mon, day, y in _DATE.findall(header)]
    weekly_pairs = [(a, b) for a in dates for b in dates if (a - b).days == 7]
    if not weekly_pairs:
        raise ValueError("table header does not name a current/prior Wednesday pair")
    wednesday, prior = max(weekly_pairs, key=lambda p: p[0])

    elim, level, s1, c1 = m.group(1), m.group(2), m.group(3), m.group(4)
    change = int(c1.replace(",", "")) * (1 if s1 == "+" else -1)
    return Parsed(wednesday, prior, int(level.replace(",", "")), change, int(elim.replace(",", "")))


def first_release_day(release_days: list[dt.date], wednesday: dt.date) -> Optional[dt.date]:
    later = [d for d in release_days if d > wednesday]
    if not later or (later[0] - wednesday).days > 7:
        return None
    return later[0]


def fed_h41_first_release(archive: RawArchive, asof_ts: int, root_rel: str,
                          release_days: list[dt.date]) -> tuple[SourceResult, list[dict]]:
    """Returns the source result (macro rows in Stage 1 MACRO_COLUMNS order) and one audit record per Wednesday."""
    res = SourceResult("macro:fed_h41_first_release")
    audit: list[dict] = []
    release_days = sorted(set(release_days))
    wed = START_WEDNESDAY
    while wed < release_days[-1]:
        rel = first_release_day(release_days, wed)
        if rel is None:
            audit.append({"wednesday": wed.isoformat(), "status": "no release within 7 days"})
            wed += dt.timedelta(days=7)
            continue
        if et_ts(rel, 16, 30) > asof_ts:
            break                                               # released after the snapshot's as-of time
        url = URL.format(rel)
        rec = {"wednesday": wed.isoformat(), "release": rel.isoformat(), "url": url}
        try:
            p = archive.get("fed_h41_release", url, spacing_s=1.0)
        except (KeyError, RuntimeError) as e:
            rec.update(status="page unavailable", error=str(e)[:200])
            audit.append(rec)
            wed += dt.timedelta(days=7)
            continue
        try:
            x = parse_release(p.body)
        except ValueError as e:
            rec.update(status="parse failed", error=str(e), sha256=p.sha256)
            audit.append(rec)
            wed += dt.timedelta(days=7)
            continue
        if x.wednesday != wed or x.prior_wednesday != wed - dt.timedelta(days=7):
            rec.update(status="table names another Wednesday", table_wednesday=x.wednesday.isoformat(), sha256=p.sha256)
            audit.append(rec)
            wed += dt.timedelta(days=7)
            continue
        pid = res.add_payload(p, root_rel, notes=f"H.4.1 release {rel.isoformat()} (archived document)")
        obs = et_ts(wed + dt.timedelta(days=1), 0, 0)               # end of the Wednesday the level describes
        pub = et_ts(rel, 16, 30)
        res.macro.append((SOURCE, SERIES, obs, pub, p.retrieved_ts, float(x.total_assets_musd) * 1e6, "USD",
                          f"first_release={rel.isoformat()}", p.sha256, "exact_release", pid))
        rec.update(status="ok", total_assets_musd=x.total_assets_musd, change_since_prior_musd=x.change_since_prior_musd,
                   implied_prior_musd=x.total_assets_musd - x.change_since_prior_musd,
                   eliminations_musd=x.eliminations_musd, sha256=p.sha256, observation_ts=obs, published_ts=pub)
        audit.append(rec)
        wed += dt.timedelta(days=7)
    res.notes.append(f"{sum(1 for a in audit if a.get('status') == 'ok')} Wednesdays recovered from archived releases; "
                     f"{sum(1 for a in audit if a.get('status') != 'ok')} not recovered (listed in the audit)")
    return res, audit
