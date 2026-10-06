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
