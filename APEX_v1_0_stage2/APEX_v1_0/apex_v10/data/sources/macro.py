"""Direct-source macro adapters (no FRED). Each row carries observation, publication and retrieval times and an
availability-quality tag. Where the source cannot prove publication time, a deliberately late rule is used and
tagged `conservative_lag` (never presented as exact).

  fed_h41          Total assets (less eliminations), Wednesday level, series RESPPMA_N.WW, Fed Data Download
                   Program H.4.1 package. Release dates from the Fed's own H.4.1 release-date archive
                   (releaseDates.json), published at the documented 4:30 p.m. ET -> exact_release.
  nyfed_rrp        Overnight reverse repo, total accepted per operation date (NY Fed Markets API). Published at the
                   operation record's same-day `lastUpdated` stamp -> source_timestamp. Records edited on a later
                   date keep a same-day publication time but are tagged approximate (latest vintage only).
  treasury_tga     Treasury General Account closing balance (Daily Treasury Statement, Fiscal Data API). Published the
                   next business day; rule: 17:00 ET of the next federal business day -> conservative_lag.
  treasury_yields  Daily par yield curve, 2-year and 10-year (home.treasury.gov CSV). Rule: 20:00 ET same day ->
                   conservative_lag.
  cboe_vix         VIX daily close (CBOE history CSV). Rule: 17:00 ET same day -> conservative_lag.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import urllib.parse
import zipfile

from ..archive import RawArchive
from ..timeutil import ET, et_ts, next_business_day, parse_et
from .common import SourceResult

START_DATE = dt.date(2014, 1, 1)


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


# ---------------------------------------------------------------------------------------------------------------
def fed_h41(archive: RawArchive, asof_ts: int, root_rel: str) -> SourceResult:
    res = SourceResult("macro:fed_h41")
    cal = archive.get("fed_h41", "https://www.federalreserve.gov/releases/h41/releaseDates.json", spacing_s=1.0)
    cal_pid = res.add_payload(cal, root_rel, notes="H.4.1 release-date archive")
    release_days = []
    for year in json.loads(cal.body):
        for month in year.get("Months", []):
            for d in month.get("Dates", []):
                day = dt.date(int(d[:4]), int(d[4:6]), int(d[6:8]))
                release_days.append(day)
    release_days = sorted(set(release_days))
    for day in release_days:
        rts = et_ts(day, 16, 30)
        if rts <= asof_ts:
            res.releases.append(("fed_h41", day.isoformat(), rts, "federalreserve.gov/releases/h41/releaseDates.json",
                                 "exact_release"))
    pkg = archive.get("fed_h41", "https://www.federalreserve.gov/datadownload/Output.aspx?rel=H41&filetype=zip",
                      spacing_s=1.0)
    pid = res.add_payload(pkg, root_rel, notes="Fed DDP H.4.1 full package (SDMX XML); latest vintage at retrieval")
    with zipfile.ZipFile(io.BytesIO(pkg.body)) as z:
        xml = z.read("H41_data.xml").decode("utf-8", errors="replace")
    i = xml.find('SERIES_NAME="RESPPMA_N.WW"')
    if i < 0:
        raise ValueError("RESPPMA_N.WW not found in the H.4.1 package")
    seg = xml[i:xml.find("</kf:Series>", i)]
    if "Total assets (Less eliminations from consolidation): Wednesday level" not in seg:
        raise ValueError("RESPPMA_N.WW description changed; refusing to ingest an unverified series")
    import bisect
    for value, period in re.findall(r'OBS_VALUE="([^"]*)" TIME_PERIOD="([0-9-]{10})"', seg):
        wed = _d(period)
        if wed < START_DATE or value in ("", "ND", "NA"):
            continue
        k = bisect.bisect_right(release_days, wed)                 # first release strictly after the Wednesday
        if k >= len(release_days) or (release_days[k] - wed).days > 7:
            continue                                               # no proven release: not ingested
        pub = et_ts(release_days[k], 16, 30)
        obs = et_ts(wed + dt.timedelta(days=1), 0, 0)              # end of the Wednesday the level describes
        if pub > asof_ts:
            continue
        res.macro.append(("fed_h41", "RESPPMA_N.WW", obs, pub, pkg.retrieved_ts, float(value) * 1e6, "USD",
                          f"ddp_latest@{pkg.sha256[:12]};release={release_days[k].isoformat()}", pkg.sha256,
                          "exact_release", pid))
    res.notes.append("H.4.1 values are the DDP's latest vintage; release timing is exact, but a value revised after "
                     "first release would not show its first-release figure. Wednesday levels are rarely revised.")
    res.notes.append(f"release calendar provenance {cal_pid}")
    return res


# ---------------------------------------------------------------------------------------------------------------
def nyfed_rrp(archive: RawArchive, asof_ts: int, root_rel: str) -> SourceResult:
    res = SourceResult("macro:nyfed_rrp")
    end = dt.datetime.fromtimestamp(asof_ts, ET).date()
    q = urllib.parse.urlencode({"startDate": START_DATE.isoformat(), "endDate": end.isoformat(),
                                "operationTypes": "Reverse Repo"})
    p = archive.get("nyfed", f"https://markets.newyorkfed.org/api/rp/results/search.json?{q}", spacing_s=1.0)
    pid = res.add_payload(p, root_rel, notes="NY Fed reverse repo operation results")
    by_day: dict[dt.date, list[dict]] = {}
    for op in json.loads(p.body)["repo"]["operations"]:
        if op.get("operationType") != "Reverse Repo" or op.get("auctionStatus") != "Results":
            continue
        by_day.setdefault(_d(op["operationDate"]), []).append(op)
    for day in sorted(by_day):
        ops = by_day[day]
        total = sum(float(o.get("totalAmtAccepted") or 0) for o in ops)
        close = max(o.get("closeTime") or "13:15" for o in ops)
        hh, mm = (int(x) for x in close.split(":"))
        obs = et_ts(day, hh, mm)
        same_day = [parse_et(o["lastUpdated"]) for o in ops if (o.get("lastUpdated") or "")[:10] == day.isoformat()]
        later = sorted({o["lastUpdated"][:10] for o in ops if (o.get("lastUpdated") or "")[:10] > day.isoformat()})
        if later:
            # The record was edited after the operation day (e.g. 479 records stamped 2015-12-05). The result itself
            # was published that day, but only the latest vintage is available, so the value is flagged approximate.
            pub = max([obs + 30 * 60] + same_day)
            quality, vintage = "approximate", f"operations={len(ops)};record_updated={','.join(later)};latest_vintage"
        elif same_day:
            pub, quality, vintage = max(max(same_day), obs), "source_timestamp", f"operations={len(ops)}"
        else:
            pub, quality, vintage = obs + 30 * 60, "conservative_lag", f"operations={len(ops)};no_lastUpdated"
        if pub > asof_ts:
            continue
        res.macro.append(("nyfed", "rrp_total_accepted", obs, pub, p.retrieved_ts, total, "USD", vintage, p.sha256,
                          quality, pid))
    return res


# ---------------------------------------------------------------------------------------------------------------
TGA_LAYOUTS = (  # (account_type, value field, first record date, last record date) - verified continuous at seams
    ("Federal Reserve Account", "close_today_bal", None, dt.date(2021, 9, 30)),
    ("Treasury General Account (TGA)", "close_today_bal", dt.date(2021, 10, 1), dt.date(2022, 4, 15)),
    ("Treasury General Account (TGA) Closing Balance", "open_today_bal", dt.date(2022, 4, 18), None),
)


def treasury_tga(archive: RawArchive, asof_ts: int, root_rel: str) -> SourceResult:
    res = SourceResult("macro:treasury_tga")
    base = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance"
    for account, field, first, last in TGA_LAYOUTS:
        q = urllib.parse.urlencode({"fields": "record_date,account_type,close_today_bal,open_today_bal",
                                    "filter": f"account_type:eq:{account},record_date:gte:{START_DATE.isoformat()}",
                                    "sort": "record_date", "page[size]": "10000"})
        p = archive.get("treasury_fiscaldata", f"{base}?{q}", spacing_s=1.0)
        pid = res.add_payload(p, root_rel, notes=f"Daily Treasury Statement operating cash balance: {account}")
        for r in json.loads(p.body)["data"]:
            day = _d(r["record_date"])
            if (first and day < first) or (last and day > last):
                continue
            v = r.get(field)
            if v in (None, "null", ""):
                continue
            obs = et_ts(day + dt.timedelta(days=1), 0, 0)          # closing balance = end of the record date
            pub = et_ts(next_business_day(day), 17, 0)
            if pub > asof_ts:
                continue
            res.macro.append(("treasury_fiscaldata", "tga_closing_balance", obs, pub, p.retrieved_ts,
                              float(v) * 1e6, "USD", f"layout={account}:{field}", p.sha256, "conservative_lag", pid))
    # Seam check: the last closing balance of one layout must equal the first opening balance of the next.
    q = urllib.parse.urlencode({"fields": "record_date,account_type,close_today_bal,open_today_bal",
                                "filter": "record_date:in:(2021-09-30,2021-10-01,2022-04-15,2022-04-18)",
                                "sort": "record_date", "page[size]": "100"})
    p = archive.get("treasury_fiscaldata", f"{base}?{q}", spacing_s=1.0)
    res.add_payload(p, root_rel, notes="Daily Treasury Statement rows at the two layout seams (validation only)")
    idx = {(r["record_date"], r["account_type"]): r for r in json.loads(p.body)["data"]}
    seams = [(("2021-09-30", "Federal Reserve Account", "close_today_bal"),
              ("2021-10-01", "Treasury General Account (TGA)", "open_today_bal")),
             (("2022-04-15", "Treasury General Account (TGA)", "close_today_bal"),
              ("2022-04-18", "Treasury General Account (TGA) Opening Balance", "open_today_bal"))]
    for (d0, a0, f0), (d1, a1, f1) in seams:
        x, y = (idx.get((d0, a0)) or {}).get(f0), (idx.get((d1, a1)) or {}).get(f1)
        if x is None or x != y:
            raise ValueError(f"TGA layout seam {d0}->{d1} is not continuous ({x} vs {y}); refusing to splice")
        res.notes.append(f"TGA seam {d0}->{d1} continuous at {x} (USD millions)")
    res.macro.sort(key=lambda r: r[2])
    return res


# ---------------------------------------------------------------------------------------------------------------
def treasury_yields(archive: RawArchive, asof_ts: int, root_rel: str, start_year: int = START_DATE.year) -> SourceResult:
    res = SourceResult("macro:treasury_yields")
    last_year = dt.datetime.fromtimestamp(asof_ts, ET).year
    for year in range(start_year, last_year + 1):
        url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
               f"{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv")
        p = archive.get("treasury_yields", url, spacing_s=1.0)
        pid = res.add_payload(p, root_rel, notes=f"Daily Treasury par yield curve {year}")
        for row in csv.DictReader(io.StringIO(p.body.decode("utf-8-sig"))):
            day = dt.datetime.strptime(row["Date"], "%m/%d/%Y").date()
            obs, pub = et_ts(day, 15, 30), et_ts(day, 20, 0)
            if pub > asof_ts:
                continue
            for col, sid in (("2 Yr", "par_yield_2y"), ("10 Yr", "par_yield_10y")):
                v = (row.get(col) or "").strip()
                if v and v.upper() != "N/A":
                    res.macro.append(("treasury_yields", sid, obs, pub, p.retrieved_ts, float(v), "percent",
                                      None, p.sha256, "conservative_lag", pid))
    res.macro.sort(key=lambda r: (r[1], r[2]))
    return res


# ---------------------------------------------------------------------------------------------------------------
def cboe_vix(archive: RawArchive, asof_ts: int, root_rel: str) -> SourceResult:
    res = SourceResult("macro:cboe_vix")
    p = archive.get("cboe", "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv", spacing_s=1.0)
    pid = res.add_payload(p, root_rel, notes="CBOE VIX daily history")
    for row in csv.DictReader(io.StringIO(p.body.decode("utf-8-sig"))):
        day = dt.datetime.strptime(row["DATE"], "%m/%d/%Y").date()
        if day < START_DATE:
            continue
        obs, pub = et_ts(day, 16, 15), et_ts(day, 17, 0)
        if pub > asof_ts:
            continue
        res.macro.append(("cboe", "vix_close", obs, pub, p.retrieved_ts, float(row["CLOSE"]), "index_points", None,
                          p.sha256, "conservative_lag", pid))
    return res


ADAPTERS = {"fed_h41": fed_h41, "nyfed_rrp": nyfed_rrp, "treasury_tga": treasury_tga,
            "treasury_yields": treasury_yields, "cboe_vix": cboe_vix}
