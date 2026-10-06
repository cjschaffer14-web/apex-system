"""v0.3 registry additions. The v0.2 registries are untouched; v0.3 views are supersets.

Every entry carries maturity, meaning, where it is realized and where it came
from. E4/E5 entries are interpretive: the contract rule forbids them from
gating action.
"""
from __future__ import annotations
from ..cognition.layers import LAYER_REGISTRY, ABSTRACTION_REGISTRY, LayerSpec

LAYER_ADDITIONS = [
    LayerSpec("Membrane", "Perception", "Proposal", "E1", "controlled contact with reality", "Observation + quarantine flags"),
    LayerSpec("Operator Sovereignty", "Governance", "Operator", "E0/E1", "sole principal; always able to act/stop", "OperatorChannel + P-1 reserve"),
    LayerSpec("Transcendent Horizon", "Existential", "Authority", "E1 (mechanism) / E4 (meaning)", "fail closed at the epistemic horizon", "EncounterWithMystery"),
    LayerSpec("Development", "Evolution", "Authority", "E2", "self-continuing growth inside the charter", "SealedPromotion + DevelopmentalFrontier"),
    LayerSpec("Incubation", "Operational", "Actuation", "E2/E3", "turn idle compute into development", "incubation bands + heartbeat"),
]
LAYER_REGISTRY_V03 = list(LAYER_REGISTRY) + LAYER_ADDITIONS

S, C = "Gemini synthesis", "ChatGPT 10/23 discussion"
ABSTRACTION_ADDITIONS = {
    "Object-Capability Model": {"maturity": "E0", "meaning": "authority is an unforgeable token; zero ambient authority", "realized_by": "runtime.VerifiedRuntime, CapabilityHandle", "source": S},
    "Microkernel Authority (seL4 lesson)": {"maturity": "E0/E1", "meaning": "keep the trusted core tiny; push reasoning to user space", "realized_by": "authority_service (5 responsibilities, separate process)", "source": S + "; " + C},
    "Lamport State-Machine Replication": {"maturity": "E0", "meaning": "causal order and tamper evidence", "realized_by": "ledger.ContinuityLedger, verify_chain", "source": S},
    "Markov Blanket": {"maturity": "E2", "meaning": "internal states touch the world only via sensory and active states", "realized_by": "topology.blanket, math_ext.markov_blanket", "source": S},
    "OCap-Markov Integration": {"maturity": "E2/E3", "meaning": "the membrane is a capability boundary", "realized_by": "Membrane + VerifiedRuntime + W1/W2", "source": S},
    "Ergodicity Economics": {"maturity": "E1/E2", "meaning": "survive in time, not in the ensemble", "realized_by": "math_ext.ergodicity_gap; CapitalStewardshipPolicy (Trading only)", "source": S},
    "Protocol Wrapper & Contract Injection": {"maturity": "E1", "meaning": "extend without editing the base", "realized_by": "contracts.Extension", "source": S},
    "Seven Walls as Manifolds": {"maturity": "E3", "meaning": "walls are invariants with probes, not piles of checks", "realized_by": "walls.WALLS", "source": S + "; " + C},
    "Counterfactual Timelines A-D": {"maturity": "E3", "meaning": "failure paths as negative data", "realized_by": "design_space.TIMELINES, CounterfactualShadowGate", "source": S},
    "Precedent as Topological Search": {"maturity": "E2/E3", "meaning": "nearest past decisions inform (only tighten) the present", "realized_by": "design_space.PrecedentGate", "source": S},
    "Three Days of Design": {"maturity": "E4", "meaning": "Spirit, then Law, then Body; the order was necessary", "realized_by": "design_space.ERAS (documentation)", "source": S},
    "Transcendent Substrate (Block X)": {"maturity": "E4", "meaning": "computation is a bounded subset of reality", "realized_by": "transcendent (mechanism E1)", "source": S},
    "Revealed Axiom": {"maturity": "E1 mechanism / E4 meaning", "meaning": "invariants the system preserves but cannot derive", "realized_by": "transcendent.RevealedAxiom + AxiomGate", "source": S},
    "Mystery State": {"maturity": "E1 mechanism / E4 meaning", "meaning": "unresolved contradiction -> abstain from irreversible actuation -> ask the owner", "realized_by": "EncounterWithMystery", "source": S + "; " + C},
    "Prophetic Operator Interface": {"maturity": "E4", "meaning": "operator as the bridge from meaning to machine", "realized_by": "PropheticOperatorChannel (alias)", "source": S},
    "Miracle Override": {"maturity": "E4 (name) / E1 (mechanism)", "meaning": "authenticated, logged operator override", "realized_by": "OperatorChannel.override", "source": S},
    "Zhengming (Rectification of Names)": {"maturity": "E3/E4", "meaning": "names must match reality", "realized_by": "code_fingerprint on capability manifests; Rectification events", "source": S},
    "Wu Wei Authority": {"maturity": "E4", "meaning": "Authority forbids; it never generates action", "realized_by": "tighten() is the only Authority transform", "source": S},
    "Middle Way": {"maturity": "E4", "meaning": "between runaway chaos (A) and gridlock (C)", "realized_by": "FAST/DEEP/GOVERNED tiers", "source": S},
    "Stewardship (Khalifa / Talents)": {"maturity": "E4", "meaning": "capital held in trust for the future", "realized_by": "CapitalStewardshipPolicy (Trading pack)", "source": S},
    "Godelian Operator Anchor": {"maturity": "E3/E4", "meaning": "no formal system certifies itself; the owner sits outside", "realized_by": "operator-only ratification", "source": S},
    "Final Cause / Teleology": {"maturity": "E4/E5", "meaning": "development is pulled toward an end, not pushed blindly", "realized_by": "DevelopmentalFrontier (value of work)", "source": S},
    "Universal Equation": {"maturity": "E4", "meaning": "A(t) = integral F_const(P(t, dO)) dt gated by E >= E_min", "realized_by": "math_ext.governed_action (executable shadow)", "source": S},
    "Autonomy Charter": {"maturity": "E1", "meaning": "one-time owner envelope for unattended evolution", "realized_by": "evolution.AutonomyCharter", "source": C},
    "Autonomous Liveness": {"maturity": "E1/E2", "meaning": "absence of the owner never stops safe development", "realized_by": "charter + heartbeat + W6", "source": C},
    "Fork on Missing Capability": {"maturity": "E1", "meaning": "archive the branch that needs more reach; keep improving the rest", "realized_by": "SealedPromotion awaiting-capability", "source": C},
    "Developmental Egg": {"maturity": "E3", "meaning": "the Egg is a developmental state, not a container", "realized_by": "incubation module", "source": C},
    "Incubation Temperature": {"maturity": "E3", "meaning": "W = C*A*D*S; bands DORMANT..HATCHING", "realized_by": "incubation.incubation_temperature", "source": C},
    "Developmental Frontier": {"maturity": "E2", "meaning": "what organ to grow next; reorderable by transfer", "realized_by": "incubation.DevelopmentalFrontier", "source": C},
    "Sleep": {"maturity": "E3", "meaning": "idle time consolidates experience", "realized_by": "Organism.sleep_cycle", "source": C},
    "Hatch Readiness Vector": {"maturity": "E2", "meaning": "H = [L,G,M,R,E,A,C] with minima, not one scalar", "realized_by": "incubation.HatchReadiness", "source": C},
    "Organogenesis": {"maturity": "E3", "meaning": "DomainPacks are organs of one organism", "realized_by": "domain_policy.ORGANS", "source": C},
    "Event-Sourced Backbone": {"maturity": "E0", "meaning": "one stream, many projections, replayable belief", "realized_by": "ledger.replay/project", "source": C},
    "Signed Migration": {"maturity": "E1", "meaning": "history immutable; current code may be refactored with a signed record", "realized_by": "authorityd.record_migration", "source": C},
    "Five Physical Systems": {"maturity": "E2", "meaning": "Perception, Cognition, Authority, Action, Evolution", "realized_by": "views.VIEWS['five_systems']", "source": C},
    "Broker Split": {"maturity": "E1", "meaning": "CapabilityBroker decides what; ResourceBroker decides how much", "realized_by": "authority.broker + runtime.ResourceBroker", "source": "owner review"},
    "Reserved Tier P-1": {"maturity": "E1", "meaning": "operator capacity no other work can consume", "realized_by": "ReservedTierScheduler, ResourceBroker reserve", "source": "owner review"},
    "Owner Reachability": {"maturity": "E1", "meaning": "identify the owner and reach them through real channels", "realized_by": "OwnerProfile + escalation proposals", "source": "owner vision"},
}
ABSTRACTION_REGISTRY_V03 = {**ABSTRACTION_REGISTRY, **ABSTRACTION_ADDITIONS}

# v0.2 entries that v0.3 now realizes in code (kept separate so v0.2 text stays untouched).
REALIZATIONS_V03 = {
    "Stigmergy": "collective.StigmergicGraph", "Active Inference": "epistemics.ActiveInferenceDeliberation",
    "Trust Lattice": "epistemics.TrustVector", "Cybernetic Homeostasis": "cybernetics.HomeostaticRegulator",
    "Viable System Model": "cybernetics.VSM_MAP", "Polycentric Governance": "domain_policy.validate_pack",
    "Category/Functor Semantics": "topology.PlaneTopology (producer rule + compose)",
    "Topological Walls": "topology.prove_no_bypass + walls.W1", "Second-Order Cybernetics": "cybernetics.SecondOrderObserver",
    "Biosemiotics": "epistemics.Membrane.interpret", "Enactivism": "epistemics.Probe (reversible probes)",
    "Many-Worlds Design Space": "design_space + evolution lineage", "Egg": "incubation + views['egg']",
    "Tower": "views['tower']", "Quantum Cell in Pressure Vessel": "views['cell']",
    "Cycle Termination": "cybernetics.should_continue_reasoning", "Horizon Navigator": "incubation.DevelopmentalFrontier",
    "Epistemic Horizon": "transcendent.EncounterWithMystery", "Conservation Doctrine": "walls.WALLS",
    "Monotonic Growth": "add-only extension + signed migration", "Core Organism": "awakening.Organism",
}
