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
