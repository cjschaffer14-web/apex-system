from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional
import hashlib, json, time, uuid


class Plane(str, Enum):
    PROPOSAL = "proposal"
    AUTHORITY = "authority"
    ACTUATION = "actuation"
    OPERATOR = "operator"


class EvidenceLevel(str, Enum):
    E0 = "E0"  # established engineering mechanism
    E1 = "E1"  # mature/context dependent
    E2 = "E2"  # active research; requires local validation
    E3 = "E3"  # exploratory APEX architecture
    E4 = "E4"  # metaphor/philosophy
    E5 = "E5"  # unresolved frontier


def now() -> float:
    return time.time()


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def canonical(obj: Any) -> str:
    if hasattr(obj, "__dataclass_fields__"):
        obj = asdict(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


@dataclass(frozen=True)
class Observation:
    id: str
    channel: str
    instrument: str
    value: Any
    error_model: dict[str, Any]
    timestamp: float
    logical_time: int
    provenance: list[str]
    evidence_level: str = "E0"


@dataclass(frozen=True)
class EvidenceBundle:
    id: str
    source_provenance: list[str]
    measurement_quality: float
    independence: float
    staleness: float
    domain_fit: float
    counterevidence: list[str]
    reproducibility: float
    uncertainty_type: str
    calibration_ref: Optional[str]
    decision_relevance: float
    evidence_level: str
    observations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Claim:
    id: str
    proposition: str
    supporting: list[str]
    contradicting: list[str]
    formal_form: Optional[str] = None
    evidence_level: str = "E2"


@dataclass(frozen=True)
class Hypothesis:
    id: str
    statement: str
    assumptions: list[str]
    alternatives: list[str]
    predictions: list[str]
    falsifiers: list[str]
    claims: list[str]


@dataclass(frozen=True)
class Proposal:
    id: str
    proposer: str
    goal: str
    requested_transition: str
    evidence_bundles: list[str]
    requested_capabilities: list[str]
    consequence_tier: int
    reversible: bool
    confidence_advisory: float = 0.0
    risk_estimate_advisory: float = 0.0
    budget: float = 0.0
    scope: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskRecord:
    id: str
    probability: float
    impact: float
    reversibility: float
    detectability: float
    blast_radius: float
    score: float


@dataclass(frozen=True)
class ConstraintRecord:
    id: str
    domain: str
    capacity: float
    consumed: float
    remaining: float
    headroom: float
    failure_threshold: float


@dataclass(frozen=True)
class Decision:
    id: str
    proposal_id: str
    result: str
    reasons: list[str]
    epistemic_certainty: float
    risk_ref: str
    constraint_ref: str
    timestamp: float


@dataclass(frozen=True)
class ExecutionToken:
    id: str
    decision_id: str
    capability: str
    resource_scope: dict[str, Any]
    budget: float
    issued_at: float
    expires_at: float
    nonce: str
    signature: str


@dataclass(frozen=True)
class Outcome:
    id: str
    token_id: str
    measured_result: Any
    observations: list[str]
    residual_vs_prediction: Optional[float]
    resources_consumed: float
    anomalies: list[str]
    timestamp: float


@dataclass(frozen=True)
class LearningCandidate:
    id: str
    target: str
    diff: str
    hypothesis_ref: str
    benchmark_plan: list[str]
    requested_permission_delta: list[str]
    parent_candidate_id: Optional[str] = None


@dataclass(frozen=True)
class Event:
    event_id: str
    event_type: str
    actor: str
    plane: str
    timestamp: float
    logical_time: int
    parent_hash: str
    payload_hash: str
    payload: dict[str, Any]
    provenance: list[str]


class LamportClock:
    def __init__(self) -> None:
        self.value = 0

    def tick(self, received: Optional[int] = None) -> int:
        if received is None:
            self.value += 1
        else:
            self.value = max(self.value, received) + 1
        return self.value


class EventLedger:
    """Append-only hash-chained event stream. Production can replace this with a Merkle DAG."""
    def __init__(self, path: str | Path = "events.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = LamportClock()
        self._tail_hash = "GENESIS"
        if self.path.exists():
            lines = [x for x in self.path.read_text().splitlines() if x.strip()]
            if lines:
                self._tail_hash = sha256(json.loads(lines[-1]))

    def append(self, event_type: str, actor: str, plane: Plane, payload: dict[str, Any],
               provenance: Optional[list[str]] = None) -> Event:
        ev = Event(
            event_id=uid("evt"),
            event_type=event_type,
            actor=actor,
            plane=plane.value,
            timestamp=now(),
            logical_time=self.clock.tick(),
            parent_hash=self._tail_hash,
            payload_hash=sha256(payload),
            payload=payload,
            provenance=provenance or [],
        )
        row = asdict(ev)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(canonical(row) + "\n")
        self._tail_hash = sha256(row)
        return ev

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text().splitlines() if x.strip()]


class ModelGraph:
    """Typed projection over event history; not an authority store."""
    NODE_TYPES = {
        "Entity","Event","Observation","Claim","Hypothesis","Value","Capability",
        "Constraint","Risk","Trajectory","Symbol","Abstraction"
    }
    EDGE_TYPES = {
        "derived_from","supports","contradicts","predicts","falsifies","depends_on",
        "constrains","authorizes","causes","precedes","compresses","instance_of","competes_with"
    }

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []

    def add_node(self, node_id: str, node_type: str, data: dict[str, Any]) -> None:
        if node_type not in self.NODE_TYPES:
            raise ValueError(f"unknown node type {node_type}")
        self.nodes[node_id] = {"type": node_type, **data}

    def add_edge(self, src: str, dst: str, edge_type: str, plane: Plane, **meta: Any) -> None:
        if edge_type not in self.EDGE_TYPES:
            raise ValueError(f"unknown edge type {edge_type}")
        if edge_type == "authorizes" and plane != Plane.AUTHORITY:
            raise PermissionError("authorizes edges are Authority-only")
        self.edges.append({"src":src,"dst":dst,"type":edge_type,**meta})
