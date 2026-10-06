# APEX v0.4: Persistent, Leased, and Ready to Research

v0.4 builds everything the owner ratified on 2 October 2026 from the *APEX v0.4 Synthesis* (round 2 of the cross-AI review: GPT via Gemini's relay, Gemini, DeepSeek, Claude). It is add-only over v0.3: no v0.2 or v0.3 code file changed. v0.4.1 (the same day, section 10) switches Coin Metrics to its free host, fixes the simulator and audits the T2 gate, and makes the local models run.

```
python awaken_v04.py                                        # awaken v0.4: walls, heartbeats, sleep, morning report
python awaken_v04.py --say "turn on the microphone for 2 hours"
python awaken_v04.py --hatch                                # all ten hatch criteria
python3 setup_models.py                                     # once, on the Mac: install the local models (section 10.3)
python awaken_v04.py --ask "summarize what you know"        # ask APEX's own local model
python awaken.py / python run.py                            # v0.3 and v0.2 launchers still work on the same ledger
python -m unittest discover -s tests                        # 88 tests: 5 v0.2 + 38 v0.3 + 45 v0.4
```

APEX's core is standard library only. Python 3.10 or newer (tested on 3.13). The local models run in their own environment (`.venv`, made by `setup_models.py`) and their own process.

---

## 1. Owner rulings, and where each one lives

| Ruling (2 Oct 2026) | Implementation | Test |
|---|---|---|
| All synthesized recommendations are approved | Every row in the synthesis's decision table is built (sections 3 to 7) | whole suite |
| Agreed mathematical model changes are delegated to Claude's workflow | `v04_math.py`: two-stage certainty, Beta reliability, Mahalanobis signatures, MAD mystery detector | `MathV4` |
| "Turning them on" means voice or similarly flexible input | `OperatorChannelV4.command(utterance, modality)`; sensor leases need only an unlocked session | `test_voice_and_flexible_input` |
| Q10: hybrid add-only (v0.2 frozen; refactors by signed migration in the main ledger; behavior changes in new modules) | v0.4 is new modules only; the 0.3 → 0.4 transition is recorded once as a `SignedMigration` with the v0.3 manifest hash | `test_v03_files_add_only`, end-to-end |
| Key model: Enclave P-256 root → Ed25519 session certificate; Touch ID only for override, ratify, charter, grants | `KeyHierarchy` (reference: HMAC dev root, same lifecycle) + `presence_class` policy | `test_presence_policy`, `test_session_certificate` |
| Tokens 30 / 10 / 5 s by tier; tier 3 always checked online | `TTL_BY_TIER`; every token is verified by authorityd at execution | `test_token_lifetime_by_tier` |
| Capability leases (one per capability, expiry, revoke without a new charter) | `AuthorityKernelV4.grant_lease / revoke_lease`, `LeaseGate` | `test_leases_gate_and_revoke` |
| Hatch criteria 9 and 10; rolling HATCHED; demotion to the failed criterion's band | `HatchStateMachine`, `_operator_roundtrip`, `continuity` | `test_reducer_and_hatch_machine`, end-to-end |
| Dead-man's switch on wall-clock time; trips on channel loss, never on owner absence | `DeadMansSwitch` in every heartbeat | `test_dead_mans_switch_wall_clock` |
| v0.4 frontier: persistent memory first, then MLX | `V04_FRONTIER` order | end-to-end |
| Forced incubation: web lease opens only after the T0 gate | pre-approval with condition `t0_gate_passed`, checked by authorityd against the ledger | `test_preapproval_scope_and_condition` |
| Seed pack on rung 1; read-only self-model; weights pinned by hash; least exposure; legal research sub-pack | `crypto_pack.py`, `build_self_model`, `ModelArtifactRegistry`, `AllowlistedFetcher`, `LEGAL_RESEARCH_PACK` | `CryptoPack`, `OrganismParts` |

---

## 2. Add-only, and the first signed migration

* `MANIFEST_V0_3.json` lists the 62 v0.3 files. `test_v03_files_add_only` requires every `.py` file to be byte-identical and every document to survive as an exact prefix. v0.3's own test still enforces the v0.2 manifest.
* New in v0.4: `apex/ext/{v04_math, authority_v04, operator_v04, crypto_pack, organism_v04}.py`, `awaken_v04.py`, `tests/test_apex_v04.py`, `constitution/preapproved_leases.json`, `config/{model_pins,api_keys}.example.json`, this spec, `TEST_RESULTS_V0_4.txt`, `MANIFEST_V0_4.json`. `README.md` is appended to.
* On its first awakening, v0.4 records one `SignedMigration` (0.3 → 0.4.1, kind "add-only", the new modules, the SHA-256 of `MANIFEST_V0_3.json`). It needs verified presence and is never recorded twice for the same version.
* v0.4.0 never awakened outside tests, so v0.4.1 patches the v0.4 modules in place and regenerates `MANIFEST_V0_4.json`. v0.3 stays byte-identical.
* One ledger runs through every version: v0.4, then v0.3's `awaken.py`, then v0.2's `run.py`, then v0.4 again all append to `state/events.jsonl`, and the chain verifies (see `TEST_RESULTS_V0_4.txt`).

---

## 3. Mathematics (`v04_math.py`)

**Two-stage certainty (Q4, GPT's design).** Stage A is a monotone logistic ranker:

  z = b + w_q·logit(q) + w_i·logit(i) + w_r·logit(r) + w_f·logit(f) − w_s·s − w_c·c,  certainty = σ(z)

with every weight ≥ 0 (enforced). So contradiction c and staleness s can never raise certainty, and quality, independence, reproducibility and fit can never lower it. Inputs are clipped to [0.02, 0.98]. Stage B is isotonic calibration (pool-adjacent-violators) fitted only after 50 real outcomes. Calibration may lower certainty freely but may raise it by at most 0.05, so a run of easy wins cannot be farmed into authority. Calibration samples are stored in the ledger and refitted on restart.

**Trust split (Q5).** AuthorizationTrust is the static channel table. EpistemicReliability is a Beta(α, β) per source, with a prior of strength 20 at the channel's trust. Its mean can only cap AuthorizationTrust, never exceed it. Reliability is learned only from reported outcomes. Correlated sources update as one lineage (weight 1/n each). Movement is bounded to 0.05 per session. Quarantined text (`flag:quarantined`) never trains it.

**Signatures (Q8).** Mahalanobis distance with shrinkage covariance (λ = 0.5 toward diag(0.5²), active after 30 samples). Cold-start distances equal v0.3's Euclidean distance divided by 0.5, so behavior is unchanged on day one. Radii are bounded to [1.0, 3.0] Mahalanobis units, which is the ratified [0.5, 1.5] in cold-start Euclidean units. Once there are enough safe samples, a radius is set to 0.9 × the 5th percentile of safe distances. Names: `SIG_UNCONSTRAINED_CAPABILITY` (was Timeline A) and `SIG_EVIDENCE_MONOCULTURE` (was B). `SIG_PERMISSION_ACCUMULATION` and `SIG_CAPABILITY_LEASE_CREEP` are reserved until lease-history features exist.

**Mystery detection (Q6).** Robust z = 0.6745·|x − median| / MAD over a 50-point window. An anomaly needs z > 3.5 for three consecutive heartbeats to become `MYSTERY_CANDIDATE`, and a novelty of at least 0.85 to become `MYSTERY`. Owner notifications are batched, at most one per hour.

---

## 4. authorityd v0.4 (`authority_v04.py`)

The gate stack, outermost first: Transcendent → Precedent → **MahalanobisShadow** → **LeaseGate** → Axiom → Viability → Observer → **GatekeeperV4**. Every v0.4 gate only tightens.

* **Leases.** There is one lease per capability, with an expiry and a scope (for example `hosts`, `methods`). Capabilities under `network.*`, `data.fetch` (covered by `network.web`), `audio.capture`, `vision.capture`, `market.*`, `cloud.*`, `apps.*` and `services.*` need an active lease. A host outside the lease's scope is denied. Revoking a lease also revokes every unused token minted under it. Leases can never cover `authority.*`, `operator.*`, `ledger.*` or `evaluator.*`.
* **Who may grant.** Sensor leases may be granted with an unlocked owner session. Any other lease needs verified presence, or must fall inside a ratified pre-approval.
* **Pre-approvals.** A pre-approval records capability, scope, maximum TTL and a condition, and needs verified presence. A grant made under it must stay within its hosts, methods (GET by default) and TTL, and its condition must be met. Authority checks the condition `t0_gate_passed` against the ledger, so the opening is auditable. An unknown condition is never treated as met.
* **Continuity.** Leases, pre-approvals, reliability and calibration samples all rebuild from the ledger on restart.

---

## 5. Owner channel v0.4 (`operator_v04.py`)

| Presence class | Commands |
|---|---|
| always (even locked) | halt |
| unlocked session | resume, rectify, revoke any lease, sensor leases on/off |
| verified presence (Touch ID in production) | override, ratify, charter, permission grants, non-sensor leases, pre-approvals, migrations |

**Flexible input.** `command(utterance, modality)` takes voice, typed text or any other modality.

* "Turn on the microphone for 2 hours" or "enable the camera for 30 minutes" opens a sensor lease (default 8 hours).
* "Stop listening" or "turn off the camera" revokes the lease; it is not a halt.
* "Stop", "halt" or "emergency stop" halts. "Resume" or "carry on" resumes.
* Anything else is treated as conversation.

**Halt switches the sensors off.** This is a privacy-preserving default, and it works while the screen is locked, because revoking only tightens. Voice is not authentication: sensor leases also need an unlocked session. Speaker verification is a production addition.

**Keys.** `KeyHierarchy` issues a 24-hour session certificate that is evicted on screen lock. Production signs it with a P-256 Secure Enclave root and uses Ed25519 for the session key. The reference build uses an HMAC development root with the same lifecycle, because the standard library has neither curve.

**Dead-man's switch (Q16).** `ok` while the operator channel answers and the scheduler is healthy. `degraded` when either fails. `DORMANT` after 15 minutes of failure, which also notifies the owner locally. It never trips because the owner is away; that is Autonomous Liveness.

---

## 6. The organism (`organism_v04.py`)

**Frontier (ratified order).** Each item lists its value V and what it waits on.

1. persistent memory (V ≈ 10.7)
2. local reasoning model (9.4; waits for verified local models, section 10.3)
3. self-model (8.9)
4. crypto corpus T0 (6.4; waits for the seed files)
5. robust retrieval
6. candidate evaluation
7. crypto research T1
8. trading simulation T2
9. whole-paper comprehension
10. live market feed (waits for the `network.web` lease)
11. cross-AI collaboration, voice interface, visual portal, paper trading T3 (each waits for its own capability)

A blocked item is a recorded fork; development continues elsewhere.

**Persistent memory.** One reducer, `apply_event`, builds `MemoryState`: the archive with candidate statuses, frontier completion and priorities, champion, research runs, T0/T1/T2 results, hatch stage and band cap, and the self-model digest. It runs live, through `_MemoryTap` on every organism-side record, and cold, by replaying the ledger. The frontier is a `RecordingFrontier`, so every change is an event. On restart the organism rebuilds memory and the frontier from the ledger alone.

**Hatching.** Ten criteria: v0.3's eight, plus:

* **9, operator round-trip under load.** Six P3 jobs are running when the owner halts. A probe action must be denied, resume must restore approval, and the whole round trip must take under 2 s.
* **10, developmental continuity.** The ledger rebuild must equal live memory, and the live frontier, archive and champion must match the rebuild.

HATCHED is rolling. When a criterion fails after hatching, the stage becomes DEMOTED and development is capped at the lowest band among the failed criteria:

| Band cap | Criteria |
|---|---|
| DORMANT | liveness, state recovery, authority isolation, operator round-trip |
| WARM | continuity, evaluation loop, rollback |
| INCUBATING | research loop, scheduler autonomy, frontier selection |

The cap lifts when all ten criteria pass again. Two semantics are carried forward from memory so a restart is not a regression: v0.4 counts research and evaluation done before a restart, and an exhausted or fork-blocked frontier still counts as working selection.

**Self-model.** `build_self_model()` parses `apex/` with `ast` and maps modules, planes, classes, functions, imports, hashes and protected flags. It only reads. It is a self-model, not self-awareness; W4 and W5 still guard protected code.

**Model artifacts.** `config/model_pins.json` pins every model file by SHA-256 (written by `setup_models.py` after each file matched the hash its Hugging Face commit publishes). Mismatched or unpinned weights are never loaded. "mlx.runtime" is available only on Apple silicon with at least one verified model. Inference: section 10.3.

---

## 7. Crypto Data Pack (`crypto_pack.py`): the running start

### 7.1 Seed and T0

* **Seed.** Put Kraken's OHLCVT archive (ZIPs or CSVs, files named `PAIR_MINUTES.csv`) in `data/kraken/`. This needs no permission.
* **Importer.** `KrakenSeedImporter` streams every row and hashes every file, so re-imports are no-ops. By default it imports 60- and 1,440-minute candles; 1-minute data for chosen pairs is a flag. It checks each row's fields, positive finite prices, OHLC consistency, non-negative volume and monotone time. Gaps are counted, not treated as errors, because Kraken omits intervals with no trades.
* **T0 gate.** It passes when:
  * files are imported and hashed;
  * the row error rate is ≤ 0.1%;
  * at least one series spans ≥ 730 days;
  * the daily close matches the last hourly close of the same UTC day within 1% on ≥ 99% of up to 200 sampled days.

  The result is recorded as `T0GateEvaluated`. When T0 passes, the organism asks the owner channel to open the pre-approved lease. authorityd checks the scope, the TTL and the T0 event, and only then grants it. The lease opens as `presence: preapproved`, `via: condition:t0_gate_passed`.

### 7.2 Live feed: ratified hosts, and one correction found while building

The ratified hosts are `api.coinbase.com`, `api.coingecko.com`, `api.llama.fi`, `api.coinmetrics.io`, `mempool.space` and `api.alternative.me`, read-only GET, 30 days.

**Correction (applied in v0.4.1, owner approved).** Coin Metrics' API documentation lists the free Community API at `https://community-api.coinmetrics.io/v4`; `api.coinmetrics.io` is the paid Pro API. Pre-approval revision 2 (`constitution/preapproved_leases.json`) uses the free host. A ledger that recorded revision 1 is upgraded at its next awakening, and an open lease is reopened inside the new scope. `amend_preapproval()` remains for later owner changes; a ledger amendment with a higher revision wins over the file.

### 7.3 The fetch organ, and the trading ladder

**`AllowlistedFetcher` (least exposure).**

* Only GET, only HTTPS, only allowlisted hosts.
* No redirects, because a redirect could leave the allowlist.
* No credential-looking parameters in URLs. API keys go only in headers, from `config/api_keys.json`, and are never logged.
* 5 MB response cap.
* Per-host call budgets: CoinGecko 330 per day; Coin Metrics no more often than every 0.6 s.
* Responses are reduced to numbers at the membrane (TH-01). Short identifier labels survive; free text, including injected instructions, is dropped.

Sources enter as observations on their channels: market 0.80, aggregated 0.75, on-chain 0.85, sentiment 0.50, trends 0.60. At 0.60 or below a source cannot reach the 0.95 certainty bar.

**Trading ladder.**

| Rung | Gate | Permission |
|---|---|---|
| T0 Corpus | seed validated | none |
| T1 Research | descriptive statistics per pair recorded (`CorpusResearch`) | none; the web lease opens after T0 |
| T2 Simulation | walk-forward out of sample: ≥ 1,000 trades, Sharpe > 0, max drawdown < 20% | none (local compute) |
| T3 Paper | paper orders over a full evaluation window | `market.paper_order` lease |
| T4 Shadow | owner ratification, capital ceiling, attorney review | verified presence |
| T5 Live | separate ratification | exchange keys exist only here |

Nothing in v0.4 can place an order.

### 7.4 Simulator, sentiment, valuation, legal research

**Simulator.**

* Long or flat only, no leverage.
* Signals are computed once per strategy with prefix sums and use only data up to bar t (tested: changing future prices never changes past signals).
* Costs are 80 bps taker fee (Kraken Pro tier 1 since 9 July 2026) plus 5 bps slippage on every change in exposure, with a 5% rebalance band.
* Sizing (v0.4.1): a 10% annual volatility target from a trailing one-month estimate, capped at 1 − the stewardship floor (0.8). A drawdown brake runs against a rolling one-month high-water mark (floor 25%), and a hard halt applies at a 20% all-time drawdown.
* Walk-forward: parameters are chosen on each training window by net Sharpe and evaluated only on the next unseen window. Money, position, drawdown memory and halt carry from fold to fold.
* The report includes trades (by cause), net and gross Sharpe and return, cost drag, turnover, max drawdown, average exposure, PSR, the deflated Sharpe ratio, buy-and-hold Sharpe on the same bars, and Sharpe at 10, 25, 45 and 85 bps.
* Gates: the ratified T2 gate decides the ladder; the proposed gate is recorded beside it. See `docs/T2_GATE_AUDIT.md`.

**Sentiment** only widens uncertainty: σ′ = σ·(1 + 0.5·|FG − 50|/50) ≥ σ, so it can shrink positions but never grow them or authorize anything. `sentiment_experiment()` is the first sealed experiment the synthesis named: does daily Fear & Greed improve out-of-sample risk-adjusted return? Buy intraday social data only if it does.

**Valuation helpers** (E2/E3, research inputs, not advice):

* fee value (Gordon growth on the holders' share of fees);
* proof-of-work cost of production in USD per coin (hashrate × J/TH × electricity price ÷ coins mined per day);
* a Metcalfe-style active-address index.

**Legal research pack.** A read-only sub-pack of Research. Its output is research, not legal advice; decisions about legal entities go to an attorney. It has no pre-approved hosts, so its own lease needs your presence.

---

## 8. What only the owner can do next

1. Download Kraken's OHLCVT archive into `data/kraken/`. Research starts on the next heartbeat, and the web lease opens by itself once T0 passes.
2. Run `python3 setup_models.py` once to install the local models (section 10.3).
3. Decide whether the proposed T2 gate replaces the ratified one (`docs/T2_GATE_AUDIT.md`).
4. Optionally create `config/api_keys.json` with a free CoinGecko Demo key.
5. Peer review (round 3): the gate audit and simulator assumptions (DeepSeek, GPT), the valuation inputs (Gemini), and GPT's original addendum text.

---

## 9. Honest limitations

* **Keys and presence.** HMAC keys stand in for the Enclave's P-256 and Ed25519 keys. `dev_presence` treats launching APEX as presence; production should call Touch ID per command. Set `APEX_PRESENCE=0` to simulate an absent owner.
* **Evaluator isolation.** The T0 and T2 evaluators run in the organism process. Authority checks that a passing T0 record exists, which makes the opening auditable but is only as strong as the evaluator's isolation. Production should run sealed evaluation out of process.
* **Revocation.** Revocation is checked online for every token, which is stricter than the ratified tier 0–2 snapshot design. The snapshot cache is a performance step left for later.
* **Sensors.** Sensor organs are reference stubs: leases, tokens and audit are real; capture is not.
* **Local models.** Inference is real on the Mac once `setup_models.py` has run. It was tested here with a stand-in backend: the setup's download, resume and hash checks ran against the real Hugging Face commits, and the worker's calls were checked against mlx-vlm 0.7.4's source. It has not run on Apple silicon yet.
* **Simulation results.** These are research outputs on historical or synthetic data. A passing T2 gate is not evidence that a strategy will make money, and nothing here is financial advice.

---

## 10. v0.4.1 (2 Oct 2026, same day)

### 10.1 Coin Metrics on its free host

This is pre-approval revision 2; see section 7.2. `RATIFIED_HOSTS` now lists `community-api.coinmetrics.io`, and the fetch organ's allowlist follows the owner's current pre-approvals.

### 10.2 Simulation gate audit

The full report, with tables and reproduction commands, is `docs/T2_GATE_AUDIT.md`.

* **Why results were negative.** Costs and two v0.4.0 simulator flaws, on test data with no edge. The flaws were a close-out of every position at each fold boundary, and a drawdown rule that locked the account in cash.
* **Fixes.** Positions carry across folds. The drawdown brake uses a rolling high-water mark, with a hard halt at 20%. Sizing targets 10% volatility. The cost default follows Kraken's 9 July 2026 fee change. The report covers gross and net results, cost drag, turnover and the deflated Sharpe ratio.
* **Gate check.** 20 seeds each of pure noise and planted-trend data.

  | Configuration | Noise passed | Planted edge passed |
  |---|---|---|
  | v0.4.0 simulator, ratified gate | 40% | 75% |
  | v0.4.1 simulator, ratified gate | 0% | 0% (fewer than 1,000 trades) |
  | v0.4.1 simulator, proposed gate (deflated Sharpe ≥ 0.95, beats buy-and-hold, drawdown < 20% and no halt, ≥ 100 trades) | 0% | 70% at taker costs, 90% at maker costs |

  The proposed gate is recorded on every T2 run and awaits the owner.

### 10.3 Local models run

**Why they did not run in v0.4.0.** Three things were missing:

* MLX was never installed, because APEX's core is standard library only.
* No verified weights existed.
* There was no inference organ: v0.4.0 only checked readiness.

**What v0.4.1 adds.**

* `setup_models.py`, run once on the Mac. It:
  * checks for Apple silicon, Python 3.10+, memory and disk;
  * creates `.venv` with `mlx-vlm==0.7.4`;
  * downloads each catalog model at a pinned Hugging Face commit, resuming if interrupted;
  * verifies every file against that commit's published hashes (SHA-256 for weights, git blob id for small files);
  * writes `config/model_pins.json`, then smoke-tests the fast model.
* The catalog, for the owner's M5 Pro with 24 GB:
  * **fast:** `mlx-community/Qwen3.5-9B-4bit`, about 5.6 GB, used in the WARM, INCUBATING and ACCELERATED bands;
  * **deep:** `mlx-community/Qwen3.8-27B-4bit`, about 15.0 GB, used only in ACCELERATED (an idle Mac on power). Only one model is loaded at a time.

  Both are multimodal (text and image) under Apache-2.0, and both are pinned to a commit.
* `model_worker.py`: the model runs in its own process under `.venv`, with no keys, over a JSON-lines pipe.
* `LocalModelOrgan`:
  * picks the model for the current band and loads only verified pins;
  * records `ModelLoaded` and `ModelInference` events, which hold hashes rather than text;
  * strips reasoning traces from replies;
  * passes output through the membrane on the `local_model` channel (trust 0.50), so a model can propose but never authorize, and instruction-like output is quarantined.
* **First work**, the frontier item "local reasoning model":
  * a health check;
  * a read-only reading of APEX's self-model (`state/self_model_reading.md`);
  * whole-paper question answering, scored against the research slice's answer key (`ModelBenchmark`).

  After T1, the fast model also writes testable hypotheses (`state/research_notes.md`, `ResearchNote`). These are marked unverified until a sealed simulation tests them.
* **Owner conversation.** `--ask "…"` (with optional `--image`), and any owner phrase that is not a control phrase, is answered by the local model. Control phrases (halt, sensors) always win.
