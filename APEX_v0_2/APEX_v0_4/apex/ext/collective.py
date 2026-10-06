"""Cross-AI collaboration (UCA-2): envelopes v2, consensus as evidence, stigmergy, peer routing.

Rules from the spec, now executable:
  consensus != truth
  model confidence != epistemic certainty
  cryptographic integrity != empirical truth
  correlated model families are not independent votes

Correction: the Gemini synthesis twice reads "proves that consensus = truth".
The design rule, and every other document, says consensus != truth. v0.3 encodes
the latter: a model family (lineage) counts once however many members vote.

Naming note (owner's broker critique): the component that picks which peer
models to consult is called PeerRouter, not "Cross-AI broker", so "broker"
stays reserved for CapabilityBroker (Authority) and ResourceBroker (Actuation).
"""
from __future__ import annotations
import hashlib, hmac, json, time, uuid
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from typing import Any, Callable
from ..core import EvidenceBundle, ModelGraph, Plane, LamportClock, uid
from .contracts import Extension

# --- Envelope v2 ---------------------------------------------------------------

PEER_FORBIDDEN_TYPES = {"ExecutionToken", "Decision", "Authorize", "AmendConstitution", "ModifyEvaluator", "GrantPermission"}


def _canon(x: Any) -> bytes:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), default=str).encode()


@dataclass(frozen=True)
class EnvelopeV2:
    schema_version: str
    message_type: str
    message_id: str
    seq: int
    timestamp: float
    sender_id: str
    sender_key_id: str
    payload_hash: str
    payload: dict
    canonicalization: str
    signature: str


class KeyRegistry:
    def __init__(self) -> None:
        self._keys: dict[tuple[str, str], tuple[bytes, bool]] = {}
        self.lineage: dict[str, str] = {}

    def register(self, sender_id: str, key_id: str, key: bytes, lineage: str) -> None:
        self._keys[(sender_id, key_id)] = (key, True)
        self.lineage[sender_id] = lineage

    def revoke(self, sender_id: str, key_id: str) -> None:
        key, _ = self._keys[(sender_id, key_id)]
        self._keys[(sender_id, key_id)] = (key, False)

    def get(self, sender_id: str, key_id: str) -> tuple[bytes, bool] | None:
        return self._keys.get((sender_id, key_id))


def make_envelope_v2(sender_id: str, key_id: str, key: bytes, seq: int, message_type: str, payload: dict) -> EnvelopeV2:
    bare = {"schema_version": "2.0", "message_type": message_type, "message_id": uuid.uuid4().hex, "seq": seq,
            "timestamp": time.time(), "sender_id": sender_id, "sender_key_id": key_id,
            "payload_hash": hashlib.sha256(_canon(payload)).hexdigest(), "payload": payload,
            "canonicalization": "JCS-like deterministic JSON"}
    return EnvelopeV2(**bare, signature=hmac.new(key, _canon(bare), hashlib.sha256).hexdigest())


def validate_envelope_v2(env: EnvelopeV2, registry: KeyRegistry, replay: dict[str, int], seen: set[str],
                         skew_seconds: float = 300.0) -> tuple[bool, list[str]]:
    errors = []
    if env.schema_version != "2.0":
        errors.append("V1 schema")
    if abs(time.time() - env.timestamp) > skew_seconds:
        errors.append("V2 timestamp")
    entry = registry.get(env.sender_id, env.sender_key_id)
    if entry is None:
        errors.append("V3 sender/key not registered")
    elif not entry[1]:
        errors.append("V3 key revoked")
    else:
        bare = asdict(env)
        sig = bare.pop("signature")
        if not hmac.compare_digest(sig, hmac.new(entry[0], _canon(bare), hashlib.sha256).hexdigest()):
            errors.append("V4 signature")
    if hashlib.sha256(_canon(env.payload)).hexdigest() != env.payload_hash:
        errors.append("V5 payload hash")
    if env.message_id in seen or env.seq <= replay.get(env.sender_id, -1):
        errors.append("V6 replay/sequence")
    if env.message_type in PEER_FORBIDDEN_TYPES:
        errors.append("V7 role violation: peers are Proposal-plane and cannot send authority messages")
    if not errors:
        replay[env.sender_id] = env.seq
        seen.add(env.message_id)
    return not errors, errors


# --- Consensus as evidence -------------------------------------------------------

@dataclass(frozen=True)
class PeerOutput:
    peer_id: str
    lineage: str
    stances: dict[str, int]                 # claim_id -> +1 support, -1 oppose, 0 abstain
    sources: tuple[str, ...] = ()
    confidence_advisory: float = 0.0        # recorded, never used


@dataclass(frozen=True)
class ClaimConsensus:
    claim_id: str
    support: float
    oppose: float
    effective_lineages: float
    status: str                             # supported | opposed | unresolved
    majority: int
    minority_peers: tuple[str, ...]
    lineages: tuple[str, ...]


@dataclass(frozen=True)
class ConsensusBundle:
    id: str
    claims: dict[str, ClaimConsensus]
    peers: int
    lineages: int
    notes: tuple[str, ...] = ("consensus != truth", "model confidence ignored",
                              "lineages count once", "descriptive artifact; not an authority grant")


def compute_consensus(outputs: list[PeerOutput], margin: float = 0.2, min_lineages: int = 2) -> ConsensusBundle:
    by_lineage: dict[str, list[PeerOutput]] = defaultdict(list)
    for o in outputs:
        by_lineage[o.lineage].append(o)
    lin_sources = {L: {s for o in os_ for s in o.sources} for L, os_ in by_lineage.items()}

    def overlap(a: set[str], b: set[str]) -> float:
        return len(a & b) / len(a | b) if (a | b) else 0.0

    weight = {L: 1.0 / (1 + sum(1 for M in by_lineage if M != L and overlap(lin_sources[L], lin_sources[M]) >= 0.5))
              for L in by_lineage}
    claims: dict[str, ClaimConsensus] = {}
    for cid in sorted({c for o in outputs for c in o.stances}):
        support = oppose = n_eff = 0.0
        for L, members in by_lineage.items():
            votes = [m.stances.get(cid, 0) for m in members]
            v = sum(votes) / len(votes)
            if v:
                n_eff += weight[L]
                support += weight[L] * max(v, 0.0)
                oppose += weight[L] * max(-v, 0.0)
        if n_eff < min_lineages or abs(support - oppose) < margin * max(n_eff, 1e-9):
            status, majority = "unresolved", 0
        else:
            majority = 1 if support > oppose else -1
            status = "supported" if majority == 1 else "opposed"
        minority = tuple(sorted(o.peer_id for o in outputs if majority and o.stances.get(cid, 0) == -majority))
        claims[cid] = ClaimConsensus(cid, round(support, 4), round(oppose, 4), round(n_eff, 4), status, majority,
                                     minority, tuple(sorted(by_lineage)))
    return ConsensusBundle(uid("consensus"), claims, len(outputs), len(by_lineage))


def consensus_to_evidence(cb: ConsensusBundle, claim_id: str, peer_trust: float = 0.5) -> EvidenceBundle:
    c = cb.claims[claim_id]
    independence = min(1.0, c.effective_lineages / max(1, cb.peers))
    return EvidenceBundle(uid("evb"), ["channel:peer_ai", f"consensus:{cb.id}"] + [f"source:lineage:{L}" for L in c.lineages],
                          peer_trust, independence, 0.0, 0.8, list(c.minority_peers), peer_trust, "consensus", None,
                          1.0, "E2", [])


# --- Stigmergy -------------------------------------------------------------------

class StigmergicGraph(Extension):
    """Peers coordinate by leaving traces in the Model Graph, not by chatting.

    Branch ownership: a peer cannot overwrite another peer's node. It adds a
    competing node and a competes_with edge, so disagreement accumulates
    instead of being erased.
    """

    def __init__(self, base: ModelGraph | None = None) -> None:
        super().__init__(base or ModelGraph())
        self.__dict__.update(owners={}, traces=[], clock=LamportClock())

    def add_node(self, peer_id: str, node_id: str, node_type: str, data: dict | None = None) -> None:
        owner = self.owners.get(node_id)
        if owner is not None and owner != peer_id:
            raise PermissionError(f"node {node_id} belongs to {owner}; add a competing node instead")
        self.base.add_node(node_id, node_type, {**(data or {}), "author": peer_id})
        self.owners[node_id] = peer_id
        self.traces.append({"t": self.clock.tick(), "peer": peer_id, "op": "node", "id": node_id, "type": node_type})

    def trace(self, peer_id: str, src: str, dst: str, edge_type: str, *, independence: float | None = None,
              sources: tuple[str, ...] = (), weight: float = 1.0) -> None:
        if edge_type in ("supports", "contradicts") and independence is None:
            raise ValueError("supports/contradicts traces must carry source-independence metadata")
        self.base.add_edge(src, dst, edge_type, Plane.PROPOSAL, author=peer_id, independence=independence,
                           sources=list(sources), weight=weight)
        self.traces.append({"t": self.clock.tick(), "peer": peer_id, "op": "edge", "src": src, "dst": dst,
                            "type": edge_type})

    def delta_since(self, t: int) -> list[dict]:
        return [x for x in self.traces if x["t"] > t]

    def competing(self, node_id: str) -> set[str]:
        out = set()
        for e in self.base.edges:
            if e["type"] == "competes_with" and node_id in (e["src"], e["dst"]):
                out.add(e["dst"] if e["src"] == node_id else e["src"])
        return out

    def stance(self, node_id: str) -> float:
        """Descriptive support minus contradiction, weighted by independence. Not truth."""
        s = 0.0
        for e in self.base.edges:
            if e["dst"] == node_id and e["type"] in ("supports", "contradicts"):
                s += (1 if e["type"] == "supports" else -1) * e.get("weight", 1.0) * (e.get("independence") or 0.0)
        return s


# --- Peer routing --------------------------------------------------------------------

@dataclass
class PeerAdapter:
    peer_id: str
    lineage: str
    ask: Callable[[str, list[str]], PeerOutput]   # (question, evidence ids) -> PeerOutput
    cost: float = 1.0


class PeerRouter:
    """Consult other models only when local uncertainty or novelty crosses a threshold; maximise lineage diversity."""

    def __init__(self, peers: list[PeerAdapter], uncertainty_threshold: float = 0.5, novelty_threshold: float = 0.7) -> None:
        self.peers, self.ut, self.nt = peers, uncertainty_threshold, novelty_threshold

    def should_consult(self, uncertainty: float, novelty: float = 0.0) -> bool:
        return uncertainty >= self.ut or novelty >= self.nt

    def select(self, k: int = 3, budget: float = float("inf")) -> list[PeerAdapter]:
        chosen, lineages, spent = [], set(), 0.0
        for p in sorted(self.peers, key=lambda p: p.cost):
            if p.lineage not in lineages and spent + p.cost <= budget:
                chosen.append(p); lineages.add(p.lineage); spent += p.cost
            if len(chosen) == k:
                break
        return chosen

    def deliberate(self, question: str, evidence_ids: list[str], k: int = 3) -> ConsensusBundle:
        outputs = [p.ask(question, evidence_ids) for p in self.select(k)]
        return compute_consensus(outputs)
