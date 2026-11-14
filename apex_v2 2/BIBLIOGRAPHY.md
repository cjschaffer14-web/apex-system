# apex_v2 bibliography (verified by web search this session)

**38 papers confirmed, not 100.** Each entry below was found in a search result; arXiv ids / venues
are given only where the result showed them. Nothing is cited from memory. Authors are omitted where
the result did not show them. The remaining ~60 (market making, optimal execution, LOB deep learning,
perp funding, EIP-1559, regime detection, RL execution) were not searched yet.

## DEX arbitrage / MEV  -> `dex.py`, `dex_backtest.py`
1. Wang, Chen, Wu, Zhou, Deng, Wattenhofer. Cyclic Arbitrage in Decentralized Exchange Markets. arXiv:2105.02784. (cycle profitability, atomic implementation)
2. Daian, Goldfeder, Kell, Li, Zhao, Bentov, Breidenbach, Juels. Flash Boys 2.0. arXiv:1904.05234. (priority gas auctions)
3. Qin, Zhou, Gervais. Quantifying Blockchain Extractable Value: How dark is the forest? arXiv:2101.05511. (IEEE S&P 2022)
4. Zhou, Qin, Torres, Le, Gervais. High-Frequency Trading on Decentralized On-Chain Exchanges. arXiv:2009.14021. (read for defence; sandwiching is not implemented)
5. Qin, Zhou, Livshits, Gervais. Attacking the DeFi Ecosystem with Flash Loans for Fun and Profit. arXiv:2003.03810. (atomicity raises arbitrage revenue)
6. A Flash(bot) in the Pan: Measuring MEV in Private Pools. arXiv:2206.04185. (private bundles)
7. Remeasuring the Arbitrage and Sandwich Attacks of MEV in Ethereum. arXiv:2405.17944.
8. Time to Bribe: Measuring Block Construction Market. arXiv:2305.16468. (builder bids)
9. From Competition to Centralization. arXiv:2412.18074. (builder concentration)
10. Decentralization of Ethereum's Builder Market. arXiv:2405.01329.
11. Private Order Flows and Builder Bidding Dynamics. arXiv:2410.12352. (private order flow = block value)
12. Wu, Sui, Thiery, Pai. Measuring CEX-DEX Extracted Value and Searcher Profitability. arXiv:2507.13023. (3 searchers take ~75%)
13. Cross-Rollup MEV: Non-Atomic Arbitrage Across L2 Blockchains. arXiv:2406.02172.
14. Rolling in the Shadows: Analyzing the Extraction of MEV Across Layer-2 Rollups. arXiv:2405.00138.
15. Optimistic MEV in Ethereum Layer 2s. arXiv:2506.01462 (AFT 2025). **Implication not yet in code:** on L2s cyclic arbitrage is mostly *speculative spam that may revert*, so the failed-tx cost (`fail_gas_frac`, public path) matters more than in the bundle model.

## AMM theory  -> `dex.py` closed-form sizing
16. Angeris, Evans, Chitra, Boyd. Optimal Routing for Constant Function Market Makers. arXiv:2204.05238 (EC'22).
17. Angeris, Kao, Chiang, Noyes, Chitra. An analysis of Uniswap markets. arXiv:1911.03380.
18. Milionis, Moallemi, Roughgarden, Zhang. Automated Market Making and Loss-Versus-Rebalancing. arXiv:2208.06046.
19. Impermanent Loss in Uniswap v3. arXiv:2111.09192.
20. Risks and Returns of Uniswap V3 Liquidity Providers. arXiv:2205.08904. (LPs lose on average: do not do passive LP)

## CEX triangular arbitrage / toxicity / latency  -> `core.py`, `governor.py`, `replay.py`
21. Foucault, Kozhan, Tham. Toxic Arbitrage. Review of Financial Studies 30(4), 2017.
22. Ito, Yamada, Takayasu, Takayasu. Execution Risk and Arbitrage Opportunities in the FX Markets. NBER w26706.
23. Free Lunch! Arbitrage Opportunities in the Foreign Exchange Markets. NBER w18541.
24. The Mirage of Triangular Arbitrage. arXiv:0812.0913.
25. Budish, Cramton, Shim. The High-Frequency Trading Arms Race: Frequent Batch Auctions as a Market Design Response. (QJE 2015)
26. Empirical Analysis of Indirect Internal Conversions in Cryptocurrency Exchanges. arXiv:2002.12274.
27. Who are the arbitrageurs? Empirical evidence from Bitcoin traders in the Mt. Gox exchange platform. arXiv:2109.10958.
28. Building Trust Takes Time: Limits to Arbitrage for Blockchain-Based Assets. Review of Finance.
29. Optimal Execution with Dynamic Order Flow Imbalance. arXiv:1409.2618.
30. Easley, Lopez de Prado, O'Hara. From PIN to VPIN. (order-flow toxicity; the `ofi` input is a crude stand-in)

## Hawkes / order flow  -> `governor.HawkesIntensity`
31. Bacry, Mastromatteo, Muzy. Hawkes processes in finance. arXiv:1502.04592.
32. Compound Hawkes Processes in Limit Order Books. arXiv:1712.03106.
33. Queue-reactive Hawkes models for the order flow. arXiv:1901.08938.
34. Diffusive Limit of Hawkes Driven Order Book Dynamics With Liquidity Migration. arXiv:2511.18117.
35. State-dependent Hawkes processes and their application to limit order book modelling (Imperial College).

## Evaluation honesty / sizing  -> how to read `backtest.py` results
36. Bailey, Borwein, Lopez de Prado, Zhu. The Probability of Backtest Overfitting. J. Computational Finance 2015. (CSCV; **not yet implemented here**: needed before trusting any tuned threshold)
37. Bailey, Lopez de Prado. The Deflated Sharpe Ratio. J. Portfolio Management 2014. (not yet implemented)
38. Harvey, Liu, Zhu. ...and the Cross-Section of Expected Returns. NBER w20592. (t > 3.0 hurdle after multiple testing; the t-stats printed by `backtest.py` should be judged against this, and I tried ~3 strategies x 5 thresholds)
39. Busseti, Ryu, Boyd. Risk-Constrained Kelly Gambling. arXiv:1603.06183. (relevant to APEX's Kelly sizing)

## Findings that should change the code (not yet done)
- Paper 15: model reverting speculative transactions on L2s (public path), not only private bundles.
- Papers 9-12: builder/searcher concentration implies the bundle `b50`/competitor-bid model should be fitted to observed builder data, not Beta(5, 2.5).
- Papers 36-38: add PBO / deflated Sharpe to `backtest.py` before tuning anything on real data.
