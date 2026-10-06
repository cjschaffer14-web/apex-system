# APEX v0.2 Implementation Specification

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

# Full Abstraction Map

## Foundational
Measurement · Temporal Ontology · Identity · Axiology · Praxeology

## Cognitive
Epistemics · Semiotics · Social modeling

## Experiential
Embodiment · Aesthetics

## Existential
Soteriology · Thanatology · Metaphysics

## Reflective
Meta-Epistemics · Meta-Theory / emergence

## Governance-adjacent
Attention · Compression · Federated Cognition · Collective Intelligence

## Authority
Constitution · Governance · Risk · Constraint · Security · Gatekeeper · Capability Broker · Protected Evaluators · Audit custody

## Actuation
Execution Runtime · Resource Enforcer · Reliability · rollback/checkpoint · outbound proxy · hardware/system preemption

## World-model structures
Entity · Event · Observation · Claim · Hypothesis · Value · Capability · Constraint · Risk · Trajectory · Symbol · Abstraction

## Relation vocabulary
derived_from · supports · contradicts · predicts · falsifies · depends_on · constrains · authorizes · causes · precedes · compresses · instance_of · competes_with

## Older / horizon abstractions retained as typed views
Core Organism · Monotonic Growth · Fractal Duality · Embodied Metaphor · Epistemic Horizon · Scale Transition · Cycle Termination · Horizon Navigator · Somatic Algebra · Trust Lattice · Relational Ethics · Conservation Doctrine

## New systems-theory integrations
Cybernetic Homeostasis · Viable System Model · Stigmergy · Active Inference · Polycentric Governance · Category/Functor Semantics · Enactivism · Second-Order Cybernetics · Biosemiotics

## Architectural metaphors retained but non-authoritative
Egg · Tower · Topological Walls · Many-Worlds Design Space · Quantum Cell in Pressure Vessel

The runtime rule is: every abstraction that affects action must terminate in an executable contract declaring inputs, outputs, state, permissions, uncertainty/error representation, budget, failure modes, telemetry, tests and rollback behavior.


---

# APEX Mathematical Systems — Integrated Reference

APEX should be mathematically plural rather than forcing all cognition into one scalar objective.

## Measurement mathematics
- explicit instrument/error model
- independent-error propagation
- covariance/Jacobian propagation in production
- calibration residuals
- measurement is not ground truth

## Temporal mathematics
- wall-clock time
- Lamport logical clocks for causal order
- interval/moment/trajectory structures
- urgency as importance × deadline proximity × irreversibility
- reasoning termination as marginal value of compute

## Probability and epistemics
- Bayesian update where a probabilistic model is justified
- Shannon entropy as uncertainty measure
- KL divergence for distributional change, with explicit direction
- expected information gain for probe/retrieval allocation
- evidence quality, independence, reproducibility, fit and staleness kept as separable factors
- no universal truth scalar

## Active inference
Use low-risk probes to reduce prediction error/uncertainty before high-consequence action.
The included `free_energy_proxy` is explicitly a proxy, not a claim to implement full variational free energy.

## Decision and optimization
- Pareto dominance for multi-objective candidate comparison
- expected-value and constraint reasoning
- reversibility and blast radius
- optional risk-sensitive/ruin-aware objectives
- value hierarchies remain partial orders where possible

## Capital mathematics
- Fractional Kelly can be used inside Trading DomainPack
- never treat Kelly as proof of safety
- estimation uncertainty, liquidity, slippage, correlation and drawdown constraints dominate naive Kelly use
- capital formulas do not belong in the universal Constitution

## Cybernetics and control
- feedback residuals
- homeostatic safe regions
- P0–P3 resource control
- PID-like control only for appropriate measurable subsystems
- Viable System Model is an organizational interpretation, not authority delegation

## Graph mathematics
- typed graph nodes/edges
- causal/dependency relations
- `competes_with` for unresolved alternatives
- `supports` / `contradicts` carry source-independence metadata
- graph centrality does not equal truth or value

## Stigmergy
Agents coordinate by changing graph traces and reading later graph state.
This reduces token-heavy synchronous debate and preserves branch independence.

## Category/functor semantics
Treat the 14-stage pipeline as a structure-preserving transformation:
typed input objects should map to typed output objects without violating authority boundaries.
v0.2 treats this as a contract-validation discipline, not as a complete mathematical proof.

## Topology
The Proposal→Actuation prohibition is represented as a missing edge/mediated boundary.
The "topological wall" is a design property backed by process/API isolation.
The geometry language remains metaphorical at the highest level.

## Evolutionary / many-worlds mathematics
- explicit candidate parentage
- benchmark vectors
- Pareto fronts
- counterfactual distance to known failure branches
- recombination of successful motifs
- archived failures are negative data
- no literal quantum claim is required

## Information compression
Every abstraction declares:
- sources
- retained information
- discarded information
- uncertainty introduced
- ability to reopen raw source

## Social/game mathematics
- model strategic agents and incentives where useful
- preserve minority/dissent reports
- consensus is not evidence independence
- correlated model families must not be counted as independent votes

## Emergence / complexity
Higher abstractions may be proposed when they measurably improve at least one:
- prediction
- compression
- explanation
- planning
- transfer
- control

Promotion must record which dimension improved and the benchmark delta.

## Trust lattices
Prefer a partial-order/vector representation:
- identity trust
- source reliability
- domain competence
- recency
- independence
- authorization

A single scalar trust score may be a projection for one task but is not the underlying representation.

## Conservation / invariants
Track quantities and properties that must survive transformation:
- audit provenance
- operator control
- authority separation
- resource floors
- rollback ability
- model/evidence lineage

## Meta-mathematical humility
Formal systems and models are tools with scopes and assumptions.
When a mathematical object is only an analogy, the implementation must mark it as such rather than letting metaphor silently become execution authority.


---

# APEX v0.2 Cross-AI Collaboration Pseudocode (UCA-2 Reference)

## 0. Governing principle

All external and local models are Proposal-plane peers.

No model:
- mints execution authority,
- directly actuates,
- changes protected evaluators,
- changes its own permissions,
- treats peer consensus as truth.

All peer outputs are evidence or proposals until Authority validates them.

---

## 1. Canonical envelope

```text
Envelope:
    schema_version
    message_type
    message_id
    seq
    timestamp
    sender_id
    sender_key_id
    payload_hash
    payload
    signature
    canonicalization = "JCS-like deterministic JSON"
```

Validation:

```text
validate(env):
    V1 schema supported
    V2 timestamp within skew
    V3 sender registered and key active
    V4 signature valid
    V5 canonical(payload) hash matches payload_hash
    V6 message_id unseen AND seq monotonic
    if any fail:
        append REJECTED event
        return REJECTED
    append VALIDATED event
    return VALIDATED
```

Production upgrade: replace HMAC reference signatures with Ed25519 or platform-secure asymmetric keys.

---

## 2. Cross-AI roles

```text
PROPOSAL PEERS:
    LocalMLX
    GPT
    Gemini
    Claude
    DeepSeek
    future models
    specialist tool-models

Each peer may:
    observe(public_projection)
    read(authorized EvidenceBundles)
    create(Claim)
    create(Hypothesis)
    create(Proposal)
    challenge(Claim)
    falsify(Hypothesis)
    attach(counterevidence)
    write(stigmergic graph traces)

Each peer may not:
    write(authorizes edge)
    mint(ExecutionToken)
    modify(Constitution)
    modify(protected evaluator)
    directly invoke side-effectful actuator
```

---

## 3. Parallel deliberation

```text
function cross_ai_deliberate(goal, evidence):
    branches = parallel_map(registered_proposal_peers):
        peer.generate(
            goal,
            evidence,
            requirements = {
                assumptions,
                alternatives,
                predictions,
                falsifiers,
                uncertainty,
                requested evidence,
                proposed action
            }
        )

    for branch in branches:
        validate envelope
        store branch separately
        write ModelGraph traces:
            supports
            contradicts
            predicts
            falsifies
            competes_with

    return branches
```

No peer overwrites another peer's branch.

---

## 4. Stigmergic collaboration

Preferred coordination is through graph state rather than a long multi-agent chat.

```text
peer_A:
    add Claim C1
    add Evidence E1 supports C1

peer_B:
    observe C1
    add Evidence E2 contradicts C1
    add Hypothesis H2 competes_with H1

peer_C:
    observe graph delta
    add Falsifier F3 for H2
```

The graph accumulates disagreement without forcing premature consensus.

---

## 5. Consensus bundle

Consensus is a descriptive artifact, not an authority grant.

```text
Authority.compute_consensus(signed_peer_outputs):
    for each claim:
        support = weighted independent support
        oppose  = weighted independent contradiction
        correlation_penalty = shared-source/shared-lineage overlap
        unresolved = evidence insufficient

    preserve:
        majority view
        minority reports
        unresolved claims
        source correlation

    return ConsensusBundle
```

Rules:

```text
consensus != truth
model confidence != epistemic certainty
cryptographic integrity != empirical truth
```

Authority recomputes epistemic status from raw EvidenceBundles.

---

## 6. Many-worlds / branch archive

"Many worlds" is implemented as design/candidate lineage, not literal quantum mechanics.

```text
CandidateBranch:
    candidate_id
    parent_candidate_id
    hypothesis
    mutation
    environment
    benchmark_vector
    risk_vector
    artifacts
    failure_reason
    status

for candidate in candidate_branches:
    run sealed evaluation
    preserve result whether pass or fail

if candidate dominates champion under declared benchmark policy:
    propose promotion
else:
    archive branch

future candidates may recombine motifs from archived branches
```

Alternative hypotheses also coexist in the Model Graph with `competes_with`.

---

## 7. Adaptive deliberation

```text
if consequence low AND uncertainty low:
    FAST:
        minimal retrieval
        direct response / standing-scope reversible tool
elif expected_information_gain > compute_cost:
    DEEP:
        N hypotheses
        retrieval
        deterministic tools
        counterfactual simulation
        critic
        verifier
else:
    GOVERNED:
        all deep steps
        formal Claim
        explicit Proposal
        Authority review
```

Termination:

```text
continue_reasoning only if:
    expected_decision_improvement > marginal_compute_cost
OR
    unresolved_high_consequence_constraint exists
```

---

## 8. Authority path

```text
Gatekeeper.evaluate(Proposal, raw EvidenceBundles, state):
    0. constitutional pre-check
    1. recompute epistemic certainty; ignore proposer confidence as authority
    2. recompute RiskRecord
    3. recompute ConstraintRecord
    4. evaluate invariants
    5. arbitrate
    6. append signed Decision
    return Approval | Denial

CapabilityBroker.mint(Approval):
    for each approved capability:
        mint token {
            capability,
            scope,
            budget,
            issued_at,
            expires_at,
            nonce,
            approval_ref
        }
```

---

## 9. Actuation path

```text
Runtime.execute(token, action):
    verify token signature
    verify capability
    verify scope
    verify budget
    verify expiry
    verify nonce unused
    execute in constrained runtime
    record OutcomeAttestation
    return Outcome
```

Production target: Wasm/gVisor/isolated subprocesses depending on substrate.

---

## 10. Outcome → learning

```text
Outcome
  -> residual(prediction, measurement)
  -> anomaly detection
  -> update Claim/Hypothesis support
  -> create LearningCandidate

LearningCandidate NEVER edits live core directly.
```

---

## 11. Sealed self-improvement

```text
sealed_promote(candidate):
    detect measurable failure/opportunity
    state hypothesis
    generate smallest change
    create isolated worktree/environment
    run:
        unit
        integration
        security
        safety
        latency
        domain
        regression
        resource
        adversarial tests
    compare benchmark vector with champion
    reject forbidden permission expansion
    require explicit authorization for:
        permissions
        spending
        persistence
        external network reach
        external actuation
    if policy passes:
        sign candidate
        canary deploy
        monitor
        promote
    if health gate fails:
        rollback
```

Protected evaluator code, constitutional invariants, signing keys and hidden tests are outside candidate mutation authority.

---

## 12. Domain packs

```text
DomainPack:
    schemas
    tools
    models
    evaluators
    risk_policy
    memory_staleness
    benchmarks
    capabilities
```

A pack may specialize cognition but may not expand the universal authority surface by itself.

Initial packs:
- Research
- Coding
- Trading
- Media
- Cybersecurity
- Personal Operations

Trading-specific mathematics such as Kelly allocation stays inside Trading policy, not the universal Constitution.

---

## 13. Resource arbitration

```text
P0 = operator / audio / OS liveness
P1 = interactive inference and current tools
P2 = vision / documents / simulations
P3 = background training / indexing / self-evaluation

scheduler:
    preempt P3 for P0/P1
    P3 must checkpoint
    consider:
        unified memory
        CPU/GPU utilization
        thermal state
        battery/AC
        audio deadline
        foreground interaction
        context/model footprint
        deadline
        expected value of compute
```

---

## 14. Multimodal presence

Continuous sensing != continuous expensive inference.

```text
audio:
    VAD/wake/light STT
    escalate on semantic relevance

vision:
    change/novelty detector
    escalate selected frames/crops

desktop:
    accessibility tree first
    pixels second

portal:
    render(system_state) as:
        avatar
        generated video
        document
        diagram
        chart
        tool
        workspace
```

The renderer never becomes the cognitive core.


---

# Implementation Plan

## Phase A — executable nucleus
1. Canonical object schemas
2. Event stream
3. Model-graph projection
4. separate Authority service/process
5. capability broker
6. token-gated runtime
7. negative tests proving Proposal cannot actuate

## Phase B — cognition
1. local model adapter
2. retrieval
3. EvidenceBundle builder
4. adaptive deliberation
5. hypothesis/claim graph
6. whole-paper Research Pack

## Phase C — evolution
1. isolated candidate worktrees
2. benchmark registry
3. champion/archive
4. signed promotion manifest
5. canary deployment
6. rollback

## Phase D — resource and presence
1. P0–P3 scheduler
2. system telemetry
3. audio VAD/STT adapter
4. vision novelty detector
5. portal renderer
6. foreground preemption

## Phase E — cross-AI
1. registry + keys
2. canonical envelopes
3. peer adapters
4. stigmergic graph collaboration
5. deterministic Authority-side consensus bundle
6. source-correlation accounting

## Phase F — DomainPacks
Research first.
Then coding.
Then trading simulator/paper execution.
Only later consider live external actuation under explicit user authorization and independently validated controls.

## Phase G — hardened authority
After the Python semantics and tests stabilize:
- move Gatekeeper/Broker/audit verification to Rust
- asymmetric signatures
- secure key custody
- process sandboxing/Wasm
- secure boot/attestation where supported
- external append-only anchor
