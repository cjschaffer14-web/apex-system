# First real-data baseline (2 Oct 2026)

This is the first time APEX's trading research has run on real prices. The data is Coinbase's free public candles (no key) for BTC and ETH, daily from 2015/2016 and hourly from 2017, plus daily candles for 16 other coins, all through 3 Oct 2026. The scripts and raw results are in `research/real_data_2026-10-02/`. Nothing here is financial advice.

## 1. The current engine: 8 simple rules, walk-forward, 10% volatility target

Sharpe ratios are out of sample and net of costs. Cost levels per side:

* 85 bps: Kraken Pro tier-1 taker, 0.80%, plus slippage.
* 45 bps: Kraken Pro tier-1 maker, 0.40%, plus slippage.
* 10 bps: about the level of US perpetual futures.

| Series | Net Sharpe at 85 / 45 / 10 bps | Gross Sharpe | Buy-and-hold Sharpe | Passes a gate? |
|---|---|---|---|---|
| BTC daily | 0.82 / 1.01 / 0.90 | 1.12 | 1.04 | No |
| ETH daily | 0.54 / 0.60 / 0.56 | 0.82 | 0.85 | No |
| BTC hourly | 0.01 / 0.15 / 0.49 | 0.90 | 1.00 | No |
| ETH hourly | 0.09 / 0.40 / 0.70 | 1.34 | 0.92 | Ratified gate only at 10 bps; proposed gate never |

What this shows:

* **Nothing beats holding** on a risk-adjusted basis at today's spot fees.
* **Hourly trading at spot fees is wiped out by costs.** ETH hourly makes a gross Sharpe of 1.34, which is above buy-and-hold, and a net Sharpe of 0.09 at the taker fee.
* **The drawdown halt tripped in most runs.** With a 10% volatility target, average exposure was only 4–10%, so absolute returns are small.
* **The ratified gate's weakness shows up on real data.** It passed ETH hourly at 10 bps, a result that still trails buy-and-hold and has a deflated Sharpe of 0.81.

## 2. Breadth: cross-sectional 2-week momentum, 18 coins, weekly rebalance

The rule is fixed in advance from Borri, Liu, Tsyvinski & Wu (2026). It is not tuned.

| Version | Sharpe | Max drawdown |
|---|---|---|
| Long top 3 / short bottom 3, at perp-level cost (6 bps) | **0.78** (PSR 0.98) | 36% |
| Same, at spot taker cost (85 bps) | −0.62 | 89% |
| Long top 3 only, 45 bps | 0.74 | 91% |
| Equal-weight basket, held | 0.75 | 81% |

* **Survivorship bias:** the universe is coins still listed on Coinbase today, which flatters long-only results.
* **The edge, if there is one, is only reachable at low cost.** Long-short momentum survives at perpetual-futures costs and dies at spot fees.

## 3. Fibonacci retracements against random levels

The rule: buy a pullback into a retracement level of the latest 60-bar up-swing once price turns up, then exit at the swing high, at the 78.6% stop, or after 60 bars. The same rule was run with the Fibonacci levels (38.2%, 50%, 61.8%), with 40 random sets of three levels drawn between 25% and 75%, and with thirds (33.3%, 50%, 66.7%). Sharpe ratios here are gross, before costs.

| Series | Fibonacci | Random levels (median) | Fibonacci's percentile among random sets | Thirds |
|---|---|---|---|---|
| BTC daily | 0.45 | 0.48 | 50th | 0.58 |
| BTC hourly | 0.66 | 0.71 | 42nd | 0.76 |
| ETH daily | 0.01 | 0.19 | 20th | 0.04 |
| ETH hourly | 0.05 | 0.14 | 38th | 0.23 |

**Fibonacci levels did no better than random levels.** This matches the best-controlled study (Tsinaslanidis, Guijarro & Voukelatos, *Expert Systems with Applications*, 2022). Net of costs, the hourly versions lose heavily (Sharpe −1.9 and −1.5 at 45 bps).

## Reproduce

```bash
cd research/real_data_2026-10-02
python3 fetch.py BTC-USD 86400 2015-07-20     # and 3600 for hourly; same for other products
python3 baseline.py; python3 fib.py; python3 xsec.py
```
