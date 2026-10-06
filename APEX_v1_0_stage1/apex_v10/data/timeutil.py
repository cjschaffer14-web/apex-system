"""Time helpers: UTC epoch seconds, US Eastern wall-clock conversion, US federal business days."""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
ET = ZoneInfo("America/New_York")


def utc_ts(d: dt.datetime) -> int:
    if d.tzinfo is None:
        raise ValueError("naive datetime")
    return int(d.timestamp())


def iso_to_ts(s: str) -> int:
    """'2026-09-16T12:00:00.000Z' / '2026-09-16T12:00:00Z' -> epoch seconds."""
    s = s.strip().replace("Z", "+00:00")
    return utc_ts(dt.datetime.fromisoformat(s))


def ts_to_iso(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def et_ts(day: dt.date, hour: int, minute: int = 0, second: int = 0) -> int:
    """Epoch seconds of a US Eastern wall-clock time on `day` (DST handled by the tz database)."""
    return utc_ts(dt.datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=ET))


def parse_et(s: str) -> int:
    """'2016-01-08 13:17:41' (US Eastern) -> epoch seconds."""
    d = dt.datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=ET)
    return utc_ts(d)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(weekday - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> dt.date:
    d = dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: dt.date) -> dt.date:
    if d.weekday() == 5:
        return d - dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + dt.timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def federal_holidays(year: int) -> frozenset[dt.date]:
    """US federal holidays (observed dates). Juneteenth from 2021."""
    h = {
        _observed(dt.date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),            # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),            # Washington's Birthday
        _last_weekday(year, 5, 0),              # Memorial Day
        _observed(dt.date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),            # Labor Day
        _nth_weekday(year, 10, 0, 2),           # Columbus Day
        _observed(dt.date(year, 11, 11)),
        _nth_weekday(year, 11, 3, 4),           # Thanksgiving
        _observed(dt.date(year, 12, 25)),
    }
    if year >= 2021:
        h.add(_observed(dt.date(year, 6, 19)))
    nxt = _observed(dt.date(year + 1, 1, 1))    # 1 Jan on a Saturday is observed on 31 Dec
    if nxt.year == year:
        h.add(nxt)
    return frozenset(h)


def is_business_day(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in federal_holidays(d.year)


def next_business_day(d: dt.date) -> dt.date:
    d = d + dt.timedelta(days=1)
    while not is_business_day(d):
        d += dt.timedelta(days=1)
    return d


def business_days(start: dt.date, end: dt.date) -> int:
    n, d = 0, start
    while d <= end:
        n += is_business_day(d)
        d += dt.timedelta(days=1)
    return n
