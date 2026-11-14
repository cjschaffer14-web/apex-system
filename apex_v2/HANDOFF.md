# apex_v2 hand-off

Status date: 2026-10-07. Everything here is research code. **Nothing signs or sends a transaction or order**, and no credentials are used.

## What is in the package
| File | Purpose |
|---|---|
| `core.py` | Corrected cycle simulator (explicit buy/sell legs, unit-checked chain, limit-price walks). Replaces the execution math of the original DeepSeek screener. |
| `governor.py` | `PredictiveGovernor`: EV gate + hard vetoes; `HawkesIntensity` (exponential kernel, O(n)); `ToxicityModel` (logistic, `fit()`). |
| `backtest.py` | **Synthetic** CEX triangular backtest: naive vs 5 bps threshold vs governed. |
| `recorder.py` | Records raw Kraken v2 WebSocket (book depth 10, trades, heartbeats) with local receive timestamps. |
| `replay.py` | Replays a recording: best triangle cycle per decision point; fill-or-kill legs at t + k*latency; unwinds on failure. |
| `dex.py`, `dex_backtest.py` | Closed-form optimal sizing for cyclic CPMM arbitrage, Poisson priority-auction EV and bid optimiser, **synthetic** DEX backtest. |
| `test_apex.py`, `test_dex.py` | 20 unit tests, all passing at last run. |
| `BIBLIOGRAPHY.md` | 38 verified papers mapped to modules. Not 100. |

Run from the folder that contains `apex_v2/`:
```
python3 -m unittest apex_v2.test_apex apex_v2.test_dex
python3 -m apex_v2.backtest --trials 20000 --seeds 5 [--signal 0] [--fee 0.0026]
python3 -m apex_v2.dex_backtest --blocks 60000 --seeds 3 --scenario l1|l2
python3 -m apex_v2.recorder --seconds 900 --out data/kraken.log      # needs: pip install websocket-client
python3 -m apex_v2.replay data/kraken.log --fee 0.0026 --latency-ms 40
```

## Added after first hand-off: DEX data foundation (P0) and design review
- `DESIGN_REVIEW.md`: review of the Global Arbitrage Observatory package + plan. Key finding: the observatory's `depth x spread` profit model overstates AMM profit by 2-4 orders of magnitude; exact size/profit for two CPMM pools is ~ (net gap)^2 x depth / 8 (net of both fees).
- `dexdata/` (read-only; no keys, no signing; `rpc.py` refuses any non-read method):
  - `collect.py`: per-block archive of Uniswap-V2-style WETH/USDC pools on Base: block header, exact reserves (eth_call at that block), Swap/Sync logs, tx sender/gas/status, multi-pool tx flag, cross-RPC block-hash check. Pools are discovered from factories and verified on-chain (token symbols), not hard-coded.
  - `univ2.py`: exact integer getAmountOut, K-invariant check, exact integer optimal cycle sizing.
  - `archive.py`: acceptance audit (contiguity, parent-hash chain, state continuity, exact swap replay with fee inference) and per-block opportunity/competition measurement.
  - `test_dexdata.py`: 8 offline tests. Whole suite: 28 tests passing.
- Run: `python3 -m apex_v2.dexdata.collect --chain base --seconds 900 --out data/base_v2.jsonl` then `python3 -m apex_v2.dexdata.archive data/base_v2.jsonl`.
- Limits: v2-style pools only (no v3 tick traversal, Curve, Balancer yet); L2 execution gas only (Base L1 data fee not modelled); one chain; public RPCs are rate-limited (collector rotates endpoints and records gaps rather than hiding them).

## First real DEX measurement (Base, 2026-10-07, ~15 min, 449 of 586 blocks captured)
- **Acceptance audit passed on what was captured:** 37/37 Uniswap-v2 swaps reproduced exactly (K invariant + exact getAmountOut, fee inferred 997/1000); BaseSwap fee inferred 9975/10000 from a single swap (weak evidence); state continuity 1293/1293; 0 parent-hash breaks; 0 cross-RPC block-hash disagreements.
- **Completeness is NOT perfect:** 137 of 586 blocks (23%) are missing because the free public RPCs rate-limit; gaps are recorded, not hidden. A paid/own node is needed for a real study.
- **Null result:** across Uniswap v2 / SushiSwap v2 / BaseSwap WETH/USDC, the pairwise price gaps never exceeded the fee hurdle (max 44.5 bps vs 55-60 bps), so 0 cycle opportunities and 0 multi-pool transactions in 449 blocks. Pools are tiny: USDC-side $650k / $1.8k (stale) / $10.9k; swaps are dust (median $1, max $60, 39 swaps, 8 senders). Base gas is negligible (base fee ~0.005 gwei, ~$0.004 for a 250k-gas cycle), so gas is not the barrier; fees and depth are.
- **Implication:** the arbitrage-relevant liquidity on Base is elsewhere (v3-style concentrated pools, Aerodrome). Needed next: v3 tick-traversal replay, Aerodrome volatile/stable pool math, and liquidity-weighted pool admission (TVL/volume thresholds) instead of "every pool a factory returns".

## Results, with how much to trust each
1. **Synthetic CEX backtest** (`backtest.py`): governed beats naive when the simulator's signals are informative; with `--signal 0` the governor is ~flat (+$388, t=1.3). Shows mechanics only. The 88% win rate comes from how I built the signals.
2. **Synthetic DEX backtest** (`dex_backtest.py`): governed bundle with EV-optimal bid beats fixed-bid and naive policies on the simulated L1 scenario ($138k vs $42k-98k per 3 seeds), ties naive on the L2 scenario. **Absolute dollar levels are artefacts** (too many opportunities, too generous; real arbitrage is competed to near zero). Only the relative ordering of bidding policies is informative, and it depends on my assumed competitor-bid distribution (Beta(5, 2.5)).
3. **Real data replay** (`replay.py`, 12.5 min of Kraken BTC/USD, ETH/USD, ETH/BTC): after fixing a book-reconstruction bug, the fee-free best triangle edge was median -0.46 bps, p99 1.05 bps, max 1.52 bps. At 26 bps and 4 bps per leg there were **zero** profitable candidates; at 0 bps, 267 naive trades earned +$1.50 total (t=1.4, not significant). **On this venue, in this window, the triangle is efficient and nothing is profitable at any real fee tier.** 12.5 minutes is a very small sample.

## Known bug history (read before trusting any replay number)
`replay.py` originally kept stale order-book levels beyond depth 10 in its internal dict; they resurfaced and left the books crossed in 99% of states, which produced fake edges of 15-30 bps and 98-100% win rates. Fixed by truncating the stored book to the subscribed depth and removing opposite-side levels a fresh quote crosses. **A regression test for crossed books has not been written yet.** Kraken's book checksum is not verified; adding it would be the proper guard.

## Not done / next steps (in priority order)
1. Add a crossed-book regression test and Kraken CRC32 checksum verification to `replay.py`.
2. Record far longer (days) and across venues; the replay needs more than one venue to test cross-exchange arbitrage and to give `ref_divergence_bps` a real value (it is 0 now).
3. Fit `ToxicityModel` on ex-post labels; the replay uses unfitted prior weights.
4. Implement PBO / deflated Sharpe (papers 36-37 in the bibliography) before tuning thresholds on real data.
5. DEX: replace the synthetic market with replayed on-chain reserves; model L2 speculative-spam (failed-tx cost) per paper 15; fit competitor bids to observed data.
6. Finish the literature pass: ~60 of the requested 100 papers are not yet searched.

## Related projects (not modified)
- `/Users/chris/Downloads/APEX_exact_shadow 2/`: separate forward shadow-test harness with Alpaca *paper* trading and 1-second quote sampling (no L2 depth, no arbitrage execution). Contains paper API key handling; nothing in `apex_v2` reads or uses it.
- `/Users/chris/Downloads/APEX System/`: the larger APEX project (v1.0 stage 1/2, specs, sqlite databases). `apex_v2/` is new and independent of it.

## Caveats that apply to everything
No result here is evidence of live profitability. Fees, latency, queue position, competitors and market impact are modelled or approximated. Do not trade real money on these numbers.

## Profit-first continuation — 2026-10-07

See `PROFIT_FIRST_HANDOFF.md` and `PROFIT_ENGINE_STATUS.json` for saved implementation and actual finite Mac validation. No continuous launch or live orders.
