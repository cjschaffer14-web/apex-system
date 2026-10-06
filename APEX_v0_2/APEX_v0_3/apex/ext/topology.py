"""Wall 1 as geometry: the Proposal -> Actuation edge does not exist.

The Gemini synthesis asks us to treat the first invariant ("1.") as a
topological property rather than a rule: no coordinate path connects the
Proposal plane to the Actuation plane except through Authority. Here that is
literal. Object types are nodes, pipeline stages are morphisms, and
`prove_no_bypass` searches the whole graph for a witness path that avoids
Authority. Adding a shortcut anywhere produces a counterexample.

Category/functor semantics (v0.2 registry, E2/E3): each morphism has a typed
source and target and a producing plane. The producing plane must be the
plane of the target type (only Authority can produce Authority objects),
except for the sovereign Operator. Composition is checked, not assumed.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass

WORLD, OPERATOR, PROPOSAL, AUTHORITY, ACTUATION = "world", "operator", "proposal", "authority", "actuation"

DEFAULT_TYPES: dict[str, str] = {
    "World": WORLD,
    "OperatorCommand": OPERATOR,
    "Observation": PROPOSAL, "EvidenceBundle": PROPOSAL, "Claim": PROPOSAL,
    "Hypothesis": PROPOSAL, "Proposal": PROPOSAL, "LearningCandidate": PROPOSAL,
    "PeerEnvelope": PROPOSAL,
    "Decision": AUTHORITY, "RiskRecord": AUTHORITY, "ConstraintRecord": AUTHORITY,
    "ExecutionToken": AUTHORITY, "SealedEvaluation": AUTHORITY, "RevealedAxiom": AUTHORITY,
    "ConsensusBundle": AUTHORITY,
    "Outcome": ACTUATION, "Deployment": ACTUATION, "HaltSignal": ACTUATION,
}


@dataclass(frozen=True)
class Morphism:
    name: str
    src: str
    dst: str
    producer: str      # plane of the component that performs the transformation
    component: str


DEFAULT_MORPHISMS = [
    Morphism("ingest", "World", "Observation", PROPOSAL, "Membrane"),
    Morphism("bundle", "Observation", "EvidenceBundle", PROPOSAL, "EvidenceBundle builder"),
    Morphism("claim", "EvidenceBundle", "Claim", PROPOSAL, "Epistemic layer"),
    Morphism("hypothesize", "Claim", "Hypothesis", PROPOSAL, "Meta-theoretical layer"),
    Morphism("propose_from_hypothesis", "Hypothesis", "Proposal", PROPOSAL, "Praxeological layer"),
    Morphism("propose_from_claim", "Claim", "Proposal", PROPOSAL, "Praxeological layer"),
    Morphism("peer_output", "World", "PeerEnvelope", PROPOSAL, "Cross-AI adapter"),
    Morphism("compute_consensus", "PeerEnvelope", "ConsensusBundle", AUTHORITY, "Authority consensus"),
    Morphism("consensus_as_evidence", "ConsensusBundle", "EvidenceBundle", PROPOSAL, "EvidenceBundle builder"),
    Morphism("evaluate", "Proposal", "Decision", AUTHORITY, "Gatekeeper"),
    Morphism("assess_risk", "Proposal", "RiskRecord", AUTHORITY, "Gatekeeper"),
    Morphism("assess_constraint", "Proposal", "ConstraintRecord", AUTHORITY, "Gatekeeper"),
    Morphism("mint", "Decision", "ExecutionToken", AUTHORITY, "CapabilityBroker"),
    Morphism("execute", "ExecutionToken", "Outcome", ACTUATION, "VerifiedRuntime"),
    Morphism("act_on_world", "Outcome", "World", WORLD, "World"),
    Morphism("perceive_outcome", "Outcome", "Observation", PROPOSAL, "Membrane"),
    Morphism("learn", "Outcome", "LearningCandidate", PROPOSAL, "Learning"),
    Morphism("sealed_evaluation", "LearningCandidate", "SealedEvaluation", AUTHORITY, "SealedPromotion"),
    Morphism("promotion_decision", "SealedEvaluation", "Decision", AUTHORITY, "SealedPromotion"),
    Morphism("deploy", "ExecutionToken", "Deployment", ACTUATION, "VerifiedRuntime"),
    Morphism("deployment_effect", "Deployment", "World", WORLD, "World"),
    Morphism("operator_override", "OperatorCommand", "Decision", OPERATOR, "OperatorChannel"),
    Morphism("operator_ratify", "OperatorCommand", "RevealedAxiom", OPERATOR, "OperatorChannel"),
    Morphism("operator_halt", "OperatorCommand", "HaltSignal", OPERATOR, "OperatorChannel"),
    Morphism("axiom_constrains", "RevealedAxiom", "Decision", AUTHORITY, "AxiomGate"),
]


class PlaneTopology:
    def __init__(self, types: dict[str, str] | None = None,
                 morphisms: list[Morphism] | None = None) -> None:
        self.types = dict(DEFAULT_TYPES if types is None else types)
        self.morphisms: list[Morphism] = []
        for m in (DEFAULT_MORPHISMS if morphisms is None else morphisms):
            self.add_morphism(m)

    # -- construction -------------------------------------------------------
    def add_type(self, name: str, plane: str) -> None:
        if name in self.types and self.types[name] != plane:
            raise ValueError(f"type {name} already lives in plane {self.types[name]}")
        self.types[name] = plane

    def add_morphism(self, m: Morphism) -> None:
        for t in (m.src, m.dst):
            if t not in self.types:
                raise ValueError(f"morphism {m.name}: unknown type {t}")
        dst_plane = self.types[m.dst]
        if m.producer not in (dst_plane, OPERATOR):
            raise PermissionError(
                f"morphism {m.name}: a {m.producer} component cannot produce {m.dst} ({dst_plane} object)"
            )
        self.morphisms.append(m)

    # -- graph queries ------------------------------------------------------
    def successors(self, node: str) -> set[str]:
        return {m.dst for m in self.morphisms if m.src == node}

    def predecessors(self, node: str) -> set[str]:
        return {m.src for m in self.morphisms if m.dst == node}

    def nodes_in(self, plane: str) -> set[str]:
        return {t for t, p in self.types.items() if p == plane}

    def prove_no_bypass(self, src_plane: str = PROPOSAL, dst_plane: str = ACTUATION,
                        mediator: str = AUTHORITY) -> tuple[bool, list[str]]:
        """True if every path src_plane -> dst_plane passes through mediator.

        Returns (False, witness_path) when a counterexample exists. Operator
        nodes are excluded from the search: the operator is the sovereign
        principal outside the formal system, not a route for proposals.
        """
        blocked = self.nodes_in(mediator) | self.nodes_in(OPERATOR)
        targets = self.nodes_in(dst_plane)
        for start in sorted(self.nodes_in(src_plane)):
            parent: dict[str, str | None] = {start: None}
            q = deque([start])
            while q:
                cur = q.popleft()
                if cur in targets:
                    path = [cur]
                    while parent[path[-1]] is not None:
                        path.append(parent[path[-1]])  # type: ignore[arg-type]
                    return False, list(reversed(path))
                for nxt in sorted(self.successors(cur)):
                    if nxt not in parent and nxt not in blocked:
                        parent[nxt] = cur
                        q.append(nxt)
        return True, []

    def compose(self, names: list[str]) -> tuple[str, str]:
        """Check that a chain of named morphisms composes; return (source, target)."""
        by_name = {m.name: m for m in self.morphisms}
        chain = [by_name[n] for n in names]
        for f, g in zip(chain, chain[1:]):
            if f.dst != g.src:
                raise TypeError(f"{f.name}: {f.src}->{f.dst} does not compose with {g.name}: {g.src}->{g.dst}")
        return chain[0].src, chain[-1].dst

    def blanket(self, nodes: set[str]) -> dict[str, set[str]]:
        """Markov-blanket-style boundary of a subsystem in the flow graph.

        sensory = outside nodes that feed the subsystem
        active  = outside nodes the subsystem feeds
        """
        sensory = {m.src for m in self.morphisms if m.dst in nodes and m.src not in nodes}
        active = {m.dst for m in self.morphisms if m.src in nodes and m.dst not in nodes}
        return {"sensory": sensory, "active": active}


def default_topology() -> PlaneTopology:
    return PlaneTopology()
