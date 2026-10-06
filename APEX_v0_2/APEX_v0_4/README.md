# APEX v0.2 — Executable Core + Full Abstraction Registry

This package converts the current APEX proposal into a small runnable organism while preserving the larger conceptual architecture as typed contracts and documented mathematical systems.

## Core topology

World → Observation → EvidenceBundle → Claim/Hypothesis → Proposal → Authority → ExecutionToken → Actuation → Outcome → LearningCandidate → sealed evaluation → champion/rollback.

There is no direct Proposal → Actuation edge.

## What is implemented

- Canonical objects and event-sourced ledger
- Typed model graph projection
- Separate Authority semantics: constitution, risk/constraint checks, capability broker
- Token-gated actuation runtime
- Adaptive deliberation tiers
- P0–P3 resource scheduler
- Sealed candidate/champion/rollback evaluation workflow
- Research and Trading DomainPack interfaces
- Cross-AI protocol envelopes and consensus-as-evidence semantics
- Registry for the 15 v9.1 layers and the older/higher abstractions
- Mathematical systems library containing executable reference formulas where appropriate
- Maturity tags distinguishing established engineering mechanisms from research and philosophical abstractions

## What is intentionally NOT treated as production-complete

- Secure Enclave integration
- Rust/PyO3 authority microkernel
- WebAssembly isolation
- cryptographic production key custody
- external cloud anchoring
- live brokerage execution
- continuous camera/microphone capture
- full MLX model runtime
- formal theorem proving for arbitrary rules

Those remain extension points.

## Run

```bash
python run.py
python -m unittest discover -s tests
```

No third-party dependencies are required.

---

# APEX v0.3 — The Incubating Organism (appended; v0.2 text above is unchanged)

```bash
python awaken.py                       # one-click awakening: walls, governed path, heartbeat, hatch readiness
python awaken.py --ticks 3 --view tower
python -m unittest discover -s tests   # 43 tests (5 v0.2 + 38 v0.3)
```

What changed: a separate **authorityd** process (keys never leave it), **VerifiedRuntime** (signature, scope, budget, manifest), **broker split** and **P-1 reserved tier**, the **Seven Walls** as invariants checked on every awakening, **operator sovereignty** (halt, override, ratify, rectify) with **owner reachability**, the **Autonomy Charter** and **fork-on-missing-capability**, the **developmental Egg** (warmth, bands, heartbeat, sleep, frontier, hatch readiness), a **Research Pack vertical slice** that improves itself, executable **UCA-2** consensus (lineages count once), **Block X** as a fail-closed mechanism, and E4 philosophy kept in `philosophy/`.

All v0.2 code is byte-identical and v0.2 text is only appended to (`MANIFEST_V0_2.json`, enforced by a test). See `APEX_V0_3_IMPLEMENTATION_SPEC.md`.

---

# APEX v0.4 — Persistent, Leased, Ready to Research (appended; text above is unchanged)

```bash
python awaken_v04.py                                   # walls, heartbeats, sleep, morning report
python awaken_v04.py --say "turn on the microphone for 2 hours"   # voice or any flexible owner input
python awaken_v04.py --hatch                           # all ten hatch criteria
python3 setup_models.py                                # once: install and verify the local models
python -m unittest discover -s tests                   # 88 tests (5 v0.2 + 38 v0.3 + 45 v0.4)
```

Built from the owner's 2 Oct 2026 rulings on the *APEX v0.4 Synthesis*:

* **Mathematics:** two-stage certainty with bounded calibration uplift; Beta reliability that can only cap channel trust; Mahalanobis `SIG_*` signatures; a MAD mystery detector with persistence.
* **authorityd v0.4:** capability leases, pre-approvals with conditions, and token lifetimes of 30/10/5 s by tier.
* **Owner channel:** a key hierarchy and presence policy. Sensors are switched on and off **by voice or typed text**, and a halt switches them off.
* **Organism:** a wall-clock dead-man's switch. **Persistent memory** rebuilt from the ledger (hatch criterion 10). Operator round-trip under load (criterion 9). Rolling HATCHED with demotion to the band of the failed criterion. A read-only self-model. Hash-pinned model weights.
* **Crypto Data Pack:** a Kraken seed importer, the T0 gate, a GET-only allowlisted fetch organ, and a walk-forward simulator with the T2 gate. Live trading stays off: exchange keys belong to rung T5 only.

**Start trading research:** download Kraken's OHLCVT archive into `data/kraken/`. The six-host read-only web lease you pre-approved opens by itself once T0 passes. Importing hourly data for every pair takes a while; use `--pairs XBTUSD,ETHUSD` to focus.

**Coin Metrics:** the web lease uses its free Community API host, `community-api.coinmetrics.io` (pre-approval revision 2).

All v0.3 code is byte-identical (`MANIFEST_V0_3.json`, enforced by a test). See `APEX_V0_4_IMPLEMENTATION_SPEC.md`.

**v0.4.1 (same day):**

* Coin Metrics now uses its free Community host.
* The trading simulator is fixed, and the T2 gate is audited in `docs/T2_GATE_AUDIT.md`. As built in v0.4.0, the gate passed pure noise 40% of the time; a proposed gate passed 0%.
* Local models run. Run `python3 setup_models.py` once on the Mac. It installs and verifies Qwen3.5-9B (fast) and Qwen3.8-27B (deep, idle-only); APEX then uses them by itself.
* 88 tests.

---

# APEX v0.5 — Evidence, Paper Trading, Your Hypotheses (appended; text above is unchanged)

```bash
python3 awaken_v05.py                  # awaken, download public history itself, research, paper-trade, report
python3 awaken_v05.py --readiness      # everything still needed before the single live deployment, and who does it
python3 awaken_v05.py --hypothesis '{"name": "...", "spec": {"type": "calendar", "unit": "hour", "value": 6, "product": "BTC-USD", "measure": "return"}, "rationale": "..."}'
python3 -m unittest discover -s tests  # 101 tests (5 v0.2 + 38 v0.3 + 45 v0.4 + 13 v0.5)
```

Built from the owner's four decisions of 2 Oct 2026 (all agreed) and the single-deployment ruling:

1. **APEX fetches its own history.** No downloads by hand. Coinbase public candles: 20 coins daily since 2015, BTC and ETH hourly since 2017. This runs under web-lease pre-approval revision 3.
2. **Paper trading now.** There are two books, perps-cost long-short and spot-cost long-only. Every rebalance needs the `market.paper_order` lease and can reach only the in-process venue `paper.local`.
3. **An evidence record replaces the pass/fail gate.** Every trial is counted. The deflated Sharpe and the probability of backtest overfitting combine into one continuous score, and the owner signs only where real money starts.
4. **Free attention data now.** Sources are Wikipedia pageviews, GDELT news counts, Fear & Greed and Kraken funding rates, with an attention → volatility test.

* **Single deployment:** one artifact (the combined model, pinned by hash) is deployed once, after owner ratification.
* **Owner hypotheses:** each is registered before it is tested and counted as a trial. The owner's 6-cycle ideas are in `hypotheses/owner_2026-10-02.json`.

**First real-data result:** no demonstrated edge yet. The best single signal, 14-day momentum, scores Sharpe 0.96 with a deflated Sharpe of 0.78. The combined model is at 0.26 / 0.11, and holding BTC scores 1.13. Paper trading has started. The full results are in `APEX_V0_5_IMPLEMENTATION_SPEC.md` and `TEST_RESULTS_V0_5.txt`.

**Fixes:**
* The action budget now refills (a rolling 24 hours).
* A lease the owner revokes stays revoked.
* Network errors become data, not crashes.

All v0.4.1 code is byte-identical (`MANIFEST_V0_4.json`, enforced by a test). Nothing in v0.5 can place a real order.

**v0.5.1 (3 Oct 2026):**

* **Your 3 Oct ideas are tested** in `docs/OWNER_IDEAS_2026-10-03.md`.
  * No special price levels: round numbers and golden-ratio, e and pi levels behave like randomly placed levels.
  * A simple BTC trend rule makes positive returns and smaller drawdowns, but does not beat holding on Sharpe.
  * Media and whale data predict volatility, not direction.
* **APEX can now test** price-level, simple-rule and media/on-chain hypotheses itself.
* **New data:** free on-chain data (Coin Metrics Community) and GDELT news tone, refreshed weekly.
* **The BTC core trend paper book** is built and waits for your OK to join the paper lease.
* **Fixes:** lease scopes now bind paper books, and the evidence record survives a restart.
* 109 tests.
