"""APEX v0.5: from a gate to evidence. The owner's four decisions of 2 Oct 2026, built add-only over v0.4.1.

  1. APEX downloads its own price history from public sources (no download by the owner). The web lease opens at
     awakening (pre-approval revision 3) for read-only GETs to the market and attention hosts.
  2. Paper trading starts now (no money): two books, perps-cost long-short and spot-cost long-only.
  3. The simulation gate is replaced by a running evidence record (deflated Sharpe over every trial, the family's
     probability of backtest overfitting, and the paper record). The owner's approval stays only where money starts.
  4. Free social and attention sources start now: Wikipedia pageviews, GDELT news counts, Fear & Greed, funding.

One deployment: the live rung deploys exactly one artifact, the combined model at a pinned version, once, after
the owner ratifies it. `deployment_readiness()` lists everything still needed, and who must do it.

v0.5.1 (3 Oct 2026, the owner's next ideas): owner hypotheses can now be price levels, simple rules and media or
on-chain features (hypotheses_v051); free on-chain data (exchange flows and balances, MVRV, active addresses) and
GDELT news tone join the attention data; a third paper book, the BTC core trend book, is built and waits for the
owner to add it to the paper lease; every list in a lease scope now binds (not only hosts).
"""
from __future__ import annotations
import datetime as dt
import hashlib, json, math, time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable
from statistics import mean, pstdev
from .awakening import AwakeningError, _dev_key
from .authority_service import DEFAULT_CHANNEL_TRUST, IsolatedAuthority
from .authority_v05 import IsolatedAuthorityV5, LocalAuthorityV5, PAPER_VENUE
from .operator_channel import OwnerProfile, ContactChannel
from .incubation import FrontierItem
from .ledger import verify_chain, ContinuityLedger
from .organism_v04 import (OrganismV4, RecordingFrontier, rebuild_memory, apply_event, _MemoryTap, PROJECT_ROOT,
                           V04_FRONTIER, dev_presence, canonical)
from . import crypto_pack as cp
from . import data_v05 as dv
from . import research_v05 as rv
from .paper_v05 import PaperBook, apply_paper_event, evidence_from_paper
from . import hypotheses_v051 as hv

VERSION = "0.5.1"
V05_MODULES = ("apex.ext.authority_v05", "apex.ext.data_v05", "apex.ext.research_v05", "apex.ext.paper_v05",
               "apex.ext.organism_v05", "apex.ext.hypotheses_v051")

_KEEP = {"persistent memory", "local reasoning model", "self-model", "robust retrieval", "candidate evaluation",
         "whole-paper comprehension", "crypto corpus (T0)", "cross-AI collaboration", "voice interface", "visual portal"}
V05_FRONTIER = [i for i in V04_FRONTIER if i.name in _KEEP] + [
    FrontierItem("public price history", 0.8, 0.7, 0.7, 0.9, 0.25, 0.02, 0.10, ("network.web",)),
    FrontierItem("attention data", 0.6, 0.5, 0.6, 0.6, 0.25, 0.02, 0.10, ("network.web",)),
    FrontierItem("signal factory and combined model", 0.9, 0.8, 0.8, 0.9, 0.30, 0.03, 0.10, ("corpus.r0",)),
    FrontierItem("owner hypotheses", 0.6, 0.6, 0.7, 0.5, 0.20, 0.02, 0.05, ("corpus.r0",)),
]

VENUE_BOOKS = tuple(rv.VENUES)                     # rebalanced weekly from the combined model
CORE_BOOK = "btc_core_trend"                        # v0.5.1: rebalanced daily by one simple rule (hv.core_trend_weights)
CORE_SPEC = {"type": "rule", "product": "BTC-USD", "rule": "sma", "days": 200, "vol_target": 0.5, "band": 0.05,
             "cost_bps": 85.0}
BOOKS = {**{name: dict(cost_bps=spec["cost_bps"], long_short=spec["long_short"]) for name, spec in rv.VENUES.items()},
         CORE_BOOK: dict(cost_bps=85.0, long_short=False)}

READINESS_PROPOSED = {
    "research": "combined model deflated Sharpe >= 0.95 and family PBO <= 0.20",
    "paper": "the deployed book paper-traded >= 90 days, consistent with its backtest (z > -2), drawdown < 20%",
}


class OrganismV5(OrganismV4):
    def __init__(self, state_dir: str | Path = "state", isolated: bool = True, owner: OwnerProfile | None = None,
                 charter=None, presence_verifier: Callable[[str], bool] | None = dev_presence,
                 data_dir: str | Path | None = None, fetch_opener: Any = None, t0_min_days: float = 730.0,
                 sim_params: dict | None = None, seed_intervals: tuple = (60, 1440), seed_pairs: tuple | None = None,
                 model_backend: str = "mlx", model_python: str | None = None, models_need_apple_silicon: bool = True,
                 universe: tuple = dv.UNIVERSE, hourly: tuple = dv.HOURLY, pace_s: float = 0.25,
                 research_min_train: int = 52, r0_min_days: float = 730.0, r0_min_products: int = 10) -> None:
        # Same awakening as v0.4, with authorityd v0.5 (the leases decided on 2 Oct 2026).
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.state_dir / "events.jsonl"
        shell = verify_chain(self.ledger_path)
        if not shell.ok:
            raise AwakeningError(f"shell damaged; refusing to awaken on a broken history: {shell.errors[:3]}")
        self.shell_report = shell
        self.home = self.state_dir.resolve().parent
        self.data_dir = Path(data_dir) if data_dir else self.home / "data"
        self.t0_min_days, self.sim_params = t0_min_days, dict(sim_params or {})
        self.seed_intervals, self.seed_pairs = tuple(seed_intervals), (tuple(seed_pairs) if seed_pairs else None)
        self._fetch_opener = fetch_opener
        self._model_cfg = (model_backend, model_python, models_need_apple_silicon)
        self._band = None
        self.universe, self.hourly, self.pace_s = tuple(universe), tuple(hourly), pace_s
        self.research_min_train, self.r0_min_days, self.r0_min_products = research_min_train, r0_min_days, r0_min_products
        self.research: dict | None = None
        self.books = {n: PaperBook(n, **spec) for n, spec in BOOKS.items()}
        key = _dev_key(self.state_dir / "operator_dev.key")
        owner_file = self.state_dir / "owner.json"
        self.owner = owner or (OwnerProfile.from_file(owner_file) if owner_file.exists() else OwnerProfile(
            "owner", "Owner", [ContactChannel("outbox_file", str(self.state_dir / "operator_outbox.jsonl"), True, 0)]))
        trust = {**DEFAULT_CHANNEL_TRUST, **cp.CRYPTO_CHANNEL_TRUST, "local_model": 0.50}
        kw = dict(ledger_path=str(self.ledger_path), operator_key=key, channel_trust=trust)
        self.isolated = isolated
        self.memory = rebuild_memory(self.ledger_path)
        inner = IsolatedAuthorityV5(**kw) if isolated else LocalAuthorityV5(**kw)
        self.authority: Any = _MemoryTap(inner, lambda t, p: apply_event(self.memory, t, p))
        try:
            self._build(key, charter, presence_verifier)
            self._awaken_v05()
        except Exception:
            self.shutdown(record=False)
            raise

    # -- v0.5 construction ------------------------------------------------------------------------------------
    def _awaken_v05(self) -> None:
        self.fetcher = dv.FetcherV5(dv.V05_HOSTS, opener=self._fetch_opener, api_keys=self._api_keys(),
                                    budget=dv.PoliteBudget(wait=self.pace_s > 0))
        self.preapprovals_v05 = self._bootstrap_v05()
        self._refresh_allowlist()
        self._renew_leases()
        self.frontier = RecordingFrontier([FrontierItem(**asdict(i)) for i in V05_FRONTIER], self._frontier_changed)
        self.frontier.restore(self.memory)
        self._rebuild_paper()
        self._restore_research()
        self._register_owner_hypothesis_files()
        if not any(r.get("event_type") == "SignedMigration" and (r.get("payload") or {}).get("to") == VERSION
                   for r in ContinuityLedger(self.ledger_path).read()):
            prev = "0.5.0" if any(r.get("event_type") == "SignedMigration" and (r.get("payload") or {}).get("to") == "0.5.0"
                                  for r in ContinuityLedger(self.ledger_path).read()) else "0.4.1"
            payload = {"from": prev, "to": VERSION, "kind": "add-only (no v0.4 file changed)",
                       "new_modules": list(V05_MODULES), "decisions": "owner decisions 1-4, 2 Oct 2026; owner ideas 3 Oct 2026"}
            try:
                self.migration_v05 = self.authority.record_migration(*self.operator._signed("migration", **payload))
            except PermissionError as e:
                self.notes.append(f"v0.5 migration record deferred: {e}")
                self.migration_v05 = None
        else:
            self.migration_v05 = None
        self.authority.record("AwakenedV05", "organism", "proposal",
                              {"version": VERSION, "leases": [l["capability"] for l in self.authority.leases() if l["active"]],
                               "paper_books": {n: b.stats() for n, b in self.books.items()}})

    def _restore_research(self) -> None:
        """v0.5.1: the last evidence record survives a restart (it is in the ledger). It is marked as restored, so the
        next rebalance re-runs the research instead of trading on old scores."""
        rows, last = {}, None
        for r in ContinuityLedger(self.ledger_path).read():
            p = r.get("payload") or {}
            if r.get("event_type") == "ResearchTrial":
                rows[p.get("name")] = {k: v for k, v in p.items() if k != "name"}
            elif r.get("event_type") == "EvidenceUpdated":
                last = p
        if last:
            self.research = {"restored": True, "latest_day": None, "books": last.get("books"),
                             "evidence": {"rows": rows, "trials_counted": last.get("trials_counted"),
                                          "pbo_family": last.get("pbo_family")},
                             "benchmarks": last.get("benchmarks"), "attention_volatility": last.get("attention_volatility"),
                             "core_book": last.get("core_book")}

    def _bootstrap_v05(self) -> list[str]:
        f = PROJECT_ROOT / "constitution" / "preapproved_leases_v05.json"
        if not f.exists():
            return []
        doc = json.loads(f.read_text())
        have = {p["capability"]: p for p in self.authority.preapprovals()}
        applied = []
        for pre in doc.get("preapprovals", []):
            cur, rev = have.get(pre["capability"]), int(pre.get("revision", 1))
            if cur and int(cur.get("revision", 1)) >= rev:
                continue
            try:
                self.operator.preapprove_lease(pre["capability"], pre["scope"], float(pre["ttl_s"]),
                                               pre.get("condition", ""), doc.get("approved_on", ""), revision=rev)
                applied.append(pre["capability"])
            except PermissionError as e:
                self.notes.append(f"pre-approval for {pre['capability']} not applied: {e}")
                continue
            if any(l["capability"] == pre["capability"] and l["active"] for l in self.authority.leases()):
                self.operator.revoke_lease(pre["capability"], via=f"pre-approval revision {rev}")
        return applied

    def _owner_revoked(self) -> set[str]:
        """Capabilities whose latest lease event is a revoke by the owner (not an expiry, not a revision swap)."""
        state: dict[str, bool] = {}
        for r in ContinuityLedger(self.ledger_path).read():
            p = r.get("payload") or {}
            if r.get("event_type") == "LeaseGranted":
                state[p.get("capability")] = False
            elif r.get("event_type") == "LeaseRevoked":
                state[p.get("capability")] = not str(p.get("via", "")).startswith("pre-approval")
        return {c for c, revoked in state.items() if revoked}

    def _renew_leases(self) -> None:
        """Pre-approved leases with no condition stay open: an expired one reopens inside the same scope. A lease the
        owner revoked stays closed until the owner grants it again."""
        revoked = self._owner_revoked()
        for pre in self.authority.preapprovals():
            cap = pre["capability"]
            if pre.get("condition") or cap in revoked:
                continue
            if not any(l["capability"] == cap and l["active"] for l in self.authority.leases()):
                self._open_preapproved(cap)

    def _register_capabilities(self) -> None:
        super()._register_capabilities()
        from .runtime import CapabilityManifest
        reg = self.runtime.register

        def backfill(host: str = "", kind: str = "", product: str = "", interval: int = 1440) -> dict:
            if kind == "candles":
                prods = self.universe if product == "universe" else (product,)
                jobs = []
                for p in prods:
                    try:
                        jobs.append(dv.backfill_coinbase(self.fetcher, self.market, p, int(interval), pace_s=self.pace_s))
                    except PermissionError:
                        raise
                    except Exception as e:  # noqa: BLE001 - one bad product never stops the rest
                        jobs.append({"product": p, "interval": interval, "error": f"{type(e).__name__}: {e}"[:200]})
                return {"jobs": jobs}
            if kind == "attention":
                try:
                    return self._attention_job(host)
                except PermissionError:
                    raise
                except Exception as e:  # noqa: BLE001
                    return {"error": f"{type(e).__name__}: {e}"[:200]}
            raise PermissionError(f"unknown backfill kind {kind!r}")

        def paper_order(host: str = "", book: str = "", target: dict | None = None, prices: dict | None = None,
                        day: int = 0) -> dict:
            if host != PAPER_VENUE:
                raise PermissionError("paper orders go only to the in-process paper venue")
            return self.books[book].rebalance(dict(target or {}), dict(prices or {}), int(day))

        reg("data.backfill", backfill, CapabilityManifest(
            "data.backfill", ("network:GET batch within the lease",), True, 1.0, ("host", "kind", "product", "interval")))
        reg("market.paper_order", paper_order, CapabilityManifest(
            "market.paper_order", ("paper book only; nothing leaves this Mac",), True, 0.5,
            ("host", "book", "target", "prices", "day")))

    def _attention_job(self, host: str) -> dict:
        today = dt.datetime.now(dt.timezone.utc)
        out: dict = {}
        if host == "wikimedia.org":
            for article in dv.WIKI_ARTICLES:
                res = self.fetcher(host=host, path=f"/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/"
                                                   f"user/{article}/daily/20150701/{today:%Y%m%d}")
                out[f"wiki:{article}"] = self.market.add_readings(
                    "attention", [(f"wiki:{article}", d, v) for d, v in dv.parse_wikimedia(res)])
        elif host == "api.gdeltproject.org":
            jobs = [("timelinevolraw", q, f"gdelt:{q}") for q in dv.GDELT_QUERIES] + \
                   [("timelinetone", q, f"gdelt_tone:{q}") for q in dv.GDELT_TONE_QUERIES]
            for mode, q, metric in jobs:              # GDELT rate-limits: one failed query never costs the others
                try:
                    res = self.fetcher(host=host, path="/api/v2/doc/doc",
                                       params={"query": q, "mode": mode, "format": "json",
                                               "startdatetime": "20170101000000", "enddatetime": f"{today:%Y%m%d}000000"})
                    out[metric] = self.market.add_readings("attention", [(metric, d, v) for d, v in dv.parse_gdelt(res)])
                except PermissionError:
                    raise
                except Exception as e:  # noqa: BLE001
                    out[metric] = {"error": f"{type(e).__name__}: {e}"[:200]}
                if self.pace_s:
                    time.sleep(self.pace_s * 4)
        elif host == "community-api.coinmetrics.io":
            res = self.fetcher(host=host, path="/v4/timeseries/asset-metrics",
                               params={"assets": "btc", "metrics": ",".join(dv.CM_ONCHAIN_METRICS), "frequency": "1d",
                                       "start_time": "2015-01-01", "page_size": "10000"})
            out["onchain"] = self.market.add_readings("onchain", dv.parse_coinmetrics(res))
        elif host == "api.alternative.me":
            res = self.fetcher(host=host, path="/fng/", params={"limit": "0", "format": "json"})
            out["fear_greed"] = self.market.add_readings("attention", [("fear_greed", dv._day(t), v) for _, t, v in cp.parse_fng(res)])
        elif host == "futures.kraken.com":
            for sym, prod in dv.FUNDING_SYMBOLS.items():
                res = self.fetcher(host=host, path="/derivatives/api/v4/historicalfundingrates", params={"symbol": sym})
                out[f"funding:{prod}"] = self.market.add_readings("funding", [(f"funding:{prod}", d, v) for d, v in dv.parse_funding(res)])
        else:
            raise PermissionError(f"{host} is not an attention source")
        return out

    # -- availability and frontier work -------------------------------------------------------------------------
    def available(self) -> set[str]:
        avail = super().available()
        if self.memory.t0 and self.memory.t0.get("passed"):
            avail.add("corpus.r0")
        return avail

    def _governed(self, goal: str, capability: str, scope: dict, **kwargs: Any) -> dict:
        ev = self.perceive({"goal": goal, "capability": capability}, channel="system", source="frontier")
        return self.act(goal, capability, [ev], tier=1, scope=scope, **kwargs)

    def backfill_prices(self) -> dict:
        jobs = []
        for interval, prods in ((1440, ("universe",)), (60, self.hourly)):
            for p in prods:
                r = self._governed(f"backfill {p} {interval}m candles", "data.backfill",
                                   {"host": "api.coinbase.com", "product": p}, host="api.coinbase.com", kind="candles",
                                   product=p, interval=interval)
                res = getattr(r.get("outcome"), "measured_result", None)
                jobs.append({"product": p, "interval": interval, "decision": r["decision"].result,
                             "reasons": r["decision"].reasons, "result": res})
        gate = dv.r0_gate(self.market, self.r0_min_days, self.r0_min_products)
        self.authority.record("T0GateEvaluated", "evaluator", "proposal",
                              {"passed": gate.passed, "reasons": gate.reasons, "metrics": gate.metrics,
                               "digest": gate.digest(), "source": "coinbase public candles (R0)"})
        return {"jobs": jobs, "r0": asdict(gate)}

    def backfill_attention(self) -> dict:
        out = {}
        for host in ("wikimedia.org", "api.gdeltproject.org", "api.alternative.me", "futures.kraken.com",
                     "community-api.coinmetrics.io"):
            r = self._governed(f"attention data from {host}", "data.backfill", {"host": host}, host=host, kind="attention")
            out[host] = {"decision": r["decision"].result, "reasons": r["decision"].reasons,
                         "result": getattr(r.get("outcome"), "measured_result", None), "error": r.get("error")}
        return out

    def _prior_trial_names(self) -> set[str]:
        names = set()
        for row in ContinuityLedger(self.ledger_path).read():
            if row.get("event_type") in ("ResearchTrial", "HypothesisTested"):
                names.add((row.get("payload") or {}).get("name"))
        return names

    def research_v05(self) -> dict:
        panel = rv.Panel.from_store(self.market, list(self.universe))
        prior = self._prior_trial_names()
        res = rv.run_research(panel, prior_trials=0, min_train=self.research_min_train)
        if not res.get("trials"):
            return {"note": res.get("note", "no research")}
        names = {t.name for t in res["trials"]}
        res["evidence"] = rv.evidence_table(res["trials"], prior_trials=len(prior - names))
        for t in res["trials"]:
            row = res["evidence"]["rows"][t.name]
            self.authority.record("ResearchTrial", "evaluator", "proposal", {"name": t.name, **row})
        att = {k: dict((d, v) for _, d, v in self.market.db.execute(
            "SELECT metric, ts, value FROM readings WHERE source='attention' AND metric=?", (k,)))
               for k in ("wiki:Bitcoin", "gdelt:bitcoin")}
        att = {k: v for k, v in att.items() if v}
        res["attention_volatility"] = rv.attention_volatility_test(panel, att) if att else {"note": "no attention data yet"}
        core = hv.test_rule(self.market, CORE_SPEC, n_trials=len(prior | names) + 1)
        res["core_book"] = {k: core.get(k) for k in ("rule", "hold", "2022_on", "last_365d", "dsr", "vs_hold", "verdict")}
        self.authority.record("EvidenceUpdated", "evaluator", "proposal",
                              {"trials_counted": res["evidence"]["trials_counted"], "pbo_family": res["evidence"]["pbo_family"],
                               "books": res["books"], "benchmarks": res["benchmarks"], "latest_day": res["latest_day"],
                               "attention_volatility": res["attention_volatility"], "core_book": res["core_book"]})
        self.research = res
        return {k: v for k, v in res.items() if k not in ("trials", "latest_scores")}

    def _work_on(self, name: str) -> dict:
        if name == "public price history":
            r = self.backfill_prices()
            if r["r0"]["passed"]:
                self.frontier.complete(name)
            return {"r0": r["r0"], "jobs": [{k: j[k] for k in ("product", "interval", "decision")} for j in r["jobs"]]}
        if name == "attention data":
            r = self.backfill_attention()
            self.frontier.complete(name)
            if self.memory.t0 and self.memory.t0.get("passed") and self.pending_hypotheses():
                r["hypotheses_retested"] = self.test_pending_hypotheses()   # media and on-chain ideas need this data
            return r
        if name == "signal factory and combined model":
            r = self.research_v05()
            self.frontier.complete(name)
            return {k: r.get(k) for k in ("books", "benchmarks", "evidence", "attention_volatility")} if "books" in r else r
        if name == "owner hypotheses":
            r = self.test_pending_hypotheses()
            self.frontier.complete(name)
            return r
        return super()._work_on(name)

    # -- owner hypotheses ------------------------------------------------------------------------------------------
    def _register_owner_hypothesis_files(self) -> None:
        d = PROJECT_ROOT / "hypotheses"
        if not d.exists():
            return
        known = {(r.get("payload") or {}).get("id") for r in ContinuityLedger(self.ledger_path).read()
                 if r.get("event_type") == "HypothesisRegistered"}
        for f in sorted(d.glob("*.json")):
            for h in json.loads(f.read_text()).get("hypotheses", []):
                if rv.hypothesis_id(h["spec"]) not in known:
                    self.submit_hypothesis(h["name"], h["spec"], h.get("rationale", ""), source=f.name)

    def submit_hypothesis(self, name: str, spec: dict, rationale: str = "", source: str = "owner") -> str:
        """Owner input from financial theory or experience. It is registered BEFORE it is tested, then counted as a
        trial, so it can inform the research but cannot bypass the evidence record."""
        hid = rv.hypothesis_id(spec)
        self.authority.record("HypothesisRegistered", "owner-input", "proposal",
                              {"id": hid, "name": name, "spec": spec, "rationale": rationale[:500], "source": source})
        return hid

    def pending_hypotheses(self) -> list[dict]:
        reg, done = {}, set()
        for r in ContinuityLedger(self.ledger_path).read():
            p = r.get("payload") or {}
            if r.get("event_type") == "HypothesisRegistered":
                reg[p["id"]] = p
            elif r.get("event_type") == "HypothesisTested":
                done.add(p.get("id"))
        return [h for k, h in reg.items() if k not in done]

    def test_pending_hypotheses(self) -> dict:
        out = {}
        n_prior = len(self._prior_trial_names())
        for h in self.pending_hypotheses():
            n_prior += 1
            res = hv.test_hypothesis(self.market, h["spec"], n_trials=n_prior)
            if res.get("retry"):                       # its data is not here yet: stays pending, not counted
                n_prior -= 1
                out[h["name"]] = res["note"]
                continue
            self.authority.record("HypothesisTested", "evaluator", "proposal",
                                  {"id": h["id"], "name": f"hypothesis:{h['name']}", "spec": h["spec"], "result": res})
            out[h["name"]] = res.get("verdict", res.get("note"))
        return out

    # -- paper trading -------------------------------------------------------------------------------------------------
    def _rebuild_paper(self) -> None:
        self.books = {n: PaperBook(n, **spec) for n, spec in BOOKS.items()}
        for r in ContinuityLedger(self.ledger_path).read():
            if r.get("event_type") in ("PaperMark", "PaperRebalance"):
                apply_paper_event(self.books, r["event_type"], r.get("payload") or {})

    def _latest_prices(self) -> tuple[int | None, dict[str, float]]:
        row = self.market.db.execute("SELECT MAX(ts) FROM candles WHERE source='coinbase' AND interval=1440").fetchone()
        if not row or row[0] is None:
            return None, {}
        ts = int(row[0])
        prices = {p: c for p, c in self.market.db.execute(
            "SELECT pair, close FROM candles WHERE source='coinbase' AND interval=1440 AND ts=?", (ts,))}
        return ts // 86400, prices

    def _book_leased(self, book: str) -> bool:
        """Is this paper book inside the open market.paper_order lease? (Adding a book widens the lease: owner only.)"""
        for lease in self.authority.leases():
            if lease["capability"] == "market.paper_order" and lease["active"]:
                books = (lease.get("scope") or {}).get("book")
                return not isinstance(books, list) or book in books
        return False

    def _btc_closes_to(self, day: int) -> list[float]:
        return [c for (c,) in self.market.db.execute(
            "SELECT close FROM candles WHERE source='coinbase' AND pair='BTC-USD' AND interval=1440 AND ts<=? ORDER BY ts",
            (day * 86400,))]

    def paper_step(self, refresh: bool = True) -> dict:
        """Once per new UTC day: refresh prices and mark the books; once a week: research and rebalance the two model
        books; every day: the core book follows its rule (only once the owner has added it to the paper lease)."""
        if not any(l["capability"] == "market.paper_order" and l["active"] for l in self.authority.leases()):
            return {"note": "no paper lease"}
        if not (self.memory.t0 and self.memory.t0.get("passed")):
            return {"note": "waiting for R0 (public price history)"}
        day0, _ = self._latest_prices()
        if refresh and (day0 is None or day0 < int(time.time() // 86400) - 1):
            self._governed("refresh daily candles", "data.backfill", {"host": "api.coinbase.com", "product": "universe"},
                           host="api.coinbase.com", kind="candles", product="universe", interval=1440)
        day, prices = self._latest_prices()
        if day is None:
            return {"note": "no prices"}
        out: dict = {"day": dv.iso_day(day), "marked": [], "rebalanced": []}
        for name, book in self.books.items():
            if name == CORE_BOOK and not self._book_leased(name):
                continue
            if book.last_day is None or day > book.last_day:
                book.mark(prices, day)
                self.authority.record("PaperMark", "paper", "proposal", {"book": name, "day": day, "prices": prices})
                out["marked"].append(name)
        due = all(self.books[n].rebalances == 0 for n in VENUE_BOOKS) or day - self._last_rebalance_day() >= rv.HORIZON
        if due:
            if self.research is None or self.research.get("latest_day") != dv.iso_day(day):
                self.research_v05()
            res = self.research or {}
            scores = res.get("latest_scores") or {}
            for name in VENUE_BOOKS:
                book = self.books[name]
                w = rv.weights_from_scores({p: s for p, s in scores.items() if p in prices}, book.long_short)
                scale = (res.get("scale_now") or {}).get(name, 0.5)
                target = {p: v * scale for p, v in w.items()}
                r = self._governed(f"paper rebalance {name}", "market.paper_order", {"host": PAPER_VENUE, "book": name},
                                   host=PAPER_VENUE, book=name, target=target, prices=prices, day=day)
                if r["decision"].result == "approved" and r.get("outcome"):
                    self.authority.record("PaperRebalance", "paper", "proposal",
                                          {"book": name, "day": day, "target": target, "prices": prices})
                    out["rebalanced"].append({"book": name, "gross": round(sum(abs(v) for v in target.values()), 3)})
                else:
                    out.setdefault("denied", []).append({"book": name, "reasons": r["decision"].reasons})
        out["core"] = self._core_step(day, prices)
        out["books"] = {n: b.stats() for n, b in self.books.items() if n != CORE_BOOK or self._book_leased(n)}
        return out

    def _core_step(self, day: int, prices: dict[str, float]) -> dict:
        """The BTC core trend book: trade only when its rule's target changes (or to start or stop the position)."""
        if not self._book_leased(CORE_BOOK):
            return {"note": "built; waiting for the owner to add btc_core_trend to the paper lease"}
        if "BTC-USD" not in prices:
            return {"note": "no BTC price today"}
        closes = self._btc_closes_to(day)
        if len(closes) < 202:
            return {"note": "not enough BTC history"}
        ws = hv.core_trend_weights(closes)
        target, before = ws[-1], ws[-2]
        book = self.books[CORE_BOOK]
        cur = book.weights.get("BTC-USD", 0.0)
        if target == before and (cur > 0) == (target > 0):
            return {"target": round(target, 3), "traded": False}
        r = self._governed(f"paper rebalance {CORE_BOOK}", "market.paper_order", {"host": PAPER_VENUE, "book": CORE_BOOK},
                           host=PAPER_VENUE, book=CORE_BOOK, target={"BTC-USD": target}, prices=prices, day=day)
        if r["decision"].result == "approved" and r.get("outcome"):
            self.authority.record("PaperRebalance", "paper", "proposal",
                                  {"book": CORE_BOOK, "day": day, "target": {"BTC-USD": target}, "prices": prices})
            return {"target": round(target, 3), "traded": True}
        return {"target": round(target, 3), "traded": False, "denied": r["decision"].reasons}

    def _last_rebalance_day(self) -> int:
        days = [(r.get("payload") or {}).get("day") for r in ContinuityLedger(self.ledger_path).read()
                if r.get("event_type") == "PaperRebalance" and (r.get("payload") or {}).get("book") in VENUE_BOOKS]
        return max(days) if days else -10 ** 9

    def heartbeat_tick(self, user_active: bool = False, body=None, t: float | None = None) -> dict:
        self._renew_leases()
        out = super().heartbeat_tick(user_active, body, t)
        if out["band"] != "DORMANT":
            out["paper"] = self.paper_step()
            if self._attention_stale():
                out["attention_refresh"] = self.backfill_attention()
                if self.pending_hypotheses() and self.memory.t0 and self.memory.t0.get("passed"):
                    out["hypotheses_retested"] = self.test_pending_hypotheses()
        return out

    def _attention_stale(self) -> bool:
        """v0.5.1: media and on-chain data refresh weekly (v0.5 fetched them once), at most one attempt per 6 hours."""
        if not self.frontier_done("attention data") or time.time() - getattr(self, "_attention_try", 0.0) < 6 * 3600:
            return False
        row = self.market.db.execute("SELECT MAX(ts) FROM readings WHERE source='onchain'").fetchone()
        tone = self.market.db.execute("SELECT COUNT(*) FROM readings WHERE metric LIKE 'gdelt_tone:%'").fetchone()[0]
        stale = not row or row[0] is None or row[0] < int(time.time() // 86400) - 7 or not tone
        if stale:
            self._attention_try = time.time()
        return stale

    def frontier_done(self, name: str) -> bool:
        item = self.frontier.items.get(name)
        return bool(item and item.done)

    # -- evidence, ladder, deployment readiness ----------------------------------------------------------------------
    def continuity(self) -> tuple[bool, str]:
        ok, detail = super().continuity()
        rebuilt = {n: PaperBook(n, **spec) for n, spec in BOOKS.items()}
        for r in ContinuityLedger(self.ledger_path).read():
            if r.get("event_type") in ("PaperMark", "PaperRebalance"):
                apply_paper_event(rebuilt, r["event_type"], r.get("payload") or {})
        paper_ok = all(abs(rebuilt[n].equity - self.books[n].equity) < 1e-6 for n in self.books)
        return ok and paper_ok, detail + ("" if paper_ok else "; paper books differ from the ledger rebuild")

    def evidence_summary(self) -> dict:
        res = self.research or {}
        rows = (res.get("evidence") or {}).get("rows", {})
        top = sorted(rows.items(), key=lambda kv: -kv[1]["evidence"])[:5]
        paper = {n: evidence_from_paper(b) for n, b in self.books.items() if n != CORE_BOOK or self._book_leased(n)}
        return {"trials_counted": (res.get("evidence") or {}).get("trials_counted"),
                "pbo_family": (res.get("evidence") or {}).get("pbo_family"),
                "top": [{"name": k, **{x: v[x] for x in ("sharpe", "dsr", "evidence")}} for k, v in top],
                "combined": {k: v for k, v in rows.items() if k.startswith("model:")},
                "benchmarks": res.get("benchmarks"), "paper": paper,
                "attention_volatility": res.get("attention_volatility"), "core_book": res.get("core_book")}

    def ladder_v05(self) -> list[dict]:
        ev = self.evidence_summary()
        r0 = bool(self.memory.t0 and self.memory.t0.get("passed"))
        best_model = max((v.get("evidence", 0.0) for v in ev["combined"].values()), default=0.0)
        days = max((b.stats()["days"] for b in self.books.values()), default=0)
        return [
            {"rung": "R0", "name": "Public data", "state": "done" if r0 else "pending"},
            {"rung": "R1", "name": "Evidence (continuous)", "state": f"combined-model evidence {best_model:.2f} of 1.00"},
            {"rung": "R2", "name": "Paper trading (continuous)", "state": f"{days} days of paper record"},
            {"rung": "R3", "name": "Shadow", "state": "owner: venue, attorney review, limits, keys"},
            {"rung": "R4", "name": "Live, single deployment", "state": "owner ratification with verified presence"},
        ]

    def deployment_readiness(self) -> list[dict]:
        ev = self.evidence_summary()
        res = self.research or {}
        combined = ev["combined"]
        best = max(combined.items(), key=lambda kv: kv[1].get("dsr", 0.0), default=(None, {}))
        pbo = ev["pbo_family"]
        paper = ev["paper"]
        hatch = self.memory.hatch_stage
        items = [
            ("APEX", "Public price history validated (R0)", bool(self.memory.t0 and self.memory.t0.get("passed"))),
            ("APEX", f"Research evidence: {READINESS_PROPOSED['research']} (now: {best[0]} DSR "
                     f"{best[1].get('dsr', 0):.2f}, PBO {pbo})",
             bool(best[1].get("dsr", 0) >= 0.95 and pbo is not None and pbo <= 0.20)),
            ("APEX", f"Paper record: {READINESS_PROPOSED['paper']} (now: "
                     + ", ".join(f"{n} {p['days']} days" for n, p in paper.items()) + ")",
             any(p["days"] >= 90 and p["max_drawdown"] < 0.20 for p in paper.values())),
            ("APEX", "Halt drill passes under load (hatch criterion 9)", hatch == "HATCHED"),
            ("Owner", "Install the local models once: python3 setup_models.py", self.llm.ready()),
            ("Owner", "Add the BTC core trend book to paper trading (widens the paper lease by one book; paper only)",
             self._book_leased(CORE_BOOK)),
            ("Owner", "Choose the venue for the single deployment (US perps or spot) and complete the attorney review", False),
            ("Owner", "Set the capital ceiling, daily loss limit and drawdown halt in the charter",
             float(self.charter.spending_ceiling or 0) > 0),
            ("Owner", "Create a trade-only exchange API key (withdrawals disabled, IP allow-listed); "
                      "it goes into the macOS Keychain, never into a file", False),
            ("Claude", "Production key custody (Secure Enclave) and the evaluator out of process", False),
            ("Claude", "Live order adapter for the chosen venue, tested in the venue's sandbox", False),
            ("Owner", "Ratify the single deployment with verified presence: one model version, pinned by hash", False),
        ]
        return [{"who": w, "item": i, "done": bool(d)} for w, i, d in items]

    def morning_report(self) -> dict:
        rep = super().morning_report()
        rep.update({"version": VERSION, "ladder": self.ladder_v05(), "evidence": self.evidence_summary(),
                    "pending_hypotheses": [h["name"] for h in self.pending_hypotheses()],
                    "readiness_open": [r["item"] for r in self.deployment_readiness() if not r["done"]]})
        return rep


def awaken_v05(state_dir: str | Path = "state", isolated: bool = True, **kw: Any) -> OrganismV5:
    return OrganismV5(state_dir, isolated, **kw)
