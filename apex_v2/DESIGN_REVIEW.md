# Design review: Global Arbitrage Observatory + apex_v2, and where profit could come from

Date: 2026-10-07. Scope: read `APEX_Global_Arbitrage_Observatory_Update/` (all files), `APEX_exact_shadow 2/` and
`APEX_HANDOFF.md`, `DEXARBSTRAT4OPUS.rtf`, and my own `apex_v2/`. I did not open the large `APEX System/` v0.x-v1.0 archives
(specs, sqlite databases, zips): they are strategy research for the original 286-portfolio suite, not the arbitrage lane.
**Nothing below is evidence of profitability.** Quantities marked (computed) were produced by running `apex_v2/dex.py`
this session; quotes marked (verified) were read from the paper's abstract/text this session.

## 1. What was verified about the observatory package
- Its 13 unit tests pass here (`PYTHONPATH=. python3 -m unittest discover -s tests`, 13/13, 0.08 s).
  They are mechanism tests on hand-built numbers. They test that the code does what it says, not that the economics hold.
- Its three cited papers exist and say what it claims: Oz et al. arXiv:2501.17335 (verified: "66.96%" inventory-based, 9 s vs 242 s bridge-based;
  242,535 arbitrages, 9 chains); He, Yang & Zhou arXiv:2507.08302 (gas-fee competition equilibrium, empirical positive inventory risk);
  Devorsetz & Herlihy arXiv:2601.19950 (rebalancing as convex optimisation).
- The same Oz et al. abstract also says (verified) **the five largest addresses execute more than half of all trades and one captures almost 40% of daily volume
  post-Dencun**. The observatory's research note keeps the pre-positioning finding and omits this concentration finding, which matters more for expected profit.
- `public_observation_status.json`/`public_observer.stdout.txt` show a DNS failure in that sandbox; no real observation exists. Kraken's public API did
  work from this session, so DNS is a sandbox limit, not a data limit.
- The integration note describes my files from a chat summary. It is partly wrong: `recorder.py` records raw Kraken v2 WebSocket messages (it does not
  serialise `report_row`), `replay.py` replays CEX books with fill-or-kill legs (it does not rebuild `MarketObservation`), `governor.py` is an EV gate (not a "governance
  boundary"). Adapters are needed; none exist.

## 2. Defects in the observatory design (ranked by effect on conclusions)

**D1. Linear profit model overstates AMM opportunities by 2-4 orders of magnitude (computed).**
`measurement_from_pair` sets `executable_value = min(cap, buy depth, sell depth)` and value = `notional x gross edge`. For a constant-product pool, profit is concave in size.
Running `dex.optimal_input` on two equal-depth WETH/USDC pools gives, to within 5%, **profit ~ (net price gap)^2 x depth / 8**, where *net gap = gap minus both pool fees* and *depth = USDC-side reserve of each pool* (TVL per pool = 2 x depth). The table below is **after fees** (5 + 30 bps). Fee-free, the same 40 bps gap at $10M depth gives $19.92 (formula g^2 x depth / 8 = $20); a single pool against an external reference price gives about TVL x g^2 / 8 ($39.9 for TVL $20M at g = 40 bps). An independent reviewer questioned the $0.30 figure; it reconciles exactly once fees are subtracted: 40 - 35 = 5 bps net, 0.0005^2 x 10M / 8 = $0.31.

| depth per pool | gap | fees | optimal size | actual profit | observatory-style `depth x (gap-fees)` |
|---|---|---|---|---|---|
| $10M | 40 bps | 5+30 bps | $1,220 | **$0.30** | $5,000 |
| $10M | 100 bps | 30+30 bps | $9,858 | **$19.45** | $40,000 |
| $10M | 300 bps | 30+30 bps | $58,612 | **$694** | $240,000 |
| $50M | 100 bps | 30+30 bps | $49,292 | **$97** | $200,000 |

Gas for a 2-hop cycle is about $3 at 3 gwei and about $0.02 at 0.02 gwei (computed with `dex.gas_cost`, ETH=$3,000). So a 100 bps gap in a $10M pool is worth about $19 against $3 of
gas at L1 gas levels and about $19 against $0.02 on a cheap L2, before any competition. The observatory's DexScreener path also treats `liquidity.usd / 2` as top-of-book depth at one price (`bid = ask = priceUsd`),
which is not an executable quote. The episode counts and "estimated net edge" it would emit from that path would be dominated by non-executable noise.
Fix: replace linear sizing with `optimal_input` over reserves (or tick liquidity for v3) for every DEX pair; keep the linear model only for CEX top-of-book.

**D2. No probability of winning.** `failed_attempt_probability` is a static input. The binding constraint in this market is the auction: concentration is extreme
(verified: top-5 > 50% of cross-chain trades; Wu et al. arXiv:2507.13023: 3 searchers took ~3/4 of CEX-DEX volume and value, profitability tied to builder integration).
The right multiplier is `P_win(bid | competitor rate)`, which `dex.DexGovernor` already estimates (Hawkes rate + empirical bid CDF, `P_win = exp(-lam (1-F(b)))`). The observatory should call it instead of a constant.

**D3. Identity by ticker symbol.** `public_observer.dexscreener` keeps the first 20 search results whose `baseToken.symbol == asset`. Many scam tokens copy symbols; honeypots and fee-on-transfer
tokens look cheap and "executable". A 500-asset universe needs canonical identity by (chain, contract address) with an allow-list/safety gate (simulate a buy+sell with `eth_call`, detect transfer tax,
owner mint/blacklist, LP lock). Papers: arXiv:2201.07220 (zero-dimensional scam detection), arXiv:2506.18398 (RPHunter).

**D4. Wrong time resolution.** Seconds-scale REST polling cannot see capturable episodes, which last roughly one to a few blocks. Persistent multi-second spreads are disproportionately
the non-capturable ones (illiquid, frictions, honeypots), so episode half-lives measured this way are biased toward junk. Needs per-block pool state (event logs or multicall at block cadence).
Exception worth testing: Wang et al. arXiv:2105.02784 report unexploited cyclic opportunities worth >1 ETH persisting on Uniswap V2, so some persistence is real.

**D5. `PortfolioStateRebalancer` is a hypothesis, not yet a mechanism, and its demo is circular.**
- The synthetic "turnover ratio 0.50" follows by construction: the baseline is a 4-leg round trip and the alternative is 2 legs. Retained-alpha 1.078 is the test fixture's arithmetic.
- Two swaps on two venues/chains are not atomic. Until both land you hold a naked X/Y bet; the same non-atomic risk the conventional cross-venue trade has.
- After the swaps, inventory is skewed (long X at A, long Y at B). The next opportunity may need the opposite skew, so inventory re-centering cost belongs in the model. It carries carrying cost
  (Oz et al.: opportunity frequency, bridging time and token depreciation decide inventory vs bridge).
- Per-leg alpha is computed from the other venue's price rather than marked to the global shadow price, so it is not a state-value calculation.
Better formulation: one convex program per decision epoch (Angeris et al. arXiv:2204.05238, which includes arbitrage as a special case) that maximises global value at shadow prices of the post-trade holdings, minus costs,
subject to AMM trading-function constraints and per-venue inventory limits, with a penalty for leaving the target inventory band. Then measure turnover/net-alpha against the pairwise baseline on **matched real episodes**.

**D6. Smaller:** `depth_weight` for Kraken ticker is 1.0 (no depth); `explicit_fee_bps=0` for aggregator rows; episode open/close thresholds use gross not net bps; capture evidence cannot distinguish "we/competitor took it" from "quote updated".

## 3. How big is the prize, and who gets it
- Loss-versus-rebalancing: for a constant-product pool under GBM the instantaneous arbitrage-extracted value is **(sigma^2 / 8) x pool value** (verified from the paper text, Milionis et al. arXiv:2208.06046).
  (computed) at sigma = 40% / 60% / 90% that is 2.0% / 4.5% / 10.1% of TVL per year: about $20M / $45M / $101M per $1B of TVL, **summed over all arbitrageurs, before pool fees and gas**.
  Fees and gas shrink it (Milionis, Moallemi, Roughgarden arXiv:2305.14604: fees scale arbitrage profit by the fraction of blocks with a profitable trade; faster blocks reduce LP loss).
- Competition takes most of it: Wu et al. (3 searchers ~75%), Oz et al. (top-5 > 50%, one ~40% post-Dencun), builder market concentration (arXiv:2412.18074, 2405.01329, 2410.12352).
  A new entrant without private order flow or builder integration should assume a small share of liquid-pair arbitrage and plan for roughly zero on L1 majors.
- A useful consequence: **extra mathematical sophistication does not create edge. Edge must come from where competition is thin, cost is low, or the information set differs.**

## 4. Where a small, careful entrant could plausibly make money (ranked by my judgment, not measured)
| Lane | Why it might work | Why it might not | Needs |
|---|---|---|---|
| Long-tail pools/tokens, same chain, atomic | generic bots skip them; larger gaps; unexploited opportunities documented (2105.02784) | scams/honeypots/taxes; thin depth caps profit at gap^2 x depth / 8 | token safety simulation, per-block state |
| Cheap L2s (Base/Optimism/Arbitrum) | gas about $0.02 so tiny profits clear costs; many pairs | latency race and revert-spam (arXiv:2506.01462: cyclic arbitrage >50% of gas on Base/Optimism in Q1 2025); thin profits (2406.02172, 2405.00138) | co-located node, sequencer-aware ordering (2306.02179, 2512.10094), cheap reverts |
| Cross-domain with pre-positioned inventory | 66.96% of cross-chain trades use inventory and settle in 9 s (verified) | inventory carry/depreciation; concentration | inventory controller, per-chain balances |
| Intent filling (UniswapX / CoW / 1inch Fusion) | competition is on price improvement, not a pure latency race; uses inventory (arXiv:2403.02525; solver routing arXiv:2510.21647) | thin margins; capital; protocol-specific solver onboarding | inventory, quoting engine |
| Backrunning user swaps through order-flow auctions | sealed-bid not latency; legitimate (refunds users) | most value goes to users/builders; saturated | searcher registration; see 2405.17944, 2408.02303 |
| CEX-DEX | large flow | dominated by integrated searchers (2507.13023); leg risk | not recommended |
| Triangle on a single CEX | done: no edge on Kraken, 12.5 min, max 1.52 bps fee-free | efficient | not recommended |
| Sandwiching / frontrunning users | profitable in the literature (2009.14021, 2101.05511) | harms counterparties; excluded on purpose | not pursued |

## 5. Design for increased expected profit (what to build, in order)
1. **Measure before modelling.** Per-block pool state and competitor activity on 2-3 candidate chains for 2-4 weeks (event logs / multicall; Kraken WS for the CEX leg). Store raw, replay deterministically.
2. **Counterfactual replay on that data.** For each block run the closed-form best cycle (`dex.best_opportunity`), subtract gas, then check from logs whether someone took it in that block and at what priority fee/bid.
   Fit lam and the bid CDF from real competitors (replace my Beta(5, 2.5) assumption). Output: realised-share-of-opportunities and EV per opportunity with bootstrap confidence intervals.
3. **Fix D1-D3 in the observatory** and make it call `DexGovernor.decide` for `P_win` and optimal bid; keep it shadow-only.
4. **Inventory controller** (the only genuinely new idea in the package): choose inventory per chain/venue by expected opportunity flow vs carry cost, with risk-constrained sizing (Busseti et al. arXiv:1603.06183). Formulate as the convex program in D5.
5. **Cost minimisation as a first-class objective:** bundle/private submission to avoid revert gas where supported, gas-optimised contracts, route selection by net-of-gas profit. Cost savings are the surest part of profit.
6. **Evaluation discipline before any money:** probability of backtest overfitting (Bailey et al. 2015), deflated Sharpe (2014), and a t > 3 hurdle after multiple testing (Harvey, Liu, Zhu). Only paper-trade if the lower confidence bound of EV per opportunity > 0 after realistic win rates.
7. **Gates:** (a) data shows positive net EV at realistic win rate; (b) a forked-chain simulation reproduces the realised results; (c) tiny-size live test with hard loss caps, only after (a) and (b), and only with the owner's explicit decision.

## 6. Housekeeping findings in related projects
- `APEX_exact_shadow 2/`: paper-only Alpaca harness; handoff reports the **only account-level P&L: calibration books -$14.27, minute-fractal variant -$5.47 (provisional)**, 286 original records with no verified dollar P&L. It samples 1 s REST quotes with no depth, so it cannot support arbitrage research; my recorder (full L2 + trades) fills that gap. No credentials are in files I read; credential handling stays with the owner.
- Duplicate project folders exist (`APEX_exact_shadow`, `APEX_exact_shadow 2`, a 1.07 GB `APEX System.zip`); worth cleaning to avoid running the wrong copy.

## 7. Verified references used here (all seen in search/fetch results this session)
Oz et al. 2501.17335; He, Yang, Zhou 2507.08302; Devorsetz & Herlihy 2601.19950; Milionis et al. 2208.06046 and 2305.14604; Wu et al. 2507.13023; Wang et al. 2105.02784;
Angeris et al. 2204.05238; Optimistic MEV on L2s 2506.01462; Cross-Rollup MEV 2406.02172; Rolling in the Shadows 2405.00138; Buying Time 2306.02179; Auctioning Time 2512.10094;
An Analysis of Intent-Based Markets 2403.02525; hybrid GA for CoW solvers 2510.21647; PROF 2408.02303; Remeasuring Arbitrage and Sandwich Attacks 2405.17944;
builder market 2412.18074, 2405.01329, 2410.12352; rug-pull detection 2201.07220, 2506.18398; Busseti et al. 1603.06183. See also `BIBLIOGRAPHY.md`.
