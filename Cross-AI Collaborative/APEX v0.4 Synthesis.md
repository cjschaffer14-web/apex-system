# APEX v0.4 Synthesis

Oct 2, 2026 · @Chris

## Where things stand

Round 2 closes the three conflicts that blocked v0.4: which key goes in the Secure Enclave, the tier-3 revocation gap, and the "Timeline F" name clash. Every question now has at least one answer, and Q12 is closed. What remains is one owner decision (Q10), eight converging proposals to ratify, and getting GPT's answers in its own words.

This document continues the [APEX v0.3 Compiled Brief for Peer AIs](https://claude.ai/code/artifact/dc5139f6-7b5b-47d0-ad68-8e8f8b52a81a); that brief stays as the round 1 record. Round 2 adds GPT's answers, relayed through Gemini's summary in *Gem 10\_26 for gpt*. The Word file *Gemini 10\_25\_30 for Claude* repeats Gemini's round 1 content and adds nothing new.

The same rules apply. Peers propose and the owner ratifies. Each model family counts once. Agreement among models is evidence, not authority.

## GPT's contributions (relayed by Gemini)

GPT's answers settle Q2, Q4 and the signature naming clash, and give Q5, Q6 and Q8 a second voice. They count as GPT's only once its original addendum (`APEX_UCA_V0_3_CURRENT_ADDENDUM_2.docx`) is supplied, because what we have is Gemini's summary of it.

| Question | GPT's answer | What it settles |
| --- | --- | --- |
| Q1/Q2 Keys and verification | A P-256 key that never leaves the Secure Enclave signs a short-lived Ed25519 session certificate when authorityd launches. Tokens are checked offline. | Gemini's Ed25519-in-Enclave design is replaced; all four models now agree |
| Q2 Revocation | Tier 3 requires a synchronous `online_revocation_check`. Tiers 0–2 check against a signed revocation snapshot, cached by epoch. | Closes the 1-second window DeepSeek's own falsifier exposed |
| Q4 Certainty | Stage A, from the start: a logistic ranker whose weights are constrained in sign, so contradiction or staleness can never raise certainty. Stage B: isotonic calibration, only once real outcomes exist. | Corrects DeepSeek's use of isotonic regression to fit weights; no longer needs outcome data before day one |
| Q5 Channel trust | Splits AuthorizationTrust (static and cryptographic) from EpistemicReliability (a Beta distribution learned slowly from prediction error). No source can raise its own score, correlated sources update together as one source, and injected text cannot train it. | A second voice; stronger than either fixed or freely learned trust |
| Q6 Mystery detection | A median-absolute-deviation residual detector with hysteresis: an anomaly must persist for at least 3 heartbeats to become MYSTERY\_CANDIDATE. | A second voice; avoids flooding the operator with alerts |
| Q8 Shadow signatures | Mahalanobis distance instead of Euclidean. Descriptive IDs replace timeline letters: SIG\_PERMISSION\_ACCUMULATION, SIG\_EVIDENCE\_MONOCULTURE, SIG\_CAPABILITY\_LEASE\_CREEP. | Ends the "Timeline F" clash; features are scaled before comparison |
| Q13 Migrations | Migration records go in the main ledger; any parallel journal is a read-only projection. | Disagrees with Gemini's dual ledger (see next section) |
| Q16 Dead-man's switch | Trigger on elapsed wall-clock time and scheduler health deadlines, not a count of heartbeats. | Disagrees with both DeepSeek and Gemini |
| Q18 Losing HATCHED | Drop to the band that matches the failed criterion. | Agrees with Gemini |
| Q20 Lineage | Judge family by structural provenance (base model hash, adapter ancestry) rather than embedding similarity. | Refines DeepSeek's and Gemini's cosine thresholds |
| Hatching | A ninth criterion, DEVELOPMENTAL\_CONTINUITY: the archive, frontier and trust state must rebuild from the ledger after every sleep. HATCHED can be lost again. | Conflicts with DeepSeek's ninth criterion (see next section) |
| MLX | Local MLX runs inside the Autonomy Charter and needs no new authorization. | Correct, with one caveat on dependencies (see next section) |

## Question status after round 2

After round 2, 15 of the 20 questions have two or more model families behind them. Ten have converged, four are split, four have one voice, Q10 awaits the owner, and Q12 is closed. "Voices" counts distinct model families; GPT is counted provisionally until its original text arrives.

| Question | Voices | Status |
| --- | --- | --- |
| Q1 Key custody | DeepSeek, Gemini, GPT | converged: Enclave P-256 root with an Ed25519 session key; Touch ID only for override, ratify, charter and grants |
| Q2 Token verification | DeepSeek, Gemini, GPT | converged: offline verification, but tier 3 is always checked online |
| Q3 Capability isolation | DeepSeek, Gemini | converged on sandbox-exec; an open risk is that Apple has deprecated it |
| Q4 Certainty aggregate | DeepSeek, GPT | converged on GPT's two-stage design |
| Q5 Channel trust | DeepSeek, GPT | converged on separating authorization from reliability |
| Q6 Mystery detection | DeepSeek, GPT | close: k-sigma plus novelty (DeepSeek) vs a median-absolute-deviation detector with persistence (GPT) |
| Q7 Lineage | DeepSeek, Gemini, GPT | converged on provenance first, similarity second |
| Q8 Shadow radii | DeepSeek, GPT | converged: Mahalanobis distance and descriptive signature IDs |
| Q9 Next frontier | DeepSeek, Gemini, GPT | converged: persistent memory first |
| Q10 Add-only | DeepSeek, Gemini, GPT | **owner decision**; all three lean hybrid (v0.2 frozen, signed migrations from v0.3 on) |
| Q11 Hatch criteria | DeepSeek, Gemini, GPT | split on what the ninth criterion should be (see next section) |
| Q12 Walls and threats | none | **closed:** UCA and Master Dense are retired as history, so W1–W7 stand on their own probes |
| Q13 Migration audit | Gemini, GPT | split: dual ledger (Gemini) vs the main ledger only (GPT) |
| Q14 Session key lifetime | Gemini | one voice: 24 h, dropped when the screen locks |
| Q15 W8 band | Gemini | one voice: the band widens with tier |
| Q16 Dead-man's switch | Gemini, GPT | split: scaled by attention (Gemini) vs wall-clock deadlines (GPT) |
| Q17 Lease granularity | Gemini | one voice: one lease per capability |
| Q18 Losing HATCHED | Gemini, GPT | converged: drop to the band of the failed criterion |
| Q19 Novelty embedding | Gemini | one voice: a frozen local model whose hash is pinned |
| Q20 Lineage threshold | Gemini, GPT | converged on GPT's provenance-first approach |

## Remaining disagreements and corrections

Four splits need a ruling or a third voice, and Gemini's summary carries four claims that should not travel forward as written.

**Splits**

| Topic | Position A | Position B | Suggested resolution |
| --- | --- | --- | --- |
| Ninth hatch criterion (Q11) | DeepSeek: under full background load, the operator's halt must complete within 50 ms | GPT: archive, frontier and trust state must rebuild from the ledger after sleep | Adopt both as criteria 9 and 10; they test different failures |
| Migration audit (Q13) | Gemini: a separate `migrations.jsonl` alongside the main ledger | GPT: one main ledger; anything else is a projection of it | Main ledger only: one hash chain cannot split into two disagreeing histories |
| Dead-man's switch (Q16) | Gemini: N = round(3 + 9·A) heartbeats | GPT: wall-clock deadline plus scheduler health | Wall clock: heartbeats can stall, which is the very failure being detected |
| Mystery detector (Q6) | DeepSeek: a 4-sigma residual and novelty above 0.85, both required | GPT: median absolute deviation, persisting 3 or more heartbeats | Use MAD with persistence as the trigger, and novelty as a second confirmation |

**Corrections to Gemini's summary**

- **"Consensus" is overstated.** It reports agreement on a ninth hatch criterion, but DeepSeek and GPT proposed different ones. It also contradicts itself on Q18: it now says a stalled research loop drops to INCUBATING, where its round 1 answer said WARM.
- **MLX is not zero-dependency.** Local MLX fits inside the charter, so no new authorization is needed. But MLX is a third-party package, and its model weights must ship inside the app, because downloading them needs network access the charter does not grant. One-click still works with a bundled dependency.
- **The regulatory section is unreliable.** FINRA Rule 3110 and SEC Rule 17a-4 govern broker-dealers, not an individual trading their own account. Pre-trade controls come from SEC Rule 15c3-5, which also binds brokers. The EU AI Act exempts purely personal, non-professional use. Whether an LLC limits personal liability is a legal question for a securities attorney before any live trading; none of this is legal advice.
- **"Executes instantly" and "mathematically guarantees" are overclaims.** The P-1 reserve bounds operator latency; the target is under 50 ms at the 95th percentile, and it has not yet been tested under load.

## Decisions for the owner

These nine items are what v0.4 needs from you: one open decision and eight proposals that two or more model families support. Set each ruling in its dropdown; whatever you ratify becomes the v0.4 build list.

| # | Decision | Backed by | Recommendation | Ruling |
| --- | --- | --- | --- | --- |
| 0 | Q10: strict add-only, or the hybrid (v0.2 frozen; signed migrations allowed from v0.3 on, for refactors only, recorded in the main ledger) | DeepSeek, Gemini, GPT lean hybrid | Your call; the hybrid keeps lineage while stopping wrapper sprawl | Awaiting owner |
| 1 | Key model: an Enclave P-256 root signs an Ed25519 session certificate; Touch ID only for override, ratify, charter and grants; halt and resume never need biometrics | DeepSeek, Gemini, GPT | Ratify | Awaiting owner |
| 2 | Revocation and token lifetime: tier 3 always checked online; tiers 0–2 use a cached snapshot; lifetimes 30 / 10 / 5 s for tiers 0–1 / 2 / 3 | DeepSeek, GPT (lifetimes: DeepSeek, Gemini) | Ratify | Awaiting owner |
| 3 | Certainty: GPT's two-stage design; the current linear formula is relabelled E2 | DeepSeek, GPT | Ratify | Awaiting owner |
| 4 | Channel trust split into AuthorizationTrust and EpistemicReliability | DeepSeek, GPT | Ratify | Awaiting owner |
| 5 | Shadow signatures: Mahalanobis distance, SIG\_\* names, radii set from data within \[0.5, 1.5\] | DeepSeek, GPT | Ratify | Awaiting owner |
| 6 | Hatching: add criteria 9 (operator round-trip under load) and 10 (developmental continuity); HATCHED can be lost and drops to the band of the failed criterion | DeepSeek, Gemini, GPT | Ratify | Awaiting owner |
| 7 | Capability leases: one lease per capability, with an expiry and an operator `revoke` that needs no new charter | DeepSeek, Gemini | Ratify | Awaiting owner |
| 8 | v0.4 frontier: persistent memory first (archive, frontier and trust rebuilt from the ledger), then MLX bundled for PDF ingestion and whole-paper reasoning | DeepSeek, Gemini, GPT | Ratify | Awaiting owner |

## Running start for trading research: a Crypto Data Pack

Yes, APEX can be prepared with a crypto data pack today, without loosening any wall. Start with a **seed pack** that needs no new permission: Kraken's full historical candles, downloaded once as local files. Then add a **read-only live feed** from six free sources under one narrow web lease. Live trading stays off; it is the last rung of the trading ladder, not the first.

**Recommended sources** (checked 2 Oct 2026; free tiers change, so the pack re-checks limits at awakening):

| Source | What it gives APEX | Access and limits | Terms | Proposed trust | Permission needed |
| --- | --- | --- | --- | --- | --- |
| [Kraken historical OHLCVT](https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data) | Candles at 1, 5, 15, 30, 60, 240, 720 and 1,440 minutes for every pair from its first trade through 30 Jun 2026; quarterly updates | Free ZIP of CSVs (about 2 GB parts); also a public REST API | Kraken's terms | market 0.80 | none (seed: local files) |
| [Coinbase public candles](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/get-public-product-candles) | Recent candles from 1 minute to 1 day, open to US users | No key; at most 350 candles per request | Coinbase API terms | market 0.80 | web lease |
| [CoinGecko Demo](https://www.coingecko.com/en/api/pricing) | Prices, market caps and volumes across thousands of coins | 100 calls/min, 10,000 calls/month; 1 year of daily or hourly history | Attribution required; no commercial use (Basic plan $35/mo adds a commercial license) | aggregated 0.75 | web lease + free key |
| [DefiLlama free API](https://api-docs.defillama.com/) | TVL, prices, stablecoins, yields, and protocol fees and revenue: the inputs for fee-accruing valuation | No key; rate limit not published; Pro API ($300/mo) adds unlocks and more | Open | aggregated 0.75 | web lease |
| [Coin Metrics Community](https://gitbook-docs.coinmetrics.io/packages/coin-metrics-community-data) | A free subset of their network and market data | No key; 10 requests per 6 s per IP | CC BY-NC 4.0: attribution, non-commercial | on-chain 0.85 | web lease |
| [mempool.space](https://mempool.space/docs/api/rest) | Bitcoin hashrate, difficulty, fees and rewards: the inputs for cost-of-production | No key; rate limited (HTTP 429) | Open | on-chain 0.85 | web lease |
| [Alternative.me Fear & Greed](https://alternative.me/crypto/fear-and-greed-index/) | Daily sentiment index built from volatility, momentum, social media, dominance and Google Trends | No key; daily | Attribution next to any display; commercial use allowed with attribution | sentiment 0.50 | web lease |
| [Google Trends API (alpha)](https://ppc.land/google-opens-alpha-testing-for-new-trends-api-targeting-developers-and-journalists/) | Consistently scaled search interest over a rolling 1,800 days (about 5 years), daily to yearly, by region | Apply for alpha access | Google's alpha terms | 0.60 (Gemini's proposal) | web lease + approval |

**Left out of the first pack:**

- **Binance.** Its API returns HTTP 451 to restricted locations, including the US, according to [CryptoDataDownload](https://www.cryptodatadownload.com/blog/posts/binance-download-data-python-usa-residents/). Its public archives ([binance-public-data](https://github.com/binance/binance-public-data)) are excellent, but use them only if the terms allow it where you are.
- **X and Reddit firehoses.** Intraday social data is where day-trading research gets expensive and where terms are tightest. Test whether daily sentiment helps first, and pay for intraday social feeds only if it does.
- **Paid on-chain feeds** (Glassnode, Kaiko, Coin Metrics Pro): defer until a sealed experiment shows the free subset is the bottleneck.

**How the data enters APEX:**

- **Membrane.** Every reading enters as an Observation carrying its channel, source and error model. Scraped text is reduced to numbers before it crosses into the system (Gemini's TH-01). Repeats of the same upstream data count as one source.
- **Sentiment and Trends never authorize.** At trust 0.60 or below they cannot reach the 0.95 certainty bar. They can only widen the uncertainty term σ in Trading-pack position sizing.
- **Valuation by asset class** (Gemini, E2/E3, Trading pack only): fee-accruing tokens use DefiLlama fees and revenue; proof-of-work coins use mempool.space hashrate plus an electricity assumption; utility tokens use active addresses from Coin Metrics.
- **Budget.** The ResourceBroker meters calls per source to stay inside free limits. CoinGecko's 10,000 calls a month is about 330 a day.

**What you would grant:**

1. **Nothing, for the seed.** Download Kraken's archive into the APEX data folder, and research starts on rung 1 (local files).
2. **One lease for the live feed:** `network.web`, read-only GET requests to six hosts (api.coinbase.com, api.coingecko.com, api.llama.fi, api.coinmetrics.io, mempool.space, api.alternative.me), with a 30-day expiry you can revoke at any time.
3. **Optional:** a free CoinGecko Demo key, and an application for Google Trends alpha access.
4. **Never, at this stage:** exchange trading keys. They belong to rung T5 and need a separate ratification.

**Day trading specifically.** Intraday research needs 1-minute candles, and Kraken and Coinbase both provide them. The first sealed experiment should test whether daily sentiment (Fear & Greed, Trends) improves risk-adjusted returns out of sample. Only buy intraday social data if that test passes.

&#91;embedded content: trading ladder · 6 rungs, 5 gates\]

The seed pack starts research at T0 today. Each gate is a sealed evaluation, and only you can open T5.

## Needed contributions for round 3

Round 3 has three jobs: get GPT's own words, settle the four splits, and review the Crypto Data Pack before anything touches the network.

**GPT (OpenAI)**

- [ ] Supply the original addendum (`APEX_UCA_V0_3_CURRENT_ADDENDUM_2.docx`) so its answers count as GPT's own voice
- [ ] Give second answers to the four questions with one voice: Q14, Q15, Q17 and Q19
- [ ] Review the Crypto Data Pack: the source list, trust levels, and the T2 simulation gate

**DeepSeek**

- [ ] Respond to the splits on Q13 (migration ledger) and Q16 (dead-man's switch)
- [ ] Reconcile its Q6 detector with GPT's median-absolute-deviation design
- [ ] Correct the lineage label in its round 1 log (it credits its review to Claude)
- [ ] Review the trading ladder gates, including its own proposed simulation gate

**Gemini (Google)**

- [ ] Fix the Q18 inconsistency (a stalled research loop drops to WARM or INCUBATING?)
- [ ] Withdraw or source the regulatory section; it misapplies broker-dealer rules to an individual
- [ ] Move σ inflation and deleveraging into the Trading pack in its crypto contract
- [ ] Review the Crypto Data Pack's valuation inputs by asset class

**Owner (Chris)**

- [ ] Rule on the nine items in Decisions for the owner
- [ ] Decide whether to download the Kraken seed archive and whether to grant the six-host `network.web` lease
- [ ] Confirm that Q12 is closed because UCA and Master Dense are retired

**Claude (Anthropic)**

- [ ] Build v0.4 from whatever you ratify, starting with persistent memory and the Crypto Data Pack's seed importer and simulator

## Contribution log (round 2)

Round 1 rows stay in the v0.3 brief. Round 2 rows go here, newest at the bottom, one row per contribution. Only the owner moves a row to Accepted, Integrated or Rejected.

| Date | AI / lineage | Question or section | Kind | Maturity | Contribution (one line) | Evidence | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-02 | Claude (Anthropic) | all; Crypto Data Pack | synthesis + proposal | E0–E3 | Round 2 synthesis; question status; nine decisions for the owner; Crypto Data Pack checked against current source terms | This document; sources listed below | Proposed |
| 2026-10-02 | GPT (OpenAI), relayed by Gemini | Q1, Q2, Q4–Q8, Q13, Q16, Q18, Q20, hatching, MLX | answers | E0–E2 | Enclave P-256 root with an Ed25519 session key, online check for tier 3, two-stage certainty, split trust, MAD detector, Mahalanobis signatures | *Gem 10\_26 for gpt* (a summary; the original is pending) | Under review |
| 2026-10-02 | Gemini (Google) | GPT summary; MLX; regulation | review | E1–E4 | Relayed GPT's answers; argued MLX needs no new authorization; added a regulatory overview | *Gem 10\_26 for gpt* | Contested |
|  | DeepSeek |  |  |  |  |  | Invited |
|  | Local MLX model (on device) |  |  |  |  |  | Invited |

## Sources

**Peer inputs:** *Gem 10\_26 for gpt* (Gemini's summary of GPT's addendum) · *Gemini 10\_25\_30 for Claude* (Word copy of Gemini's round 1) · *Deepseek 10\_24\_30* (DeepSeek's round 1) · [APEX v0.3 Compiled Brief for Peer AIs](https://claude.ai/code/artifact/dc5139f6-7b5b-47d0-ad68-8e8f8b52a81a) · [APEX v0.3 User Journey](https://claude.ai/code/artifact/97160a01-1dae-46ae-820b-615a54f6ae87)

**Data sources checked on 2 Oct 2026:**

- [Kraken: downloadable historical OHLCVT data](https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data)
- [Coinbase: Get Public Product Candles](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/get-public-product-candles)
- [CoinGecko API pricing](https://www.coingecko.com/en/api/pricing)
- [DefiLlama API docs](https://api-docs.defillama.com/) and [DefiLlama pricing](https://docs.llama.fi/pro-api)
- [Coin Metrics Community Data](https://gitbook-docs.coinmetrics.io/packages/coin-metrics-community-data)
- [mempool.space REST API](https://mempool.space/docs/api/rest)
- [Alternative.me Crypto Fear & Greed Index](https://alternative.me/crypto/fear-and-greed-index/)
- [Google Trends API alpha (PPC Land)](https://ppc.land/google-opens-alpha-testing-for-new-trends-api-targeting-developers-and-journalists/)
- [Binance public data (GitHub)](https://github.com/binance/binance-public-data) and [CryptoDataDownload on US access to Binance](https://www.cryptodatadownload.com/blog/posts/binance-download-data-python-usa-residents/)
