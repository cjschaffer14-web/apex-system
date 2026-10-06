# T2 simulation gate audit (v0.4.1, 2 Oct 2026)

The owner asked for a check of the simulation gates and why performance was negative. The short answers:

* **Why performance was negative.** Trading costs and two simulator flaws, on test data that has no real edge. The flaws:
  * v0.4.0 closed every position at each fold boundary.
  * Its drawdown rule left the account mostly in cash after a loss.
* **Whether the gate works.** As built in v0.4.0, the ratified T2 gate passed pure noise 40% of the time. With the simulator fixed, the ratified gate rejects everything, including a real planted edge. The 1,000-trade minimum is the cause.
* **Proposed gate.** It passed 0% of noise runs and 70% of planted-edge runs at Kraken's current taker fee, or 90% at maker-level costs. It stays advisory until the owner ratifies it.

No real market data has been simulated yet; the Kraken seed is not downloaded. Every number below comes from synthetic prices, so none of them says anything about real markets.

**Fee correction.** On 9 July 2026 Kraken moved to cross-platform fee tiers. Tier 1 on Kraken Pro is now 0.40% maker and 0.80% taker; it was previously 0.25% and 0.40% ([Kraken fee schedule](https://www.kraken.com/features/fee-schedule), [Datawallet, 24 Aug 2026](https://www.datawallet.com/crypto/kraken-fees-explained)). v0.4.0 assumed the old 0.40% taker fee. v0.4.1 defaults to 0.80% plus 0.05% slippage, 85 bps on every change in exposure, and reports results at 10, 25, 45 and 85 bps.

## 1. Why performance was negative

The left column re-runs the build-time runs with the delivered v0.4.0 code (from `APEX_v0_4.zip`), which used 45 bps. The right column uses v0.4.1 at 85 bps.

| Run | v0.4.0 (45 bps, as delivered) | v0.4.1 (85 bps) |
|---|---|---|
| A. Daily synthetic, 3,000 bars (the negative run) | Sharpe −0.45, return −13.5%; T2 fail | Sharpe +0.37, return +19.1% (gross +46.3%); fails both gates |
| B. Hourly synthetic demo (`TEST_RESULTS_V0_4.txt`) | Sharpe 1.00, return +16%; **T2 pass**, but buy-and-hold Sharpe 2.80 | Sharpe 0.48, return +6.6% (gross +45.3%); fails both (below buy-and-hold) |
| C. Pure noise, hourly, 40,000 bars | Sharpe +0.10; **T2 pass (a false positive)** | Sharpe −1.10, halted at the 20% drawdown limit; fails both |
| D. Planted trend, hourly, 40,000 bars | Sharpe 1.78; T2 pass | Sharpe 1.31, return +42.5% (gross +144%); ratified fail (403 trades), **proposed pass** |

Four causes, in order of size:

1. **Costs.** Hourly strategies paid 6% to 25% a year in costs.
   * In run A under v0.4.0, a gross gain of +12% became a net loss of −13.5%.
   * In run B under v0.4.1, gross Sharpe was 2.67 and net was 0.48.
   * In noise run C, gross Sharpe was +0.44 and net was −1.10.

   The simulator now reports gross and net results, cost drag, turnover, and Sharpe at each cost level. Limit (maker) orders cost half as much as taker orders, which matters more than any signal tweak.
2. **Fold close-outs (v0.4.0 flaw).** Every position was sold at each fold boundary (every 90 days on daily data, every 30 days on hourly) and rebought in the next fold. Those were pure cost trades. v0.4.1 carries positions across folds.
3. **Cash-lock after drawdowns (v0.4.0 flaw).** Exposure was scaled by 1 − drawdown/20%, measured from the all-time peak. After a loss, the account sat mostly in cash and could not earn its way back. This is the known "CPPI cash-lock".

   v0.4.1 measures the brake against a rolling one-month high-water mark, with a floor of 25%. Separately, it applies a hard halt at a 20% all-time drawdown, which is the ratified Trading-pack limit. In live trading, the owner reviews before anything resumes.
4. **No edge in the test data.** Runs A to C are random walks. A strategy that loses its costs on noise is the simulator telling the truth. Long-or-flat strategies also sit out part of every rally. That is why run B trailed buy-and-hold in a strongly rising synthetic market.

Sizing was a fifth issue. v0.4.0 held up to 80% exposure in an asset with roughly 56% annual volatility, which made a 20% drawdown almost certain over several years. v0.4.1 targets 10% annual volatility, half the drawdown limit, using a trailing one-month estimate with no look-ahead. At 45 bps, a 20% target passed 35% of planted-edge runs, 15% passed 60%, and 10% passed 90%.

## 2. Does the gate tell skill from luck?

Each configuration ran 20 random seeds on each of two data types, using 40,000 hourly bars (about 4.5 years) and walk-forward with 90-day training and 30-day test windows. The data types:

* **Noise:** no edge exists, so every pass is a false positive.
* **Planted trend:** persistent up and down regimes with a drift of 0.06% per hour and a mean regime length of 500 hours. A real edge exists, so every pass is a true positive.

| Simulator, gate, costs | Passes on noise (false alarms) | Passes on planted edge (power) |
|---|---|---|
| v0.4.0 simulator, ratified gate, 45 bps | **40%** | 75% |
| v0.4.1 simulator, ratified gate, 45 or 85 bps | 0% | **0%** |
| v0.4.1 simulator, proposed gate, 85 bps (taker) | **0%** | **70%** |
| v0.4.1 simulator, proposed gate, 45 bps (maker) | 0% | 90% |

* **Why the ratified gate passed noise.** "Sharpe > 0" has no significance test. On a single noisy path, a positive out-of-sample Sharpe happens by chance about half the time. The 1,000-trade minimum did not help, because v0.4.0's churn made it easy to reach.
* **Why it rejects real edges once the simulator is honest.** Trend strategies trade about 150 to 450 times in 4.5 years, so they never reach 1,000 trades. That minimum rewards turnover, which is exactly what costs punish.

## 3. Proposed T2 gate (advisory until ratified)

`crypto_pack.t2_strict_gate` is recorded beside the ratified result on every T2 run (`T2GateEvaluated.proposed_gate`). It requires:

1. **Skill unlikely to be luck.** The deflated Sharpe ratio must be at least 0.95 (Bailey & López de Prado), using the Probabilistic Sharpe Ratio against the Sharpe that the best of N no-skill tries would reach. N counts every T2 run in the ledger, so re-running until something passes is discounted automatically.
2. **Value over holding.** The out-of-sample Sharpe must be above buy-and-hold's on the same bars.
3. **Risk.** The maximum drawdown must stay under 20%, and the drawdown halt must never trip.
4. **A minimum sample** of 100 out-of-sample trades, replacing 1,000.

The ladder still uses the ratified gate. Adopting the proposed gate is an owner decision.

## 4. Reproduce

```bash
python3 -c "from apex.ext.crypto_pack import gate_controls; print(gate_controls(seeds=20))"   # about 3 minutes
python3 -m unittest tests.test_apex_v04.SimulatorAudit
```

To reproduce v0.4.0's sizing, use `SimConfig(**crypto_pack.V040)`, and add `fee_bps=40` for its costs.
