"""Offline fixtures: tiny synthetic payloads in the exact shapes the real sources return, written into a temporary
raw archive so every adapter can be exercised without a network."""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import urllib.parse
import zipfile
from pathlib import Path

from apex_v10.data.archive import gzip_deterministic, request_key

ROOT_REL = "data_v10/raw"


class FakeArchiveBuilder:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lines: list[str] = []

    def add(self, source: str, url: str, body: bytes, retrieved_ts: int = 1791000000) -> None:
        sha = hashlib.sha256(body).hexdigest()
        rel = f"{source}/{sha}.gz"
        (self.root / source).mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_bytes(gzip_deterministic(body))
        self.lines.append(json.dumps({"request_key": request_key(url), "source": source, "url": url, "sha256": sha,
                                      "bytes": len(body), "path": rel, "retrieved_ts": retrieved_ts, "status": 200},
                                     sort_keys=True))

    def close(self) -> None:
        (self.root / "MANIFEST.jsonl").write_text("\n".join(self.lines) + "\n")


def iso(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def bitmex(b: FakeArchiveBuilder, asof: int) -> None:
    for sym in ("XBTUSD", "ETHUSD"):
        ev = []
        t0 = asof - 10 * 86400
        ev.append({"timestamp": iso(t0), "symbol": sym, "fundingInterval": "2000-01-02T00:00:00.000Z", "fundingRate": 0.0003})
        t = t0 + 86400
        while t <= asof + 3 * 28800:                                 # includes events after the as-of time
            ev.append({"timestamp": iso(t), "symbol": sym, "fundingInterval": "2000-01-01T08:00:00.000Z",
                       "fundingRate": 0.0001})
            t += 28800
        q = urllib.parse.urlencode({"symbol": sym, "count": 500, "start": 0, "reverse": "false"})
        b.add("bitmex", f"https://www.bitmex.com/api/v1/funding?{q}", json.dumps(ev).encode())


def deribit(b: FakeArchiveBuilder, asof: int, start: int) -> None:
    window = 30 * 86400
    for inst in ("BTC-PERPETUAL", "ETH-PERPETUAL"):
        t = start
        while t < asof:
            t_end = min(t + window, asof)
            rows = [{"timestamp": h * 1000, "index_price": 100.0, "interest_8h": 8e-5, "interest_1h": 1e-5,
                     "prev_index_price": 100.0} for h in range(t - t % 3600 + 3600, t_end + 1, 3600)]
            rows.append(rows[-1])                                   # a duplicate at the window edge
            q = urllib.parse.urlencode({"instrument_name": inst, "start_timestamp": t * 1000, "end_timestamp": t_end * 1000})
            b.add("deribit", f"https://www.deribit.com/api/v2/public/get_funding_rate_history?{q}",
                  json.dumps({"jsonrpc": "2.0", "result": rows}).encode())
            t = t_end


def kraken(b: FakeArchiveBuilder, asof: int) -> None:
    for sym in ("PF_XBTUSD", "PF_ETHUSD"):
        ts = [asof - 5 * 3600, asof - 4 * 3600, asof - 2 * 3600, asof - 3600, asof + 3600]   # a 2h gap, one future
        rates = [{"timestamp": iso(t).replace(".000", ""), "fundingRate": 0.5, "relativeFundingRate": 2e-6} for t in ts]
        b.add("kraken_futures", f"https://futures.kraken.com/derivatives/api/v4/historicalfundingrates?symbol={sym}",
              json.dumps({"result": "success", "rates": rates}).encode())


def intx(b: FakeArchiveBuilder, asof: int) -> None:
    for inst in ("BTC-PERP", "ETH-PERP"):
        ts = [asof - k * 3600 for k in range(0, 6)]                  # newest first, as the API returns
        res = [{"instrument_id": "1", "funding_rate": "0.00001", "mark_price": "50000", "event_time": iso(t).replace(".000", "")}
               for t in ts]
        q = urllib.parse.urlencode({"result_limit": 1000, "result_offset": 0})
        b.add("coinbase_intx", f"https://api.international.coinbase.com/api/v1/instruments/{inst}/funding?{q}",
              json.dumps({"pagination": {"result_limit": 1000, "result_offset": 0}, "results": res}).encode())


def h41(b: FakeArchiveBuilder) -> None:
    # Wednesdays 2024-07-03 (Thursday 4 July is a holiday -> released Friday 5 July) and 2024-07-10 (normal)
    dates = {"yearValue": "2024", "Months": [{"MonthName": "July", "MonthValue": "202407", "Dates": ["20240705", "20240711"]}]}
    b.add("fed_h41", "https://www.federalreserve.gov/releases/h41/releaseDates.json", json.dumps([dates]).encode())
    xml = ('<kf:Series SERIES_NAME="RESPPMA_N.WW" FREQ="19"><frb:Annotations><common:Annotation><common:AnnotationText>'
           'Assets: Total Assets: Total assets (Less eliminations from consolidation): Wednesday level'
           '</common:AnnotationText></common:Annotation></frb:Annotations>'
           '<frb:Obs OBS_STATUS="A" OBS_VALUE="7200000" TIME_PERIOD="2024-07-03" />'
           '<frb:Obs OBS_STATUS="A" OBS_VALUE="7190000" TIME_PERIOD="2024-07-10" />'
           '<frb:Obs OBS_STATUS="A" OBS_VALUE="7180000" TIME_PERIOD="2024-07-17" /></kf:Series>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("H41_data.xml", xml)
    b.add("fed_h41", "https://www.federalreserve.gov/datadownload/Output.aspx?rel=H41&filetype=zip", buf.getvalue())


def nyfed(b: FakeArchiveBuilder, asof: int) -> None:
    ops = [{"operationDate": "2015-03-02", "operationType": "Reverse Repo", "auctionStatus": "Results", "closeTime": "13:15",
            "lastUpdated": "2015-12-05 16:04:47", "totalAmtAccepted": 100000000},
           {"operationDate": "2024-07-01", "operationType": "Reverse Repo", "auctionStatus": "Results", "closeTime": "13:15",
            "lastUpdated": "2024-07-01 13:16:30", "totalAmtAccepted": 400000000000},
           {"operationDate": "2024-07-01", "operationType": "Reverse Repo", "auctionStatus": "Results", "closeTime": "13:00",
            "lastUpdated": "2024-07-01 13:05:00", "totalAmtAccepted": 1000000000}]
    end = dt.datetime.fromtimestamp(asof, dt.timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date()
    q = urllib.parse.urlencode({"startDate": "2014-01-01", "endDate": end.isoformat(), "operationTypes": "Reverse Repo"})
    b.add("nyfed", f"https://markets.newyorkfed.org/api/rp/results/search.json?{q}",
          json.dumps({"repo": {"operations": ops}}).encode())


TGA_BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance"


def tga(b: FakeArchiveBuilder, seam_ok: bool = True) -> None:
    layouts = [("Federal Reserve Account", [("2021-09-29", "200000", "190000"), ("2021-09-30", "215160", "200000")]),
               ("Treasury General Account (TGA)", [("2021-10-01", "132452", "215160"), ("2022-04-15", "578473", "602292")]),
               ("Treasury General Account (TGA) Closing Balance", [("2022-04-18", "null", "841253")])]
    for acct, rows in layouts:
        q = urllib.parse.urlencode({"fields": "record_date,account_type,close_today_bal,open_today_bal",
                                    "filter": f"account_type:eq:{acct},record_date:gte:2014-01-01",
                                    "sort": "record_date", "page[size]": "10000"})
        data = [{"record_date": d, "account_type": acct, "close_today_bal": c, "open_today_bal": o} for d, c, o in rows]
        b.add("treasury_fiscaldata", f"{TGA_BASE}?{q}", json.dumps({"data": data}).encode())
    seam = [{"record_date": "2021-09-30", "account_type": "Federal Reserve Account", "close_today_bal": "215160", "open_today_bal": "200000"},
            {"record_date": "2021-10-01", "account_type": "Treasury General Account (TGA)", "close_today_bal": "132452", "open_today_bal": "215160"},
            {"record_date": "2022-04-15", "account_type": "Treasury General Account (TGA)", "close_today_bal": "578473", "open_today_bal": "602292"},
            {"record_date": "2022-04-18", "account_type": "Treasury General Account (TGA) Opening Balance", "close_today_bal": "null",
             "open_today_bal": "578473" if seam_ok else "578000"}]
    q = urllib.parse.urlencode({"fields": "record_date,account_type,close_today_bal,open_today_bal",
                                "filter": "record_date:in:(2021-09-30,2021-10-01,2022-04-15,2022-04-18)",
                                "sort": "record_date", "page[size]": "100"})
    b.add("treasury_fiscaldata", f"{TGA_BASE}?{q}", json.dumps({"data": seam}).encode())


def yields(b: FakeArchiveBuilder, year: int) -> None:
    url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
           f"{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv")
    body = 'Date,"1 Mo","2 Yr","10 Yr"\n10/02/2026,4.0,3.50,4.10\n10/01/2026,4.0,N/A,4.12\n'
    b.add("treasury_yields", url, ("﻿" + body).encode("utf-8"))


def vix(b: FakeArchiveBuilder) -> None:
    body = "DATE,OPEN,HIGH,LOW,CLOSE\n12/31/2013,14,14,13,13.7\n10/01/2026,16.3,17.6,16.2,16.39\n10/02/2026,16.1,16.2,15.3,15.31\n"
    b.add("cboe", "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv", body.encode())
