# Owner Ideas, 3 October 2026: Results

Five questions came in on 3 October:

1. Does BTC react at special price levels? The candidates were round numbers and their golden-ratio multiples (10k → 16.18k, 20k → 32.4k, 40k → 64.7k, 100k → 161.8k), and powers of 1.618, 1.1618 and other constants.
2. Can a simple rule make a positive return before deployment?
3. Do media and whale activity carry signal?
4. Is the pasted research, with its links, a better model?
5. What does "a single deployment that operates across nodes" mean for the build?

The code and raw results are in `research/owner_ideas_2026-10-03/`. Every test was written down before it was run, and every idea is now an owner hypothesis that APEX re-tests itself (`hypotheses/owner_2026-10-03.json`). Nothing here is financial advice.

## 1. Price levels: no special levels

**Data and test design.**
* Data: Coinbase BTC-USD hourly closes, 2017 to 2 October 2026 (85,437 hours).
* Touch: price comes within 0.5% of a level after being at least 1.5% away.
* Bounce: price turns back to 1.5% on the side it came from within 72 hours, rather than breaking through.
* Volatility: how much price moves while it sits at a level.

**The control.** The same grid is shifted to 400 random positions (in the code, the "placebos"). Each copy keeps the same number of levels and the same spacing, so an ordinary property of price movement shows up in every copy, and only the true positions could show something more. A level family counts only if it beats the shifted copies in both periods (2017–21 and 2022–26), in the same direction.

z below is how far the true levels sit from the shifted copies, in standard deviations. Roughly 2 or more in both periods is needed.

| Level family | Touches 2017–21 / 2022–26 | Bounce z | Volatility z |
|---|---|---|---|
| Round 1-2-5 (10k, 20k, 50k, 100k) | 121 / 68 | −0.1 / −1.2 | +0.1 / +2.0 |
| Multiples of 10k | 137 / 300 | −0.6 / +0.6 | −0.5 / +1.2 |
| Round × golden ratio (16.18k, 32.4k, 64.7k, 161.8k) | 203 / 88 | −1.2 / −0.8 | −0.6 / −0.9 |
| Powers of 1.618 | 173 / 138 | +0.9 / −1.2 | −1.3 / −0.9 |
| Powers of 1.1618 (as written) | 659 / 354 | −0.3 / −1.5 | +0.1 / −0.3 |
| Powers of e | 111 / 54 | +0.5 / +1.2 | −0.5 / +0.5 |
| Powers of pi | 70 / 74 | +1.0 / +0.9 | −0.4 / −0.1 |

**Result:** none of the families is supported. Price reacts at these levels the same way it reacts at randomly placed levels with the same spacing.

* **Could the test have found an effect?** Yes. A planted effect that raises the bounce rate from about 53% to about 62% was detected in 8 of 10 simulated 4.5-year periods. A stronger one (about 69%) was detected in 10 of 10. An effect smaller than that could still be hiding (`levels_power.py`).
* **The one near-miss:** price moved more than usual near 10k, 20k, 50k and 100k after 2022 (z +2.0), but not before. It's worth watching because it has a known cause. In currency markets, take-profit and stop-loss orders cluster at round numbers, so prices reverse or accelerate there more often (Osler, 2000 and 2003). That mechanism comes from where people put their orders; nothing comparable has been documented for the golden ratio.
* **A note on terms:** the golden ratio is algebraic (it solves x² = x + 1), not transcendental. Both kinds were tested; e and pi are the transcendental constants here.

## 2. Simple rules (Occam's razor): positive returns, but not more than holding

**Set-up.**
* Data: Coinbase daily closes, 2016 to 2026.
* Spot costs: 85 bps on every change of position.
* Long-only, no leverage.
* Each rule was fixed in advance with its textbook settings.

| Rule (85 bps) | Annual return | Sharpe | Worst drawdown | 2022–26 annual return | 2022–26 drawdown | Last 12 months |
|---|---|---|---|---|---|---|
| Hold BTC | +65.8% | 1.09 | 84% | +13.5% | 67% | −29.9% |
| BTC above its 200-day average | +54.6% | 1.09 | 72% | +23.9% | 37% | −4.7% |
| … and sized to 50% volatility (the **core book**, with a 5-point trade band) | +45.1% | 1.15 | 58% | +22.9% | 33% | −4.2% |
| BTC above its 100-day average | +55.1% | 1.12 | 70% | +11.7% | 44% | +0.3% |
| BTC above its 50-day average | +57.3% | 1.18 | 66% | +3.2% | 60% | −9.4% |
| 28-day momentum | +35.8% | 0.87 | 81% | −6.1% | 61% | −17.3% |
| 90-day momentum | +49.4% | 1.02 | 69% | +5.1% | 46% | −20.0% |
| Volatility-sized hold | +46.7% | 1.02 | 74% | +12.2% | 64% | −30.6% |
| Altcoin basket above their 200-day averages | −15.1% | 0.11 | 99% | −48.1% | 97% | −66.8% |

**What this shows:**
* **Holding BTC was positive over ten years, beyond luck.** Its deflated Sharpe is 0.93–0.95, counting all 30 trials so far. That return is the asset's own rise, not an edge.
* **The trend filter doesn't beat holding on return.** On risk-adjusted return it is a coin flip: the bootstrap probability that its Sharpe is higher is 0.48 for the 200-day rule and 0.64 for the core book.
* **It reliably cuts the deep losses.**
  * With volatility sizing, the probability of a smaller worst drawdown is 0.96–0.97.
  * Unchanged on ETH, the same rule cut ETH's worst drawdown from 94% to 47% (probability 1.00).
  * Over the last 12 months, BTC fell 30% and the core book lost 4%.
* **The altcoin basket lost mostly to costs.** Its membership changes often, adding up to about 40 times the portfolio in trading each year. Even before costs, altcoins as a group have fallen since 2022 (about −11% a year). That fits the owner's point that BTC is the market's base.

**For the single deployment:** a simple, ten-year-tested candidate is now available, the BTC core trend book. Choosing it is a decision about holding BTC with a brake on drawdowns; nobody can prove it has an edge. It is built as a third paper book. It trades only once the owner adds it to the paper lease, because adding a book widens a lease.

## 3. Media and whale data: they say more about volatility than about direction

**Set-up.**
* Media: Fear & Greed, Wikipedia views, and GDELT news volume and tone.
* Whale proxies, from the Coin Metrics Community API: exchange inflows and outflows, exchange balances, MVRV and active addresses.
* Lag: one day.
* Sampling: non-overlapping weeks and months.
* Bar: 27 tests in total, so the Bonferroni bar is |z| ≥ 3.11 on the full sample, plus |z| ≥ 2 in both periods.

* **Returns: nothing passed.** The closest result was coins flowing *into* exchanges preceding weaker weeks: z −2.5 before 2022, −1.1 since, −2.6 in total. It points the right way for "whales move coins to exchanges to sell", but it fades after 2022.
* **Volatility, once today's own volatility is accounted for:**
  * Wikipedia attention surprises and exchange inflows still predict next week's swings (full-sample z +3.4 and +3.4). Both are strong before 2022 and the same sign but weaker after.
  * Extreme fear's apparent volatility signal disappears once today's volatility is known, because fear follows the crash.
* **Group chats near whales** (Telegram, Discord, X) are not reachable for free. Each needs an account or a paid API, so each is an owner decision.

**Use:** these series go into risk sizing (how much to hold), not direction (what to buy). That matches the v0.5 finding. APEX now downloads them weekly and tests the owner's media and whale hypotheses itself.

## 4. The pasted research and links

**The five-layer outline** (data → features → prediction → portfolio and risk → execution) matches APEX's design.
* **APEX already has:**
  * purged, time-ordered validation;
  * combinatorial overfitting checks (CSCV);
  * the deflated Sharpe;
  * pessimistic costs;
  * risk kept separate from prediction (authorityd).
* **Worth trying next:**
  * **triple-barrier labels and meta-labelling,** where a second model decides whether to act on the first model's signal and how much to size it;
  * **a regime switch** (a hidden Markov model).
  * Each is a counted trial.
* **Not relevant at this size:** execution algorithms (VWAP and IS) and order-book microstructure features, which need paid tick data.
* **Kelly sizing:** only fractional, if ever.

| Link | What it is | Verdict |
|---|---|---|
| Chainstack SmolLM3 MLX tutorial | A 3B local model makes buy/sell calls on Uniswap (Base). No results; "NOT FOR PRODUCTION". | Skip |
| chainstacklabs/web3-ai-trading-agent | Code for the tutorial: a GAN, a LoRA-distilled Qwen2.5-3B and a DQN reinforcement-learning agent. No results. | Skip; the idea of a model that outputs one of a few fixed words is reusable |
| humanplane/cross-market-state-fusion | Binance futures state used to trade Polymarket's 15-minute crypto markets with an on-device MLX reinforcement-learning agent. Claims about 2,500% over one 10-hour paper session, with fills at mid-price, no fees and no held-out test. | Borrow the hypothesis (a fast market leads a slow one); ignore the numbers |
| LiquidAI LFM2.5-1.2B MLX 8-bit | A small official general model. Custom licence. | Optional helper for tagging news text; it doesn't make trading decisions |
| "Chaos-Agent … Qwen3.8-27B … OBLITERATED" | An individual's fine-tune of a version with refusals removed, trained mostly on security and pentesting data. | Skip: unvetted, guardrails removed, nothing to do with markets; APEX already runs Qwen3.8-27B from mlx-community |
| Chainstack GAN synthetic data | WGAN-GP swap data for fine-tuning. | Skip for training; it can teach invented patterns |

**Do we have the top model?** For language, yes: the pinned Qwen3.5-9B and Qwen3.8-27B. For trading, no trading model has demonstrated an edge yet, either here or in any of the links. The fastest legitimate progress comes from more independent, weak signals and honest counting, not from a bigger model.

## 5. One deployment, many nodes

As built, one pinned version, the procedure and its code, deploys once. Its parameters keep updating inside that procedure: refits, the volatility estimate and the trend state. Other nodes (phone, cloud, peer AIs) observe and propose. Only the Mac's authority process holds the exchange key and signs orders. A change to the procedure itself is a new version and needs a new owner ratification.

## Sources

* Osler, C. (2000), *Support for Resistance: Technical Analysis and Intraday Exchange Rates*, FRBNY Economic Policy Review: https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf
* Osler, C. (2003), *Currency Orders and Exchange Rate Dynamics: An Explanation for the Predictive Success of Technical Analysis*, Journal of Finance: https://onlinelibrary.wiley.com/doi/abs/10.1111/1540-6261.00588
* Coin Metrics Community API catalog (checked 3 Oct 2026): https://community-api.coinmetrics.io/v4/catalog-v2/asset-metrics?assets=btc
* The six links reviewed are listed in the table above, as provided by the owner.
