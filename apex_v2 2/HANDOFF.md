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
