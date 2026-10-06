# Many worlds: how the design took form — E3/E4

The owner's correction: many worlds is an **interpretation of how the blocks took form**, not a runtime quantum simulation. Its engineering residue is lineage and negative data.

## Three (now five) days
| Day | Question | Versions | Alone it would have been |
|---|---|---|---|
| 1 Spirit | What is a mind? values, identity, time | v8.0–v9.1 (15 layers, Egg) | a philosophy with no body or law |
| 2 Law | How do we bind it and prevent ruin? | v10, GOV (planes, Gatekeeper, risk) | a bureaucracy with nothing to govern |
| 3 Body | How does it run securely on the M5? | v11.1 (tokens, isolation, awakening) | a verified hypervisor with no purpose |
| 4 Nucleus | Can it actually run? | v0.2 | a skeleton without growth |
| 5 Incubation | Can it keep developing safely on its own? | v0.3 | (current branch) |

Asking Day 3 questions on Day 1 would have produced an excellent dead shell. The order was Spirit, then Law, then Body.

## Failure timelines (negative data, `design_space.TIMELINES`)
* **A Unconstrained capability swarm**: no Proposal/Authority split → value drift, ruin. Lesson: a non-bypassable Gatekeeper.
* **B Consensus capture**: votes replace verification; shared lineages hallucinate together (T2). Lesson: consensus ≠ truth; lineages count once.
* **C Zero-liveness formal prover**: everything theorem-proved → gridlock. Lesson: FAST tier, P-1 reserve, liveness monitor, charter.
* **D Passive analytical tool**: no metabolism, no learning → stagnation. Lesson: incubation, frontier, sealed self-improvement.

A and B have feature signatures. Tier ≥ 2 proposals near them are denied by `CounterfactualShadowGate`. C and D shape the organism itself.

## Wiser guys, convergent worlds
Object capabilities (Miller, Hewitt) → tokens and zero ambient authority. seL4 (Liedtke, Heiser) → tiny authorityd. Lamport → logical clocks and the hash chain. Friston → Markov blanket and active inference. Beer → VSM. Ostrom → polycentric packs. Lawvere → typed morphisms and composition checks. Varela → enactive reversible probes. von Foerster → second-order observer. Sebeok → signals interpreted by channel.

## Common mathematical threads
1. **DAGs / causality**: authority flows down, evidence flows up; the ledger is a causal chain.
2. **Information theory**: authority scales inversely with uncertainty; recompute certainty, never trust stated confidence.
3. **Ergodicity**: survive in time, not on average; ruin is an absorbing barrier.

**Are we on the superior path?** It can't be proved. What can be shown is that the design avoids known absorbing failures and keeps options open: every branch is archived, every promotion can roll back, and every claim is tested.

## In code
Lineage is concrete: `CandidateV3(parent, mutation, environment, benchmark_vector, failure_reason, status)`. Archived branches give `SealedPromotion.motifs()` for recombination.
