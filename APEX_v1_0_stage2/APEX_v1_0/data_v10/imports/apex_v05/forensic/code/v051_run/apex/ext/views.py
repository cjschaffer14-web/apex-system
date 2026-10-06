"""Representative models: one organism, many projections (all E4, non-authoritative).

Each view maps metaphor elements to real components and planes. A view is
checked like a functor: every plane must be covered, and every element must
name a component that exists. A metaphor that cannot be checked this way is
decoration.

The single macro-to-micro analogy (Gemini) is the Cell in a Pressure Vessel.
The developmental reading (ChatGPT) is the Egg as a state, not a container.
"""
from __future__ import annotations

PLANES = ("world", "proposal", "authority", "actuation", "operator")

VIEWS: dict[str, dict[str, tuple[str, str]]] = {   # element -> (component, plane)
    "egg": {
        "Shell": ("ContinuityLedger + checkpoints + lineage", "authority"),
        "Membrane": ("Membrane -> EvidenceBundle", "proposal"),
        "Yolk / DNA": ("ConstitutionV3 + RevealedAxioms + WALLS", "authority"),
        "White": ("ResourceBroker reserve + scheduler P-1 reserve", "actuation"),
        "Embryo": ("Proposal plane: graph, models, research slice", "proposal"),
        "Warmth": ("incubation_temperature (W = C*A*D*S)", "operator"),
        "Outside world": ("World", "world"),
    },
    "tower": {
        "Observatory": ("Proposal plane", "proposal"),
        "Load-bearing core": ("authorityd: Gatekeeper + CapabilityBroker + audit", "authority"),
        "Street": ("VerifiedRuntime", "actuation"),
        "Control room": ("OperatorChannel (P-1)", "operator"),
        "City": ("World", "world"),
    },
    "cell": {
        "Cytoplasm": ("Proposal plane (high-entropy generation)", "proposal"),
        "Nuclear membrane": ("TranscendentGatekeeperWrapper -> ... -> Gatekeeper", "authority"),
        "DNA": ("Constitution + axioms", "authority"),
        "Pressure-vessel hull": ("VerifiedRuntime + ResourceBroker", "actuation"),
        "Steward": ("Operator", "operator"),
        "Environment": ("World", "world"),
    },
    "manifold": {
        "Interior (Proposal manifold)": ("all Proposal-plane types", "proposal"),
        "Event horizon": ("W1 missing edge", "authority"),
        "Coordinate transform": ("mint: Decision -> ExecutionToken", "authority"),
        "Exterior trajectory": ("execute: ExecutionToken -> Outcome", "actuation"),
        "Observer outside the system": ("Operator (Godelian anchor)", "operator"),
        "Ambient space": ("World", "world"),
    },
    "markov_blanket": {
        "Sensory states": ("Membrane, EvidenceBundle, PeerEnvelope", "proposal"),
        "Internal states": ("Authority + Model Graph", "authority"),
        "Active states": ("ExecutionToken -> VerifiedRuntime", "actuation"),
        "External states": ("World", "world"),
        "Principal": ("Operator", "operator"),
    },
    "five_systems": {
        "1 Perception": ("Membrane: observations -> evidence", "proposal"),
        "2 Cognition": ("graph + models + reasoning + memory", "proposal"),
        "3 Authority": ("constitution + risk + capabilities", "authority"),
        "4 Action": ("sandbox + tools + domain packs", "actuation"),
        "5 Evolution": ("outcomes -> experiments -> evaluation", "authority"),
        "Owner": ("Operator", "operator"),
        "World": ("World", "world"),
    },
    "design_space": {
        "Day 1 Spirit": ("15 layers, Egg (Proposal-plane registry)", "proposal"),
        "Day 2 Law": ("planes, Gatekeeper, risk", "authority"),
        "Day 3 Body": ("tokens, isolation, awakening", "actuation"),
        "Failure timelines A-D": ("CounterfactualShadowGate negative data", "authority"),
        "Owner's choices": ("Operator", "operator"),
        "Other design worlds": ("World", "world"),
    },
}


def check_view(name: str) -> tuple[bool, list[str]]:
    v = VIEWS[name]
    covered = {plane for _, plane in v.values()}
    missing = [p for p in PLANES if p not in covered]
    unknown = [e for e, (_, p) in v.items() if p not in PLANES]
    return not missing and not unknown, missing + unknown


def render(name: str) -> str:
    v = VIEWS[name]
    w = max(len(k) for k in v)
    lines = [f"[{name}] (E4 view; explains, never authorizes)"]
    lines += [f"  {k.ljust(w)}  ->  {comp}  ({plane})" for k, (comp, plane) in v.items()]
    return "\n".join(lines)
