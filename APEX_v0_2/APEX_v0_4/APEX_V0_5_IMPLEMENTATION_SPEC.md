# APEX v0.5: From a Gate to Evidence

v0.5 builds the owner's four decisions of 2 October 2026. It is add-only: no v0.2, v0.3 or v0.4 code file changed, and the earlier launchers still run on the same ledger. It is research and paper trading only. Nothing in v0.5 can place a real order, and nothing here is financial advice.

```
python3 awaken_v05.py                  # awaken, download public history, research, paper-trade, report
python3 awaken_v05.py --readiness      # what is still needed before the single live deployment, and who does it
python3 awaken_v05.py --hypothesis '{"name": "...", "spec": {...}, "rationale": "..."}'
python3 -m unittest discover -s tests  # 101 tests: 5 v0.2 + 38 v0.3 + 45 v0.4 + 13 v0.5
```

## 1. Decisions and where they live

| Decision (owner, 2 Oct 2026) | Built as |
|---|---|
| 1. APEX downloads its own history (no download by you) | `data_v05.py`. The pre-approval is revision 3 (`constitution/preapproved_leases_v05.json`), and the web lease opens at awakening. Coinbase public candles are downloaded daily for 20 coins since 2015, and hourly for BTC and ETH since 2017. Each backfill is one governed action, and its requests are spaced politely. |
| 2. Paper trading now | `paper_v05.py`. There are two books: perps-cost long-short (6 bps) and spot-cost long-only (85 bps). Each rebalance needs the `market.paper_order` lease and goes only to the in-process venue `paper.local`. The books rebuild from the ledger after a restart. |
| 3. Evidence record instead of the simulation gate | `research_v05.py`. Every trial is logged. The deflated Sharpe counts every trial ever run, and CSCV gives the family's probability of backtest overfitting. The two combine into one continuous evidence score. Your approval is needed only where real money starts. |
| 4. Free social and attention sources now | Wikipedia pageviews (since 2015), GDELT news counts (since 2017), Fear & Greed (since 2018) and Kraken funding rates (the last 12 months, then collected going forward). An attention → volatility test runs against a HAR baseline. |
| Single deployment | The live rung deploys one artifact once: the combined model, pinned by hash. `deployment_readiness()` lists every remaining item and who must do it. |
| Your own alpha ideas | Owner hypotheses are registered before they are tested, then counted as trials. Your 6-cycle ideas are in `hypotheses/owner_2026-10-02.json`. |

## 2. How it fits

```
public data (lease) ─► signal factory (12 weak signals, 20 coins) ─► combined model (ridge, purged, expanding)
        │                                                                     │
        └─► attention (Wikipedia, GDELT, F&G, funding) ─► volatility test     ▼
owner hypotheses ─► registered ─► tested in two periods ─► evidence record (DSR over all trials, PBO, paper)
                                                                              │
                                    paper books (perps / spot) ◄── weekly rebalance, daily marks (lease)
                                                                              │
                                     single live deployment ◄── owner: venue, attorney, limits, keys, ratification
```

**The signals:**
* momentum over 3, 7, 14, 28 and 56 days;
* 1-day reversal;
* low volatility;
* trend versus the 50-day average;
* lottery (the maximum recent daily return);
* abnormal volume;
* low beta to BTC;
* an empirical-dynamic-modelling forecast (Takens delay embedding with simplex projection; the "manifold" signal).

Each uses data up to the decision day only, and a test changes future prices to prove it. Books trade only when at least 6 coins are available, are volatility-targeted, and charge their venue's costs on turnover.

## 3. First run on real data (2 Oct 2026, from this build machine)

The run covered 20 Coinbase coins (daily since 2015) plus BTC and ETH hourly (since 2017). All results are out of sample, net of costs, with 21 trials counted.

| Item | Sharpe | Deflated Sharpe | Evidence (0–1) |
|---|---|---|---|
| Best single signal: 14-day momentum, long-short at perps cost | 0.96 | 0.78 | 0.47 |
| Combined model, perps long-short | 0.26 | 0.11 | 0.06 |
| Combined model, spot long-only | 0.19 | 0.08 | 0.05 |
| Benchmarks: BTC held / equal-weight basket held | 1.13 / 0.72 | | |

The family's probability of backtest overfitting is 0.40.

What the run shows:

* **No demonstrated edge yet.** The combined model is weaker than its best signal, because adding noisy signals dilutes the good one. Better combinations go into the research loop as counted trials.
* **Attention → volatility:** Wikipedia views improved the next-week volatility forecast by 0.8% (t = 0.85), which is not significant.
* **Owner 6-cycle hypotheses**, tested in two periods (to 2021, then 2022–26) with multiple-testing control:

| Hypothesis | BTC | ETH |
|---|---|---|
| Return in the 06:00 UTC hour | not supported | not supported |
| Return on the 6th day of the month | not supported | – |
| Return on Saturday | not supported | – |
| A 6-month cycle | inside the noise band | inside the noise band |
| Volatility in the 06:00 UTC hour | **supported:** it is significantly lower (t −5.4 and −7.2) | – |

  The volatility result is the ordinary daily rhythm of global market hours. Volatility peaks around the US open; 06:00 UTC sits in the quiet stretch. It can help choose when to trade, but it says nothing about direction.

* **Paper trading has started.** Day 1 holds only the entry costs: −0.05% on the perps book and −0.68% on the spot book.

## 4. What is still needed before the single live deployment

| Who | Item |
|---|---|
| APEX | Research evidence: combined-model deflated Sharpe ≥ 0.95 and family PBO ≤ 0.20 (proposed threshold) |
| APEX | Paper record: at least 90 days for the book to be deployed, consistent with its backtest, drawdown under 20% (proposed) |
| Owner | Install the local models once (`python3 setup_models.py`) |
| Owner | Choose the venue (US perpetual futures or spot) and complete the attorney review |
| Owner | Set the capital ceiling, daily loss limit and drawdown halt in the charter |
| Owner | Create a trade-only exchange API key: withdrawals disabled, IP allow-listed, stored in the macOS Keychain |
| Claude | Production key custody (Secure Enclave) and the evaluator out of process |
| Claude | A live order adapter for the chosen venue, tested in the venue's sandbox |
| Owner | Ratify the single deployment with verified presence |

Already done: R0 public data, and the halt drill under load (hatch criterion 9).

## 5. Bringing your own ideas

```json
{"name": "6th hour (UTC) return, BTC", "spec": {"type": "calendar", "unit": "hour", "value": 6, "product": "BTC-USD", "measure": "return"},
 "rationale": "why you expect it"}
```

* **Supported now:** `calendar` (unit `hour`, `weekday`, `monthday` or `month`; measure `return` or `abs_return`) and `cycle` (a lag in months).
* **Next, in v0.6:** event studies (exchange listings, token unlocks, launches, announcements), which need event data, and feature rules over any stored series.

Each idea is recorded before it is tested and counts as a trial. It can steer the research, but it cannot skip the evidence.

**Boundaries (not negotiable in code):**
* Public information only. Trading on non-public information is insider trading, and it has been prosecuted in crypto.
* No coordinated pumps.
* Taking part in token sales needs the attorney review first.

## 6. Fixes found while building

* **The action budget never refilled.** Since v0.3, about 90 approved actions would have exhausted it for the life of the process. v0.5 makes it a rolling 24-hour window.
* **Owner revocations now stick.** A lease you revoke is not reopened automatically at the next awakening.
* **Network errors are data, not crashes.** HTTP 429 and 5xx responses are retried with backoff, and GDELT is spaced 6 seconds apart.
* **Date labels pass the membrane.** Timestamps and dates now cross; free text still does not.
* **Off-by-one in the first calendar test.** The ad-hoc check run before v0.5 (in the reply, not shipped) labelled each return one hour or one day early. The v0.5 engine labels each candle's return with that candle's own start time, and section 3 reports the corrected results.

## 7. v0.5.1: the owner's ideas of 3 October (appended)

The full results are in `docs/OWNER_IDEAS_2026-10-03.md`, and the code and data are in `research/owner_ideas_2026-10-03/`.

| Idea | Result |
|---|---|
| Round numbers, golden-ratio multiples, powers of 1.618 / 1.1618 / e / pi | None of the 7 families beats the same grid shifted to random positions (400 shifted copies, two periods). The test does detect a planted 9-point bounce-rate lift 80% of the time. |
| A simple positive-return rule (Occam's razor) | Holding BTC above its 200-day average, sized to 50% volatility, made +45% a year over 2016–26 after 85 bps costs (BTC held: +66%). It cut the worst drawdown from 84% to 58%; in 2022–26, from 67% to 33%. Over the last 12 months it returned −4% against −30% for holding. It does not beat holding on Sharpe. |
| Media and whale activity | Nothing predicts direction in both periods. Wikipedia attention surprises and exchange inflows predict next-week volatility beyond today's volatility (full-sample z +3.4), strongest before 2022. |

**What changed in code** (v0.5 files patched in place, as in v0.4.1; v0.4 stays byte-identical):

* **New owner hypothesis kinds** (`hypotheses_v051.py`, standard library only):
  * `level`: price levels in geometric, round or arithmetic families, tested against randomly shifted copies of the same grid.
  * `rule`: a simple long-only rule tested against holding the same coin, with costs, a block bootstrap and the deflated Sharpe.
  * `feature`: any media or on-chain series tested against the next 7- or 28-day return or the next week's volatility; volatility tests control for today's volatility.
* **New data, all on hosts the web lease already covers:**
  * on-chain series from the Coin Metrics Community API: exchange inflows and outflows, exchange balances, MVRV, active addresses;
  * GDELT news tone.
  * Attention and on-chain data now refresh weekly.
* **The BTC core trend book:** a third paper book that follows `core_trend_weights` daily. It trades only after the owner adds it to the paper lease (`deployment_readiness()` lists that item).
* **Lease scopes:** every list in a lease scope now binds (paper books, for example), not only hosts. Before this fix, a paper order for a book outside the lease would have passed.
* **Hypotheses waiting for data:** a hypothesis whose data has not arrived stays pending and is not counted as a trial. It is retested after the next attention backfill.
* **The evidence record survives a restart.** It is restored from the ledger and marked as restored, so the next rebalance re-runs the research instead of trading on old scores.

```json
{"name": "...", "spec": {"type": "level", "family": "geometric", "ratio": 1.618}}
{"name": "...", "spec": {"type": "level", "family": "round", "mantissas": [1, 2, 5], "times": 1.0}}
{"name": "...", "spec": {"type": "rule", "rule": "sma", "days": 200, "vol_target": 0.5, "cost_bps": 85}}
{"name": "...", "spec": {"type": "feature", "feature": "exchange_netflow_7d", "target": "return7"}}
```

The feature names are listed in `hypotheses_v051.FEATURES`.
