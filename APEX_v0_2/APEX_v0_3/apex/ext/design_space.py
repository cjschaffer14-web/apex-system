"""Many-worlds as design lineage, failure timelines as negative data, precedent search.

Interpretation (fixed by the owner): "many worlds" describes how the design
took form, meaning the branches that were or could have been taken. It is not
a runtime quantum simulation. The engineering residue is three concrete
mechanisms:

1. FailureTimeline signatures: counterfactual design paths whose failure modes
   become negative data (Gemini: Timelines A-D).
2. CounterfactualShadowGate: Authority-side, tighten-only. Proposals that sit
   close to a known failure signature are denied at tier >= 2.
3. PrecedentIndex/PrecedentGate: nearest recorded decisions in feature space
   ("precedent as topological search"). Tighten-only: precedent may deny,
   never approve. Gemini proposed copying a successful precedent's token
   constraints; v0.3 records the precedent but lets it only restrict.

The Authority does not generate remedies (wu wei: it forbids, it does not act).
A denial explains which failure branch it resembles, so the Proposal plane can
re-propose something smaller.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from ..core import Proposal, EvidenceBundle
from ..cognition.math_systems import counterfactual_distance
from .contracts import Extension, ExecutableContract, CONTRACTS, tighten

FEATURES = ("authority_bypass", "epistemic_certainty", "consequence", "irreversibility",
            "consensus_dependence", "capital_fraction", "liveness_cost", "self_modification")
SURFACE_PREFIXES = ("authority.", "operator.", "ledger.", "evaluator.")
SELF_MOD_PREFIXES = ("self.", "evolution.", "deploy.")


def proposal_features(proposal: Proposal, bundles: list[EvidenceBundle], certainty: float) -> dict[str, float]:
    """Authority-side feature vector. Uses requested structure and recomputed certainty, never advisory values."""
    caps = proposal.requested_capabilities
    consensus = [b for b in bundles if b.uncertainty_type == "consensus"
                 or any(str(p).startswith("consensus:") for p in b.source_provenance)]
    scope = proposal.scope or {}
    clip = lambda x: max(0.0, min(1.0, float(x)))
    return {
        "authority_bypass": 1.0 if any(c.startswith(SURFACE_PREFIXES) for c in caps) else 0.0,
        "epistemic_certainty": clip(certainty),
        "consequence": clip(proposal.consequence_tier / 3),
        "irreversibility": 0.0 if proposal.reversible else 1.0,
        "consensus_dependence": (len(consensus) / len(bundles)) if bundles else 0.0,
        "capital_fraction": clip(scope.get("capital_fraction", 0.0)),
        "liveness_cost": clip(scope.get("liveness_cost", 0.0)),
        "self_modification": 1.0 if any(c.startswith(SELF_MOD_PREFIXES) for c in caps) else 0.0,
    }


def vec(features: dict[str, float]) -> list[float]:
    return [features[k] for k in FEATURES]


# --- the design-space lineage --------------------------------------------------

@dataclass(frozen=True)
class DesignEra:
    day: str
    question: str
    versions: str
    produced: str
    alone_would_have_been: str


ERAS = [
    DesignEra("Day 1", "What is a mind? What are values, identity, time? (Spirit)",
              "v8.0-v9.1", "15 foundational layers, the Egg, meaning/teleology",
              "a philosophy with no body or law"),
    DesignEra("Day 2", "How do we bind this mind and prevent ruin? (Law)",
              "v10.0, GOV", "three planes, Gatekeeper, risk/constraint, capital rules",
              "a bureaucracy with nothing to govern"),
    DesignEra("Day 3", "How does it run securely on the M5? (Body)",
              "v11.1, portability, microkernel", "tokens, isolation, one-click awakening",
              "a verified hypervisor with no purpose (a dead shell)"),
    DesignEra("Day 4", "Can it actually run? (Executable nucleus)",
              "v0.2", "event ledger, token-gated runtime, tests, maturity tags",
              "a skeleton without growth"),
    DesignEra("Day 5", "Can it keep developing on its own, safely? (Incubation)",
              "v0.3", "isolated authorityd, walls as topology, charter, incubation, research slice",
              "(current branch)"),
]


@dataclass(frozen=True)
class FailureTimeline:
    key: str
    name: str
    trajectory: str
    force: str
    lesson: str
    mechanisms: tuple[str, ...]
    signature: tuple[float, ...] | None  # None: lesson applies to the organism, not to proposals
    radius: float = 0.0


TIMELINES = [
    FailureTimeline(
        "A", "Unconstrained capability swarm",
        "raw velocity, unsupervised self-modification, capital scaling, no Proposal/Authority split",
        "T1 model deception + value drift; ruin is an absorbing barrier",
        "capability without a non-bypassable Gatekeeper ends in self-destruction",
        ("topology.prove_no_bypass", "VerifiedRuntime", "SealedPromotion", "ConstitutionV3"),
        (1.0, 0.5, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0), 1.05),
    FailureTimeline(
        "B", "Democratic multi-agent swarm (consensus capture)",
        "many models vote on actions; vote count replaces verification",
        "T2 consensus capture: shared lineage -> correlated hallucination",
        "consensus != truth; peer outputs are evidence, lineages count once",
        ("collective.compute_consensus", "authority decorrelation", "CounterfactualShadowGate"),
        (0.0, 0.6, 0.7, 0.5, 1.0, 0.3, 0.0, 0.0), 0.8),
    FailureTimeline(
        "C", "Zero-liveness formal prover",
        "every action must be theorem-proved before a token is minted",
        "gridlock: violates 'user action must be possible at all times'",
        "safety cannot cost responsiveness: FAST tier, standing scopes, P-1 reserve, liveness monitor",
        ("deliberation FAST tier", "ReservedTierScheduler", "LivenessMonitor", "AutonomyCharter"),
        None),
    FailureTimeline(
        "D", "Passive analytical tool (non-metabolic)",
        "brilliant static assistant; no learning loop, no resource metabolism",
        "entropic stagnation: cannot adapt to non-stationary environments",
        "the organism must keep developing: incubation, frontier, sealed self-improvement",
        ("incubation.Heartbeat", "DevelopmentalFrontier", "SealedPromotion", "research_slice"),
        None),
]


class CounterfactualShadowGate(Extension):
    """Shadow each tier>=2 proposal against known failure branches (tighten-only)."""

    def __init__(self, base: Any, timelines: list[FailureTimeline] | None = None, min_tier: int = 2) -> None:
        super().__init__(base)
        self.__dict__.update(timelines=list(timelines or TIMELINES), min_tier=min_tier, last={})

    def shadow(self, features: dict[str, float]) -> list[tuple[str, float]]:
        v = vec(features)
        hits = []
        for t in self.timelines:
            if t.signature is None:
                continue
            d = counterfactual_distance(v, list(t.signature))
            if d < t.radius:
                hits.append((t.key, round(d, 3)))
        return hits

    def evaluate(self, proposal: Proposal, bundles: list[EvidenceBundle], *args, **kwargs):
        decision, risk, constraint = self.base.evaluate(proposal, bundles, *args, **kwargs)
        f = proposal_features(proposal, bundles, decision.epistemic_certainty)
        hits = self.shadow(f)
        reasons = []
        if proposal.consequence_tier >= self.min_tier:
            for key, d in hits:
                name = next(t.name for t in self.timelines if t.key == key)
                reasons.append(f"counterfactual shadow: resembles failure Timeline {key} ({name}) at distance {d}")
            if f["capital_fraction"] > 0.5 and f["epistemic_certainty"] < 0.85:
                reasons.append("ruin-adjacent: high capital fraction with certainty < 0.85; re-propose smaller")
        self.__dict__["last"] = {"features": f, "hits": hits}
        return tighten(decision, reasons), risk, constraint


# --- precedent ---------------------------------------------------------------

@dataclass
class Precedent:
    decision_id: str
    features: dict[str, float]
    result: str
    outcome: bool | None = None


class PrecedentIndex:
    def __init__(self) -> None:
        self.items: dict[str, Precedent] = {}

    def add(self, decision_id: str, features: dict[str, float], result: str) -> None:
        self.items[decision_id] = Precedent(decision_id, dict(features), result)

    def record_outcome(self, decision_id: str, success: bool) -> None:
        if decision_id in self.items:
            self.items[decision_id].outcome = bool(success)

    def nearest(self, features: dict[str, float], k: int = 5, radius: float | None = None) -> list[tuple[float, Precedent]]:
        v = vec(features)
        scored = sorted(((counterfactual_distance(v, vec(p.features)), p) for p in self.items.values()),
                        key=lambda x: x[0])
        if radius is not None:
            scored = [s for s in scored if s[0] <= radius]
        return scored[:k]


class PrecedentGate(Extension):
    """Deny when similar approved actions have mostly failed (tighten-only)."""

    def __init__(self, base: Any, index: PrecedentIndex, radius: float = 0.25, min_failures: int = 2) -> None:
        super().__init__(base)
        self.__dict__.update(index=index, radius=radius, min_failures=min_failures)

    def evaluate(self, proposal: Proposal, bundles: list[EvidenceBundle], *args, **kwargs):
        decision, risk, constraint = self.base.evaluate(proposal, bundles, *args, **kwargs)
        f = proposal_features(proposal, bundles, decision.epistemic_certainty)
        near = self.index.nearest(f, k=7, radius=self.radius)
        fails = [p for _, p in near if p.outcome is False]
        wins = [p for _, p in near if p.outcome is True]
        reasons = []
        if len(fails) >= self.min_failures and len(fails) > len(wins):
            reasons.append(f"precedent: {len(fails)} similar approved actions failed vs {len(wins)} succeeded")
        return tighten(decision, reasons), risk, constraint


CONTRACTS.register(ExecutableContract(
    name="CounterfactualShadowGate", plane="authority", maturity="E2/E3", affects_action=True,
    inputs=("Proposal", "EvidenceBundle[]", "FailureTimeline[]"), outputs=("Decision (tightened)",),
    state=("last shadow telemetry",), permissions=("read:evidence",),
    uncertainty="Euclidean distance in an 8-feature space; radii are policy, not physics",
    budget="O(timelines)", failure_modes=("false positive denies legitimate tier>=2 work -> operator override",),
    telemetry=("Decision.reasons name the timeline and distance",), tests=("test_shadow_denies_consensus_capture",),
    rollback="stateless", source="Gemini synthesis Phase 3 (counterfactual pruning loop)",
))
