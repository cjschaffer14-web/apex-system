# APEX v0.3: The Incubating Organism

v0.3 grows the v0.2 executable nucleus into an organism that can keep developing by itself, safely, while staying governed. Every idea in the four sources below is either built as code with tests, recorded as an E4 interpretation that is not allowed to gate action, or corrected here with the reason stated.

```
python awaken.py                                  # one-click awakening (v0.3)
python run.py                                     # v0.2 demo, unchanged
python -m unittest discover -s tests              # 43 tests: 5 from v0.2 (unchanged) + 38 from v0.3
```

Standard library only. Python 3.10 or newer (tested on 3.13).

---

## 0. Sources integrated

| Source | What it contributed |
|---|---|
| v0.2 package (this folder) and `APEX_V0_2_IMPLEMENTATION_SPEC.md` | the executable core, abstraction registry, maths library, UCA-2 pseudocode, plan phases A–G |
| *Gemini – Architectural Synthesis of Unified Model* (20 pp) | many-worlds design lineage, failure timelines, systems theories (VSM, stigmergy, active inference, polycentric governance, category theory, enactivism, second-order cybernetics, biosemiotics), wrapper/mixin extension pattern, walls as manifolds, Egg/Tower/Cell analogies, wiser-guys convergence (OCap, seL4, Lamport, Friston), common mathematical threads, philosophical correspondences, Block X (Transcendent Organism) |
| *ChatGPT 10/23 discussion* (49 pp) | five physical systems; Upgrades 1–8 (separate knowledge kinds, add-only history, tiny authorityd, event-stream backbone, many-worlds as lineage, sealed self-improvement first, trading out of the Constitution, Research Pack first); Autonomy Charter and Autonomous Liveness; value-of-computation formula; developmental Egg (warmth, bands, heartbeat, sleep, frontier, hatch readiness, permeability, morning report) |
| Owner decisions from earlier APEX sessions | add-only rule; single user; owner action possible at all times; broker split; reserved tier; boundary hardening; identify and reach the owner through real channels; alignment with the v8.5 Egg |

**Referenced but not supplied:** the 70-page Master Dense corpus, the Unified Codex (ollama), v9.0, parts of UCA-1.1 (threat classes T3–T9, mitigations M1–M30), and the v8.5 Egg text with the canonical wall names. Where v0.3 depends on these it says so and leaves a reconciliation point.

---

## 1. The add-only rule

* Every v0.2 code file is **byte-identical**, and v0.2 docs are only appended to. `MANIFEST_V0_2.json` lists them and `test_v02_files_add_only` enforces it (code identical; docs may only be appended to). `state/` is excluded because it is append-only runtime history.
* All v0.3 code is new: `apex/ext/`, `awaken.py`, `tests/test_apex_v03.py`, `constitution/`, `philosophy/`, `config/`, this spec. `README.md` is only appended to.
* The extension mechanism is `contracts.Extension`, the Gemini "Protocol Wrapper & Contract Injection" pattern. Wrappers hold a base object, never mutate it, and preserve its interface. Every Authority-side wrapper may only **tighten** a decision (`contracts.tighten`).
* v0.3 continues v0.2's ledger. `awaken.py` appends to `state/events.jsonl`, so v0.2's history is the start of v0.3's Shell. `run.py` can still append to it, and the chain still verifies.

**Open decision for the owner.** ChatGPT's Upgrade 2 proposes that "add-only means history is immutable, not that current code can never be refactored", using signed migrations. Your standing rule is stricter. v0.3 follows your rule: nothing is edited. It also ships the signed-migration mechanism unused (`authorityd.record_migration` + `ledger.file_manifest`). You can switch to it later without losing lineage.

---

## 2. Shape: five systems, three planes, one loop

```
WORLD ─► 1 PERCEPTION (Membrane → Observation → EvidenceBundle)
            ─► 2 COGNITION (graph, research slice, deliberation, peers)  ── Proposal plane
            ─► 3 AUTHORITY (authorityd: verify → constrain → invariants → mint → audit)
            ─► 4 ACTION (VerifiedRuntime + ResourceBroker, token-gated)  ── Actuation plane
            ─► 5 EVOLUTION (outcome → LearningCandidate → sealed suites → canary → champion/rollback)
                     └──────────────► back to Cognition
OPERATOR (P-1): halt · resume · override · ratify axioms · rectify names · charter · migrations
```

There is no Proposal → Actuation edge. `topology.prove_no_bypass()` searches the whole flow graph for a path that avoids Authority and returns a witness if one is ever added (Wall 1).

---

## 3. What v0.3 adds, by system

| System | Capability | Module | Maturity | Source |
|---|---|---|---|---|
| Perception | Membrane: channel trust, error model, provenance; instruction-like text on non-command channels is quarantined as quoted data | `epistemics.Membrane` | E1 | Gemini (biosemiotics, membrane); ChatGPT (web ≠ truth) |
| Perception | Trust lattice: partial order, meet/join, task projection | `epistemics.TrustVector` | E1/E2 | v0.2 doc |
| Cognition | Active inference: reversible probes chosen by information gain net of cost before proposing | `epistemics.ActiveInferenceDeliberation` | E2 | Gemini Step 1 |
| Cognition | Compression records that must keep raw references | `epistemics.CompressionRecord` | E1 | v0.2 doc |
| Cognition | Research Pack vertical slice: document graph, claims, equations, citations, 4 retrieval strategies, grounding check, benchmark | `research_slice` | E1/E2 | ChatGPT Upgrade 8 |
| Cognition | Stigmergic graph: branch ownership, independence metadata required, competes_with | `collective.StigmergicGraph` | E2 | Gemini, UCA-2 §4 |
| Cognition | PeerRouter: consult peers only above uncertainty/novelty thresholds; maximise lineage diversity | `collective.PeerRouter` | E2 | ChatGPT (cross-AI as an organ) |
| Authority | **authorityd** in a separate process: 5 responsibilities, key never leaves, whitelisted surface, sole ledger writer | `authority_service` | E0/E1 | ChatGPT Upgrade 3; Plan Phase A.4 |
| Authority | Evidence resolved by id; channel-trust caps; correlated sources collapse to one vote | `authority_service.decorrelate` | E1 | UCA-2 §5 |
| Authority | Protected-evaluator seal (hash of every Authority module, checked before each decision; fails closed) | `AuthorityKernel.seal_status` | E0 | spec §11 |
| Authority | ConstitutionV3: proposals can never request `authority.*`, `operator.*`, `ledger.*`, `evaluator.*` | `authority_service.ConstitutionV3` | E0 | v0.2 + hardening |
| Authority | Viability region over layer vectors (only layers at E3 or better may gate) | `epistemics.ViabilityGate` | E2/E3 | Gemini OCap-Markov item 2 |
| Authority | Revealed axioms (operator-ratified, restored from history on restart) | `transcendent.AxiomGate` | E1 | Gemini Block X |
| Authority | Counterfactual shadow vs failure Timelines A–D; ruin-adjacent rule | `design_space.CounterfactualShadowGate` | E2/E3 | Gemini Phase 3 |
| Authority | Precedent search (tighten-only) | `design_space.PrecedentGate` | E2/E3 | Gemini OCap-Markov item 3 |
| Authority | Epistemic horizon: mystery evidence → deferred, owner escalation | `transcendent.TranscendentGatekeeperWrapper` | E1 | Gemini Block X; ChatGPT Upgrade 1 |
| Authority | Second-order observer + liveness monitor (Timeline C lesson) | `cybernetics` | E1/E2 | Gemini |
| Action | VerifiedRuntime: Authority token introspection, scope, budget, replay, halt, manifest + code fingerprint ("rectification of names") | `runtime.VerifiedRuntime` | E0/E1 | spec §9; Gemini Zhengming |
| Action | **Broker split**: CapabilityBroker (Authority, *what*) vs ResourceBroker (Actuation, *how much*, protects reserve) | `runtime.ResourceBroker` | E1 | owner review |
| Action | **Reserved tier P-1** + preemption + checkpointing + incubation gating | `scheduler.ReservedTierScheduler` | E1 | owner review; spec §13 |
| Evolution | Sealed promotion: 9 suites, protected targets, canary, rollback, motifs from archived branches | `evolution.SealedPromotion` | E1 | spec §11; ChatGPT Upgrades 5–6 |
| Evolution | **Autonomy Charter** (signed once) + **fork on missing capability** (archive as awaiting-capability, keep improving) | `evolution.AutonomyCharter` | E1 | ChatGPT |
| Evolution | Developmental frontier ordered by value of computation V_i | `incubation.DevelopmentalFrontier` | E2 | ChatGPT |
| Operator | Owner profile + ranked channels; local outbox always; external channels as gated proposals | `operator_channel` | E1 | owner vision |
| Operator | Halt (revokes all tokens, stops runtime, checkpoints jobs), resume, override, ratify, rectify, charter, permission grants | `operator_channel.OperatorChannel` | E0/E1 | owner rule |
| Shell | Chain verification, Lamport continuity, replay to any point, projections | `ledger` | E0 | ChatGPT Upgrade 4 |
| Organism | One-click awakening, heartbeat, sleep cycle, morning report, hatch readiness | `awakening.Organism` | E1/E2 | Codex launch sequence via ChatGPT |
| Packs | Polycentric validation; Coding, Media, Cybersecurity, Personal Ops packs; CapitalStewardshipPolicy (Trading only) | `domain_policy` | E1 | spec §12; ChatGPT Upgrade 7 |

---

## 4. authorityd (the trusted core)

```
verify_proposal      evidence by id · channel-trust caps · decorrelation · seal check · halt check
evaluate_constraints v0.2 Gatekeeper risk + resource headroom
evaluate_invariants  ConstitutionV3 · viability region · revealed axioms · counterfactual shadow · precedent · horizon
mint_capability      v0.2 CapabilityBroker; key = os.urandom(32) generated inside authorityd
append_audit         ContinuityLedger; the only writer
operator endpoints   halt · resume · override · ratify · rectify · ratify_charter · verify_grant · record_migration
```

Decision stack, outermost first: `TranscendentGatekeeperWrapper → PrecedentGate → CounterfactualShadowGate → AxiomGate → ViabilityGate → SecondOrderObserver → Gatekeeper(ConstitutionV3)`.

Trusted-core size (Authority modules + the shared code they import): about 1,800 lines of Python. When this API is stable, port it to Rust (Phase G).

---

## 5. The Seven Walls as manifolds

Each wall is an invariant over the organism's state space, read through every analogy, with an executable probe. Awakening **fails closed** if any probe fails.

| Wall | Invariant (manifold) | Egg | Tower | Probe |
|---|---|---|---|---|
| W1 Mediated Boundary | every trajectory from thought to effect crosses Authority | membrane | no stair from observatory to street except through the core | reachability proof |
| W2 Token-Only Actuation | no consequential change without a valid scoped token | nothing leaves the shell without passage | street gates open only to keys cut in the core | forged and missing tokens refused |
| W3 Immutable Provenance | history append-only and verifiable | shell | foundation records | chain verification |
| W4 Protected Constitution & Evaluators | the organism cannot amend its own law or judges | yolk / DNA | load-bearing core | seal intact; authority-surface requests refused |
| W5 Observed Self-Modification | every change passes sealed evaluation; evaluators stay outside mutation | the genome's rules | inspected renovations | protected-target candidate refused |
| W6 Operator Sovereignty & Liveness | the owner can always act and stop; the owner's absence never stops safe development | the hand can always lift the egg | control room always powered | channel reachable, P-1 reserve intact, charter present |
| W7 Reserves & Reversibility | floors hold; every promotion can roll back | the white | structural margin | reserve > 0, rollback path, checkpoint dir |

The v8.5 canonical names weren't in the supplied files. Gemini places the autopoietic perimeter at Wall 5, which matches W5 here. When the v8.5 text is available, reconcile the names; the invariants shouldn't need to change.

---

## 6. Autonomy without abdication

* **Autonomy Charter** (`constitution/autonomy_charter.json`). You approve it once, at first awakening. *May*: 22 classes of self-development. *May not*: rewrite constitutional authority, grant itself a new external permission, exceed the spending ceiling, obtain new credentials, remove the operator's ability to stop it, silently erase audit history. It is stored in the ledger and restored on every awakening.
* **Autonomous Liveness** (invariant, W6): once awakened, the owner's absence must not stop safe learning, research, experimentation, evaluation or improvement inside the envelope.
* **Fork on missing capability**: a candidate that needs reach the charter doesn't grant is archived as `awaiting-capability`, and development continues on compatible branches. Your decision widens the organism's reach. It is not needed for learning to continue. A signed, candidate-specific grant (`OperatorChannel.grant_permission_delta`) releases a forked branch.
* **Executive loop** (`Organism.heartbeat_tick`): sense body → incubation temperature → band → pick the highest-value frontier item → run it as checkpointable P3 work → sealed evaluation → autonomous promotion inside the charter → token-gated persistence → checkpoint.

## 7. The developmental Egg (incubation)

* Warmth `W = C·A·D·S` (compute headroom, attention, developmental data, stability). Bands: DORMANT, WARM, INCUBATING, ACCELERATED, HATCHING. Unused compute becomes incubation; DORMANT disables P3.
* Shell continuity: an awakening refuses to proceed on a broken chain. Authority rebuilds axioms, rectifications and the charter from history. A restart is cooling, not death.
* Sleep cycle: replay → compress (with declared loss) → recombination motifs.
* Hatch Readiness `H = [L, G, M, R, E, A, C]` with minima over 8 criteria: liveness, state recovery, authority isolation, evaluation loop, candidate rollback, research loop, scheduler autonomy, frontier selection. HATCHED means *self-continuing*, never *unconstrained*.
* Permeability ladder: local files → approved web → approved cloud → cross-AI → external applications → persistent services. Each rung opens only with granted capabilities. The membrane gets richer; it never disappears.

## 8. First autonomous improvement (reference run)

Research slice on the bundled sample paper, 5 questions:

| Strategy | Accuracy | Sealed result |
|---|---|---|
| flat_small (baseline champion) | 0.6 | baseline |
| flat_large | 0.4 | rejected: domain, regression |
| section | 0.6 | rejected: regression on Q1 |
| **claim_graph** | **0.8** | **promoted autonomously**, persisted via token-gated `state.write_champion` |
| cross_ai | – | **awaiting-capability** (needs `network.peer_ai`); forked, development continued |

## 9. Cross-AI (UCA-2, executable)

Envelope v2 adds `sender_key_id`, key revocation and **V7 role violation**: peers cannot send Decision, Token, Authorize, Amend or ModifyEvaluator messages. Consensus counts each model **lineage once**, discounts lineages that share sources, preserves minority reports, and enters only as `uncertainty_type="consensus"` evidence. At tier ≥ 2 the counterfactual shadow denies proposals that rest on consensus alone (Timeline B).

## 10. Mathematics added (`math_ext.REGISTRY_V03`)

Jensen–Shannon divergence; conditional entropy H(S|O); mutual information; ergodicity gap (time average vs ensemble average); gambler's ruin; Markov blanket (DAG) and subsystem blankets over the flow graph; the reachability proof; the partial-order trust lattice; value of computation `V_i = (E[ΔK]+αE[ΔC]+βE[ΔU]+γE[ΔT]) / (C+R+λL)`; developmental warmth; and the Universal Equation's executable shadow `governed_action` (no certainty, no action).

## 11. Interpretive layers (E4, never authorizing)

`philosophy/` holds the Egg, Tower, Cell, Manifold, many-worlds design-space, Transcendent (Block X) and philosophical-correspondence material. `views.py` makes each analogy checkable: every view must cover all five planes and name real components. The contract rule (`ExecutableContract.validate`) rejects any E4/E5 abstraction that tries to affect action.

---

## 12. Corrections made to the source material

1. **"Consensus = truth"** appears twice in the Gemini text. The design rule everywhere else is *consensus ≠ truth*; v0.3 encodes that.
2. **Gemini Block X code would not run against v0.2.** It imported a non-existent `apex.authority.Invariant`, called `evaluate(proposal, state, evidence)` expecting `(approval, decision)`, and read `proposal.risk_estimate` (the proposer's advisory value, which Authority must ignore). Rewritten against the real API with the same names.
3. **"Zhengming inputs bypass heuristics and write directly to Authority's immutable memory"** contradicts itself. v0.3 implements authenticated, appended Rectification records.
4. **Overclaims** ("proves we are hitting absolute structural truth", "most resilient possible path", "the architecture is complete", "absolute coherence"). Convergence with OCap, seL4, Lamport and Friston is evidence that those choices are sound, not proof of superiority. v0.3 claims only what its tests show.
5. **"20% floor and 2.5% redistribution are mathematical proofs of ergodicity."** They are ruin-avoidance policies motivated by ergodicity economics. Moved to the Trading pack as configurable `CapitalStewardshipPolicy`.
6. **"Determinant is positive" / "tensor multiplication"** for gating became a per-dimension viability-region check.
7. **"Authority triggers de-leveraging/hedges"**: Authority never generates action (wu wei). It denies with a reason, and the Proposal plane re-proposes smaller.
8. **"Apply the precedent's token constraints"**: precedent may tighten, never approve.
9. The Gemini timeline lettering differs between answers. Reconciled as A (unconstrained capability), B (consensus capture), C (zero-liveness prover), D (passive non-metabolic tool).
10. **Gaps in v0.2 itself**, fixed by extension without edits: the runtime didn't verify signature, scope or budget; the Lamport clock reset on reload; the Gatekeeper accepted proposer-supplied bundles; Authority wasn't a separate process (Plan A.4); the Authority-side consensus computation was missing; the envelope lacked `sender_key_id`.

## 13. Still not production-complete

Secure Enclave operator key with a user-presence check (today it is an HMAC dev key in `state/operator_dev.key`, mode 0600) · Ed25519 instead of HMAC · Rust authorityd · Wasm/process sandbox for capabilities · MLX model runtime · PDF parsing (the slice takes text/markdown) · real email sending (dry run writes to the outbox) · battery/thermal telemetry · persisting the candidate archive across sessions (only the champion is persisted) · external anchoring · live brokerage.

## 14. Next horizon (v0.4 candidates, by expected value)

1. Persist the evolutionary archive and frontier as ledger projections, so lineage survives restarts.
2. MLX reasoner + PDF ingestion plugged into `research_slice.parse_document/retrieve`.
3. A real `notify.email` behind the charter's network allowlist, using your verified address in `state/owner.json`.
4. Port authorityd to Rust/PyO3 with Ed25519, keeping the Python API as the test oracle.
5. Reconcile wall names and the threat classes T3–T9 when the v8.5 and UCA-1.1 texts are supplied.
