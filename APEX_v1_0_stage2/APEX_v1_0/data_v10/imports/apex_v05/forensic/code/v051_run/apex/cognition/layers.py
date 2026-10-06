from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class LayerSpec:
    name: str
    level: str
    plane: str
    maturity: str
    purpose: str
    operational_contract: str


LAYER_REGISTRY = [
    LayerSpec("Measurement","Foundational","Proposal","E0/E1","measure with error/calibration","Observation + error_model"),
    LayerSpec("Temporal Ontology","Foundational","Proposal","E1","bind moments, causal order, urgency","logical_time + temporal projection"),
    LayerSpec("Identity","Foundational","Proposal","E1/E2","persistence and self/other boundaries","identity/provenance record"),
    LayerSpec("Axiological","Foundational","Proposal","E2/E3","explicit values and tradeoffs","Value nodes; Authority enforces ratified subset"),
    LayerSpec("Praxeological","Foundational","Proposal","E2/E3","agency, intention, responsibility","Proposal + responsibility metadata"),
    LayerSpec("Epistemic","Cognitive","Proposal","E1/E2","justification, ignorance, evidence","EvidenceBundle + Claim"),
    LayerSpec("Semiotic","Cognitive","Proposal","E2/E3","meaning, symbols, negotiation","Symbol nodes + referent relations"),
    LayerSpec("Social","Cognitive","Proposal","E2/E3","other agents, cooperation, incentives","Agent models; no authority from consensus"),
    LayerSpec("Embodiment","Experiential","Proposal","E2/E3","sensorimotor coupling and affordances","Observation/action residuals"),
    LayerSpec("Aesthetic","Experiential","Proposal","E3/E4","judgment of form/elegance","advisory preference signal"),
    LayerSpec("Soteriological","Existential","Proposal","E4","harm/loss/redemption abstraction","advisory conceptual view"),
    LayerSpec("Thanatological","Existential","Proposal","E4","finitude, legacy, continuity","continuity/retirement metadata"),
    LayerSpec("Metaphysical","Existential","Proposal","E4/E5","limits, infinity, sacred/unknown","unknown/limit declarations"),
    LayerSpec("Meta-Epistemic","Reflective","Proposal","E2/E3","detect missing/unknown/unrepresented","open questions + uncertainty gaps"),
    LayerSpec("Meta-Theoretical","Reflective","Proposal","E2/E3","theory, explanation, prediction, emergence","Hypothesis/Abstraction nodes"),
    LayerSpec("Attention","Governance-adjacent","Proposal","E1","allocate cognitive bandwidth","priority/expected-value records"),
    LayerSpec("Compression","Governance-adjacent","Proposal","E1/E2","consolidate with declared loss","CompressionRecord"),
    LayerSpec("Federated Cognition","Governance-adjacent","Proposal","E2","peer proposals from multiple models","signed untrusted envelopes"),
    LayerSpec("Collective Intelligence","Governance-adjacent","Proposal","E2/E3","aggregate perspectives without equating consensus to truth","ConsensusBundle as evidence"),
    LayerSpec("Reliability","Operational","Actuation","E0/E1","rollback/checkpoint/degradation","checkpoint + rollback"),
    LayerSpec("Security","Operational","Authority","E0/E1","authn/authz/integrity/attestation","deny-by-default policy"),
    LayerSpec("Risk","Operational","Authority","E1","probability/impact/blast radius","RiskRecord"),
    LayerSpec("Constraint","Operational","Authority","E0/E1","resource/capital/compute bounds","ConstraintRecord"),
    LayerSpec("Governance","Operational","Authority","E1/E2","decision arbitration","Decision"),
]

# Earlier and higher-order abstractions are retained as views/contracts.
ABSTRACTION_REGISTRY = {
    "Core Organism": {"maturity":"E3", "meaning":"minimal persistent perceive-reason-act-learn loop"},
    "Monotonic Growth": {"maturity":"E3/E4", "meaning":"historical lineage remains recoverable; current implementation may refactor through signed migration"},
    "Fractal Duality": {"maturity":"E4", "meaning":"complementary representations at multiple scales"},
    "Embodied Metaphor": {"maturity":"E4", "meaning":"metaphor as an interpretive view, never direct authority"},
    "Epistemic Horizon": {"maturity":"E3/E4", "meaning":"explicit boundary between modeled and unknown"},
    "Scale Transition": {"maturity":"E3", "meaning":"detect when reasoning scale/model must change"},
    "Cycle Termination": {"maturity":"E2/E3", "meaning":"stop reasoning when marginal value falls below cost/criterion"},
    "Horizon Navigator": {"maturity":"E3", "meaning":"select next frontier/open question"},
    "Somatic Algebra": {"maturity":"E4/E5", "meaning":"body/resource-state abstraction; source incomplete in supplied corpus"},
    "Trust Lattice": {"maturity":"E2/E3", "meaning":"partial-order trust relations rather than one scalar trust score"},
    "Relational Ethics": {"maturity":"E3/E4", "meaning":"contextual relation-based value reasoning; advisory unless ratified"},
    "Conservation Doctrine": {"maturity":"E3/E4", "meaning":"preserve critical invariants/resources across transformation"},
    "Egg": {"maturity":"E4", "meaning":"Shell=persistence, Yolk=invariants, White=reserves, Membrane=boundary"},
    "Tower": {"maturity":"E4", "meaning":"Observatory=Proposal, Core=Authority, Street=Actuation"},
    "Topological Walls": {"maturity":"E3/E4", "meaning":"security invariants realized as impossible/mediated edges"},
    "Many-Worlds Design Space": {"maturity":"E3/E4", "meaning":"candidate lineage and counterfactual branches, not literal quantum mechanics"},
    "Quantum Cell in Pressure Vessel": {"maturity":"E4", "meaning":"unifying metaphor for generative interior + constrained actuation"},
    "Cybernetic Homeostasis": {"maturity":"E2", "meaning":"feedback loops maintain state inside viability bounds"},
    "Viable System Model": {"maturity":"E2/E3", "meaning":"recursive operational regulation without granting subunits sovereign authority"},
    "Stigmergy": {"maturity":"E2", "meaning":"agents coordinate by graph traces rather than chat consensus"},
    "Active Inference": {"maturity":"E2", "meaning":"choose low-risk probes that reduce uncertainty"},
    "Polycentric Governance": {"maturity":"E2/E3", "meaning":"DomainPacks have local policy within global invariants"},
    "Category/Functor Semantics": {"maturity":"E3", "meaning":"pipeline should preserve typed contracts across transformations"},
    "Enactivism": {"maturity":"E3", "meaning":"world-model updated through bounded sensorimotor interaction"},
    "Second-Order Cybernetics": {"maturity":"E3", "meaning":"system records and audits its own observing/evaluating processes"},
    "Biosemiotics": {"maturity":"E3/E4", "meaning":"signals interpreted by context/provenance rather than treated as raw truth"},
}
