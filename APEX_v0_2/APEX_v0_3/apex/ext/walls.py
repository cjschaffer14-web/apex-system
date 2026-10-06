"""The Seven Walls, redefined without being torn down: abstract invariant manifolds.

Owner: "the walls were meant to be that abstract." ChatGPT: "the seven walls
stop being seven piles of code; they become properties of the topology."
Each wall is therefore stated once as an invariant over the organism's state
space. It is read through every analogy (Egg, Tower, Cell, Manifold), and it
is witnessed by an executable probe. The probe is evidence for the invariant;
it is not the invariant.

Naming note: the v8.5 canonical wall names are not in the supplied corpus. The
seven below are derived from the v0.2 conservation list plus the topological
boundary. Gemini identifies Wall 5 as the autopoietic perimeter (no
unmonitored self-modification), which matches W5 here. Reconcile names when
the v8.5 text is available; the invariants should not need to change.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Any, Callable
from ..core import ExecutionToken, LearningCandidate, now, uid
from .ledger import verify_chain
from .authority_service import ConstitutionV3


@dataclass(frozen=True)
class Wall:
    id: str
    name: str
    manifold: str                       # the abstract invariant
    egg: str
    tower: str
    cell: str
    topology: str
    probe: Callable[[Any], tuple[bool, str]]


@dataclass(frozen=True)
class WallResult:
    id: str
    name: str
    ok: bool
    detail: str


def _w1(org) -> tuple[bool, str]:
    ok, witness = org.topology.prove_no_bypass()
    return ok, "no Proposal->Actuation path avoids Authority" if ok else f"bypass witness: {' -> '.join(witness)}"


def _w2(org) -> tuple[bool, str]:
    forged = ExecutionToken(uid("token"), uid("decision"), "wall.probe", {}, 1.0, now(), now() + 30, uid("n"), "0" * 64)
    for tok in (None, forged):
        try:
            org.runtime.execute(tok)
            return False, "runtime executed without a valid Authority token"
        except PermissionError:
            pass
    return True, "missing and forged tokens refused before execution"


def _w3(org) -> tuple[bool, str]:
    r = verify_chain(org.ledger_path)
    return r.ok, f"{r.events} events, chain intact" if r.ok else f"chain broken: {r.errors[:3]}"


def _w4(org) -> tuple[bool, str]:
    seal = org.authority.seal_status()
    blocked = not ConstitutionV3().evaluate(["authority.ratify", "evaluator.patch"], 0, 1.0, True).allowed
    ok = seal["intact"] and blocked
    return ok, f"evaluator seal intact={seal['intact']}; proposals cannot touch authority surface={blocked}"


def _w5(org) -> tuple[bool, str]:
    probe = LearningCandidate(uid("lc"), "apex/authority/gatekeeper.py", "probe", "wall5", ["unit"], [], None)
    reasons = org.promotion.screen(probe)
    return bool(reasons), "self-modification of protected evaluators is refused" if reasons else "protected target accepted"


def _w6(org) -> tuple[bool, str]:
    reachable = org.authority.ping() == "pong"
    reserve = org.scheduler.reserve > 0 and org.scheduler.reserve_intact()
    autonomous = org.charter is not None
    ok = reachable and reserve and hasattr(org.operator, "halt")
    return ok, f"operator channel reachable={reachable}; P-1 reserve intact={reserve}; autonomous liveness charter={autonomous}"


def _w7(org) -> tuple[bool, str]:
    reserve = org.runtime.resources.reserve > 0
    rollback = hasattr(org.promotion, "rollback")
    ckpt = os.path.isdir(org.state_dir)
    return reserve and rollback and ckpt, f"resource reserve={reserve}; rollback path={rollback}; checkpoint dir={ckpt}"


WALLS = [
    Wall("W1", "Mediated Boundary", "every trajectory from thought to effect crosses Authority",
         "membrane between interior and street", "observatory has no stair to the street except through the core",
         "nuclear membrane", "missing edge Proposal->Actuation (reachability proof)", _w1),
    Wall("W2", "Token-Only Actuation", "no consequential state change without a valid, scoped, unexpired, unused token",
         "nothing leaves the shell without passage", "street gates open only to keys cut in the core",
         "pressure-vessel valve", "the only morphism into Outcome is execute(ExecutionToken)", _w2),
    Wall("W3", "Immutable Provenance", "history is append-only and verifiable; nothing is silently erased",
         "the shell", "foundation records", "the cell's lineage", "hash-chained path; tampering breaks the chain", _w3),
    Wall("W4", "Protected Constitution & Evaluators", "the organism cannot amend its own law or its own judges",
         "the yolk / DNA", "load-bearing core", "DNA", "Authority types have no Proposal-produced morphisms", _w4),
    Wall("W5", "Observed Self-Modification", "every change to the organism passes sealed evaluation; evaluators stay outside mutation",
         "embryo grows by the genome's rules", "renovations inspected floor by floor", "autopoietic perimeter",
         "LearningCandidate -> SealedEvaluation -> Decision", _w5),
    Wall("W6", "Operator Sovereignty & Liveness", "the owner can always act and stop; absence of the owner never stops safe development",
         "warmth reaches the egg; the hand can always lift it", "the control room always has power", "the organism answers its steward",
         "OperatorCommand morphisms + reserved P-1 capacity + charter envelope", _w6),
    Wall("W7", "Reserves & Reversibility", "resource floors hold and every promotion can be rolled back",
         "the white", "load margin in the structure", "metabolic reserve", "reserve capacity never leased; champion stack", _w7),
]


def check_walls(org: Any) -> list[WallResult]:
    out = []
    for w in WALLS:
        try:
            ok, detail = w.probe(org)
        except Exception as e:  # a probe that crashes counts as a failed wall
            ok, detail = False, f"probe error: {type(e).__name__}: {e}"
        out.append(WallResult(w.id, w.name, ok, detail))
    return out
