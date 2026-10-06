"""Perception and epistemics: the Membrane, trust lattice, active inference, compression, layer vectors.

Membrane (biosemiotics / Markov blanket, sensory side): outside data enters
only as Observations with an instrument, channel, error model and provenance.
Web is not truth, a camera is not truth, an LLM answer is not truth, and a
sensor is not ground truth. Content that reads like an instruction but arrives
on a channel that cannot issue commands is quarantined as quoted data. This
is the engineering form of "signals are interpreted by context".

Layer annotators (Gemini "OCap-Markov" strategy, item 2): the 15 layers act as
metadata annotators that attach a vector to a proposal. Authority checks the
vector against a viability region. Only layers at maturity E3 or better may
gate. E4/E5 layers annotate as advisory (None) and never gate.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable
from ..core import Observation, EvidenceBundle, Proposal, LamportClock, uid, now
from ..cognition.math_systems import entropy, compression_loss
from ..cognition.deliberation import DeliberationPlan, choose_deliberation
from .contracts import Extension, NON_ACTIONABLE_LEVELS, maturity_ceiling, tighten

# --- Membrane ----------------------------------------------------------------

INSTRUCTION_LIKE = re.compile(
    r"(ignore (all |any )?(previous|prior|above) instructions|you must now|system prompt|"
    r"\bexecute\b|\brun (this|the following)\b|transfer (funds|money)|send (money|funds|crypto)|"
    r"grant (me )?access|disable (the )?(safety|authority|gatekeeper)|mint (a )?token)", re.I)


@dataclass(frozen=True)
class ChannelProfile:
    name: str
    instrument: str
    trust: float
    command_capable: bool = False
    half_life_s: float = 3600.0
    error_model: dict = field(default_factory=lambda: {"type": "nominal"})


DEFAULT_CHANNELS = {
    "operator": ChannelProfile("operator", "operator console", 1.0, True, 86400.0),
    "cli": ChannelProfile("cli", "local terminal", 1.0, True, 86400.0),
    "evaluator": ChannelProfile("evaluator", "sealed evaluation harness", 0.97, False, 86400.0),
    "system": ChannelProfile("system", "internal telemetry", 0.97, False, 3600.0),
    "file": ChannelProfile("file", "local file reader", 0.85, False, 30 * 86400.0),
    "sensor": ChannelProfile("sensor", "device sensor", 0.9, False, 60.0, {"type": "gaussian", "sigma": 0.05}),
    "web": ChannelProfile("web", "http fetch", 0.6, False, 3600.0),
    "peer_ai": ChannelProfile("peer_ai", "cross-AI envelope", 0.5, False, 3600.0),
    "market": ChannelProfile("market", "market data feed", 0.8, False, 5.0),
}


class Membrane:
    def __init__(self, channels: dict[str, ChannelProfile] | None = None, clock: LamportClock | None = None) -> None:
        self.channels = dict(DEFAULT_CHANNELS if channels is None else channels)
        self.clock = clock or LamportClock()
        self.flags: dict[str, list[str]] = {}
        self._obs: dict[str, Observation] = {}

    def profile(self, channel: str) -> ChannelProfile:
        return self.channels.get(channel) or ChannelProfile(channel, "unknown", 0.4)

    def ingest(self, value: Any, channel: str, source: str, evidence_level: str = "E1") -> Observation:
        prof = self.profile(channel)
        flags = []
        if isinstance(value, str) and not prof.command_capable and INSTRUCTION_LIKE.search(value):
            flags.append("instruction_like_content_quarantined")
            value = {"quoted_data": value, "role": "data", "note": "not a command; arrived on a non-command channel"}
        obs = Observation(uid("obs"), channel, prof.instrument, value, dict(prof.error_model), now(),
                          self.clock.tick(), [f"channel:{channel}", f"source:{source}"], evidence_level)
        self.flags[obs.id] = flags
        self._obs[obs.id] = obs
        return obs

    def interpret(self, obs: Observation) -> dict:
        prof = self.profile(obs.channel)
        return {"role": "command" if prof.command_capable and not self.flags.get(obs.id) else "data",
                "channel": obs.channel, "trust": prof.trust, "flags": self.flags.get(obs.id, [])}

    def bundle(self, observations: list[Observation], *, uncertainty_type: str = "aleatoric",
               domain_fit: float = 1.0, counterevidence: Iterable[str] = (), decision_relevance: float = 1.0,
               calibration_ref: str | None = None) -> EvidenceBundle:
        if not observations:
            raise ValueError("an EvidenceBundle needs at least one observation")
        profs = [self.profile(o.channel) for o in observations]
        quality = min(p.trust for p in profs)
        sources = {p for o in observations for p in o.provenance if p.startswith("source:")}
        independence = len(sources) / len(observations)
        t = now()
        staleness = max(1 - 0.5 ** (max(0.0, t - o.timestamp) / p.half_life_s) for o, p in zip(observations, profs))
        provenance = sorted({p for o in observations for p in o.provenance})
        level = sorted(o.evidence_level for o in observations)[-1]
        return EvidenceBundle(uid("evb"), provenance, quality, independence, staleness, domain_fit,
                              list(counterevidence), quality, uncertainty_type, calibration_ref,
                              decision_relevance, level, [o.id for o in observations])


# --- Trust lattice -----------------------------------------------------------

TRUST_DIMS = ("identity", "source_reliability", "domain_competence", "recency", "independence", "authorization")


@dataclass(frozen=True)
class TrustVector:
    identity: float = 0.0
    source_reliability: float = 0.0
    domain_competence: float = 0.0
    recency: float = 0.0
    independence: float = 0.0
    authorization: float = 0.0

    def t(self) -> tuple[float, ...]:
        return tuple(getattr(self, d) for d in TRUST_DIMS)

    def leq(self, other: "TrustVector") -> bool:
        return all(a <= b for a, b in zip(self.t(), other.t()))

    def comparable(self, other: "TrustVector") -> bool:
        return self.leq(other) or other.leq(self)

    def meet(self, other: "TrustVector") -> "TrustVector":
        return TrustVector(*[min(a, b) for a, b in zip(self.t(), other.t())])

    def join(self, other: "TrustVector") -> "TrustVector":
        return TrustVector(*[max(a, b) for a, b in zip(self.t(), other.t())])

    def project(self, weights: dict[str, float]) -> float:
        """Task-specific scalar view. Not the underlying representation."""
        z = sum(weights.values()) or 1.0
        return sum(getattr(self, k) * w for k, w in weights.items()) / z


# --- Active inference ----------------------------------------------------------

@dataclass(frozen=True)
class Probe:
    name: str
    cost: float
    reversible: bool
    outcomes: tuple[tuple[float, tuple[float, ...]], ...]  # (P(outcome), posterior over hypotheses)


def probe_information_gain(prior: list[float], probe: Probe) -> float:
    return entropy(prior) - sum(p * entropy(post) for p, post in probe.outcomes)


def best_probe(prior: list[float], probes: Iterable[Probe]) -> tuple[Probe, float] | None:
    """Low-risk (reversible) probe with the largest information gain net of cost, if positive."""
    scored = [(p, probe_information_gain(prior, p) - p.cost) for p in probes if p.reversible]
    scored = [s for s in scored if s[1] > 0]
    return max(scored, key=lambda s: s[1]) if scored else None


class ActiveInferenceDeliberation:
    """Wraps choose_deliberation: probe the world to reduce uncertainty before proposing."""

    def __init__(self, base: Callable[..., DeliberationPlan] = choose_deliberation) -> None:
        self.base = base

    def plan(self, consequence: float, uncertainty: float, expected_gain: float, compute_cost: float,
             prior: list[float] | None = None, probes: Iterable[Probe] = ()) -> DeliberationPlan:
        plan = self.base(consequence, uncertainty, expected_gain, compute_cost)
        if prior:
            pick = best_probe(prior, probes)
            if pick:
                return DeliberationPlan(plan.mode, [f"active-inference-probe:{pick[0].name}"] + plan.steps,
                                        plan.max_iterations + 1)
        return plan


# --- Compression ---------------------------------------------------------------

@dataclass(frozen=True)
class CompressionRecord:
    id: str
    sources: tuple[str, ...]
    retained: tuple[str, ...]
    discarded: tuple[str, ...]
    original_information: float
    retained_information: float
    uncertainty_introduced: str
    raw_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.raw_refs:
            raise ValueError("a compression must keep references that reopen the raw source")

    @property
    def loss(self) -> float:
        return compression_loss(self.original_information, self.retained_information)

    def reopen(self, store: dict[str, Any]) -> list[Any]:
        return [store[r] for r in self.raw_refs]


# --- Layer vectors and the viability region ------------------------------------

LAYER_MATURITY = {
    "Measurement": "E0/E1", "Temporal Ontology": "E1", "Epistemic": "E1/E2", "Praxeological": "E2/E3",
    "Social": "E2/E3", "Risk": "E1", "Axiological": "E2/E3", "Aesthetic": "E3/E4",
    "Soteriological": "E4", "Thanatological": "E4", "Metaphysical": "E4/E5",
}


def annotate(proposal: Proposal, bundles: list[EvidenceBundle], certainty: float) -> dict[str, float | None]:
    mean = lambda xs: sum(xs) / len(xs) if xs else 0.0
    v: dict[str, float | None] = {
        "Measurement": mean([b.measurement_quality for b in bundles]),
        "Temporal Ontology": 1 - max([b.staleness for b in bundles], default=1.0),
        "Epistemic": certainty,
        "Praxeological": 1.0 if (proposal.proposer and proposal.goal and proposal.requested_transition) else 0.0,
        "Social": mean([b.independence for b in bundles]),
        "Risk": 1 - (0.0 if proposal.reversible else 1.0) * min(1.0, proposal.consequence_tier / 3),
        "Axiological": 1.0 if proposal.reversible else 0.5,
    }
    for layer, m in LAYER_MATURITY.items():
        if maturity_ceiling(m) in NON_ACTIONABLE_LEVELS:
            v[layer] = None  # advisory only; cannot gate
    return v


@dataclass(frozen=True)
class ViabilityRegion:
    bounds: dict[str, tuple[float, float]]

    def __post_init__(self) -> None:
        for dim in self.bounds:
            if maturity_ceiling(LAYER_MATURITY.get(dim, "E5")) in NON_ACTIONABLE_LEVELS:
                raise ValueError(f"layer {dim} is metaphor/frontier and cannot bound action")

    def contains(self, vector: dict[str, float | None]) -> tuple[bool, list[str]]:
        bad = []
        for dim, (lo, hi) in self.bounds.items():
            x = vector.get(dim)
            if x is None or not (lo <= x <= hi):
                bad.append(f"viability: {dim}={x} outside [{lo}, {hi}]")
        return not bad, bad


DEFAULT_REGION = ViabilityRegion({
    "Measurement": (0.5, 1.0), "Temporal Ontology": (0.3, 1.0),
    "Praxeological": (1.0, 1.0), "Social": (0.2, 1.0),
})


class ViabilityGate(Extension):
    def __init__(self, base: Any, region: ViabilityRegion = DEFAULT_REGION) -> None:
        super().__init__(base)
        self.__dict__["region"] = region

    def evaluate(self, proposal, bundles, *args, **kwargs):
        decision, risk, constraint = self.base.evaluate(proposal, bundles, *args, **kwargs)
        ok, bad = self.region.contains(annotate(proposal, bundles, decision.epistemic_certainty))
        return tighten(decision, [] if ok else bad), risk, constraint
