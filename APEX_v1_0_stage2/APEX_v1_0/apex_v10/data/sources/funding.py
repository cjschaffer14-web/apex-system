"""Perpetual-funding event adapters. Each venue keeps its own symbols, timestamps and rate semantics; nothing is
spliced into a synthetic "crypto funding rate" (Stage 0 review decision). All four venues are offshore proxies for
whichever US venue APEX may use later; backtests must name the proxy they used.

  bitmex          XBTUSD, ETHUSD    settlement events; interval from the source field `fundingInterval`
  deribit         BTC/ETH-PERPETUAL continuous funding sampled hourly (interest_1h); 744-record cap per request
  kraken_futures  PF_XBTUSD, PF_ETHUSD hourly relative funding (API window ~12 months)
  coinbase_intx   BTC-PERP, ETH-PERP hourly funding with mark price (2023+)

Binance and Bybit are not ingested: both refuse US connections (HTTP 451 / 403), and access is not circumvented.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.parse

from ..archive import RawArchive
from ..timeutil import iso_to_ts
from .common import SourceResult

Q_SRC = "source_timestamp"
_EPOCH_2000 = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)


def _derived_intervals(rows: list[tuple], ts_idx: int = 2) -> list[int]:
    out, prev = [], None
    for r in rows:
        out.append(r[ts_idx] - prev if prev is not None else 0)
        prev = r[ts_idx]
    return out


def bitmex(archive: RawArchive, asof_ts: int, root_rel: str) -> SourceResult:
    res = SourceResult("funding:bitmex")
    for symbol in ("XBTUSD", "ETHUSD"):
        start = 0
        while True:
            q = urllib.parse.urlencode({"symbol": symbol, "count": 500, "start": start, "reverse": "false"})
            p = archive.get("bitmex", f"https://www.bitmex.com/api/v1/funding?{q}", spacing_s=1.2)
            pid = res.add_payload(p, root_rel, notes=f"BitMEX funding history {symbol} offset {start}")
            data = json.loads(p.body)
            for e in data:
                ts = iso_to_ts(e["timestamp"])
                if ts > asof_ts:
                    continue
                interval = int((dt.datetime.fromisoformat(e["fundingInterval"].replace("Z", "+00:00")) - _EPOCH_2000)
                               .total_seconds())
                res.funding.append(("bitmex", symbol, ts, float(e["fundingRate"]), interval, "source_field",
                                    "bitmex_settlement_rate_per_interval", None, None, ts, Q_SRC, pid))
            if len(data) < 500 or iso_to_ts(data[-1]["timestamp"]) > asof_ts:
                break
            start += 500
    return res


def deribit(archive: RawArchive, asof_ts: int, root_rel: str, start_ts: int = 1530403200) -> SourceResult:
    """Walk 30-day windows (720 hourly samples < the 744-record cap) from mid-2018 to the as-of time."""
    res = SourceResult("funding:deribit")
    window = 30 * 86400
    for inst in ("BTC-PERPETUAL", "ETH-PERPETUAL"):
        seen = set()
        t = start_ts
        while t < asof_ts:
            t_end = min(t + window, asof_ts)
            q = urllib.parse.urlencode({"instrument_name": inst, "start_timestamp": t * 1000,
                                        "end_timestamp": t_end * 1000})
            p = archive.get("deribit", f"https://www.deribit.com/api/v2/public/get_funding_rate_history?{q}",
                            spacing_s=0.25)
            pid = res.add_payload(p, root_rel, notes=f"Deribit funding history {inst}")
            for e in json.loads(p.body).get("result", []):
                ts = int(e["timestamp"]) // 1000
                if ts in seen or ts > asof_ts or e.get("interest_1h") is None:
                    continue
                seen.add(ts)
                res.funding.append(("deribit", inst, ts, float(e["interest_1h"]), 3600, "source_sampling",
                                    "deribit_continuous_funding_hourly_sample:interest_1h",
                                    None, float(e["index_price"]) if e.get("index_price") is not None else None,
                                    ts, Q_SRC, pid))
            t = t_end
    res.funding.sort(key=lambda r: (r[0], r[1], r[2]))
    res.notes.append("Deribit funding accrues continuously; interest_1h is stored as an hourly sample. The exact "
                     "accrual formula must be confirmed against Deribit documentation before execution use.")
    return res


def kraken_futures(archive: RawArchive, asof_ts: int, root_rel: str) -> SourceResult:
    res = SourceResult("funding:kraken_futures")
    for sym in ("PF_XBTUSD", "PF_ETHUSD"):
        p = archive.get("kraken_futures",
                        f"https://futures.kraken.com/derivatives/api/v4/historicalfundingrates?symbol={sym}", spacing_s=1.0)
        pid = res.add_payload(p, root_rel, notes=f"Kraken Futures historical funding {sym}")
        rows = []
        for e in json.loads(p.body).get("rates", []):
            ts = iso_to_ts(e["timestamp"])
            if ts > asof_ts:
                continue
            rows.append(["kraken_futures", sym, ts, float(e["relativeFundingRate"]), None, "derived_spacing",
                         "kraken_relative_funding_rate_per_period", None, None, ts, Q_SRC, pid])
        rows.sort(key=lambda r: r[2])
        for r, gap in zip(rows, _derived_intervals(rows)):
            r[4] = gap or None
            res.funding.append(tuple(r))
    return res


def coinbase_intx(archive: RawArchive, asof_ts: int, root_rel: str) -> SourceResult:
    res = SourceResult("funding:coinbase_intx")
    for inst in ("BTC-PERP", "ETH-PERP"):
        rows, offset = [], 0
        while True:
            q = urllib.parse.urlencode({"result_limit": 1000, "result_offset": offset})
            p = archive.get("coinbase_intx",
                            f"https://api.international.coinbase.com/api/v1/instruments/{inst}/funding?{q}", spacing_s=0.5)
            pid = res.add_payload(p, root_rel, notes=f"Coinbase International funding {inst} offset {offset}")
            data = json.loads(p.body).get("results", [])
            for e in data:
                ts = iso_to_ts(e["event_time"])
                if ts > asof_ts:
                    continue
                rows.append(["coinbase_intx", inst, ts, float(e["funding_rate"]), None, "derived_spacing",
                             "coinbase_intx_funding_rate_per_period", float(e["mark_price"]) if e.get("mark_price") else None,
                             None, ts, Q_SRC, pid])
            if len(data) < 1000:
                break
            offset += 1000
        rows.sort(key=lambda r: r[2])
        dedup = {}
        for r in rows:
            dedup.setdefault(r[2], r)
        rows = list(dedup.values())
        for r, gap in zip(rows, _derived_intervals(rows)):
            r[4] = gap or None
            res.funding.append(tuple(r))
    return res


ADAPTERS = {"bitmex": bitmex, "deribit": deribit, "kraken_futures": kraken_futures, "coinbase_intx": coinbase_intx}
