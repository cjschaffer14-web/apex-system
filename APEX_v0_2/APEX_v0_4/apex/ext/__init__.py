"""APEX v0.3 — extension layer over the v0.2 executable core.

Add-only rule
-------------
Nothing in this package edits a v0.2 file. Every v0.3 capability wraps,
subclasses or composes a v0.2 object (the "Protocol Wrapper & Contract
Injection" pattern). The v0.2 files stay byte-identical; tests verify this
against MANIFEST_V0_2.json at the package root.

Module map
----------
contracts          ExecutableContract + Extension wrapper base + tighten() (the add-only mechanism)
ledger             chain verification, Lamport continuity, replay + projections, file manifests (Shell)
topology           plane graph, morphism producer rule, composition, no-bypass proof, blankets
walls              the Seven Walls as abstract invariant manifolds with executable probes
authority_service  authorityd: 5 responsibilities, separate process, owns keys/evidence/audit
runtime            VerifiedRuntime (signature/scope/budget/manifest) + ResourceBroker (broker split)
scheduler          ReservedTierScheduler (P-1 operator reserve, preemption, checkpoint)
operator_channel   owner identity + reachability, halt/override/ratify/rectify/charter
transcendent       Block X: EncounterWithMystery, RevealedAxiom, AxiomGate, reverence wrapper
epistemics         Membrane, TrustVector lattice, active inference, compression, layer vectors
collective         Envelope v2, consensus-as-evidence (lineage counts once), stigmergy, PeerRouter
evolution          SealedPromotion, AutonomyCharter, fork-on-missing-capability, motifs
design_space       design eras, failure timelines A-D, counterfactual shadow, precedent gate
cybernetics        second-order observer, liveness monitor, homeostasis, termination, VSM
domain_policy      pack validation, CapitalStewardshipPolicy (Trading only), new packs, organs
math_ext           JS divergence, conditional entropy, ergodicity, ruin, blanket, value of work
incubation         body model, warmth, bands, frontier, hatch readiness, permeability ladder
research_slice     Research Pack vertical slice (document graph -> answer -> benchmark)
registry_ext       v0.3 additions to the layer/abstraction registries (add-only supersets)
views              Egg / Tower / Cell / Manifold / Markov / Five Systems / Design-space views
awakening          Organism: one-click awakening, heartbeat, sleep, morning report, hatching
"""
__version__ = "0.3.0"
BASE_VERSION = "0.2.0"
