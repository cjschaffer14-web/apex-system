"""authorityd: a small Authority kernel in its own process.

ChatGPT review, Upgrade 3 ("shrink the trusted core"): Authority keeps five
responsibilities and nothing else:

    verify_proposal      resolve evidence by id, normalise by channel trust, decorrelate sources
    evaluate_constraints risk + resource headroom (v0.2 Gatekeeper)
    evaluate_invariants  constitution, revealed axioms, viability region, shadow, precedent
    mint_capability      v0.2 CapabilityBroker; signing key generated inside this process
    append_audit         sole writer of the event ledger (audit custody)

plus the authenticated Operator endpoints (halt, resume, override, ratify,
rectify, charter). No LLM, research, memory, strategy or ontology runs here.

Boundary hardening over v0.2:
  * The signing key never leaves the Authority process. The runtime asks
    Authority to verify tokens (introspection), so no Actuation-side key exists.
  * Only whitelisted methods cross the process boundary.
  * Evidence is resolved by id from Authority's own store, so a proposer
    cannot hand the Gatekeeper evidence at decision time.
  * Bundles that share a source collapse to one vote. Correlated evidence
    cannot stack.
  * Protected-evaluator seal: source hashes of every Authority module are
    taken at start and checked before every decision. A mismatch fails closed.
"""
from __future__ import annotations
import functools, hashlib, hmac, importlib, os, time
import multiprocessing as mp
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from ..core import Proposal, EvidenceBundle, Decision, ExecutionToken, Plane, uid, now, canonical, sha256
from ..authority.constitution import Constitution, ConstitutionalResult
from ..authority.gatekeeper import Gatekeeper
from ..authority.broker import CapabilityBroker
from .ledger import ContinuityLedger, verify_chain
from .transcendent import (TranscendentGatekeeperWrapper, AxiomGate, EncounterWithMystery,
                           RevealedAxiom, active_axioms, MYSTERY)
from .design_space import CounterfactualShadowGate, PrecedentGate, PrecedentIndex, proposal_features
from .cybernetics import SecondOrderObserver, LivenessMonitor
from .epistemics import ViabilityGate, DEFAULT_REGION, ViabilityRegion

FORBIDDEN_PREFIXES = ("authority.", "operator.", "ledger.", "evaluator.")
DEFAULT_CHANNEL_TRUST = {"operator": 1.0, "cli": 1.0, "evaluator": 0.97, "system": 0.97, "sensor": 0.9, "file": 0.85,
                         "market": 0.8, "web": 0.6, "peer_ai": 0.5}
UNKNOWN_CHANNEL_TRUST = 0.4
PROTECTED_MODULES = (
    "apex.core", "apex.authority.constitution", "apex.authority.gatekeeper", "apex.authority.broker",
    "apex.cognition.math_systems", "apex.ext.authority_service", "apex.ext.transcendent",
    "apex.ext.design_space", "apex.ext.cybernetics", "apex.ext.contracts", "apex.ext.ledger",
    "apex.ext.epistemics",
)


def operator_sign(key: bytes, command: dict) -> str:
    return hmac.new(key, canonical(command).encode(), hashlib.sha256).hexdigest()


def new_command(cmd: str, **args: Any) -> dict:
    return {"cmd": cmd, "args": args, "nonce": uid("opn"), "ts": now()}


class ConstitutionV3(Constitution):
    """v0.2 Constitution plus a prefix rule: proposals never touch the authority surface."""

    def evaluate(self, requested_capabilities, consequence_tier, epistemic_certainty, reversible) -> ConstitutionalResult:
        base = super().evaluate(requested_capabilities, consequence_tier, epistemic_certainty, reversible)
        extra = sorted(c for c in requested_capabilities
                       if c.startswith(FORBIDDEN_PREFIXES) and c not in self.FORBIDDEN_DIRECT_CAPABILITIES)
        reasons = list(base.reasons) + ([f"forbidden authority-surface capabilities: {extra}"] if extra else [])
        return ConstitutionalResult(not reasons, reasons)


def _roots(b: EvidenceBundle) -> set[str]:
    r = {p for p in b.source_provenance if not str(p).startswith("channel:")}
    return r or {f"bundle:{b.id}"}


def _merge(members: list[EvidenceBundle]) -> EvidenceBundle:
    mean = lambda xs: sum(xs) / len(xs)
    if any(m.uncertainty_type == MYSTERY for m in members):
        ut = MYSTERY
    elif any(m.uncertainty_type == "consensus" for m in members):
        ut = "consensus"
    else:
        ut = members[0].uncertainty_type
    return EvidenceBundle(
        "merged_" + sha256(sorted(m.id for m in members))[:16],
        sorted({p for m in members for p in m.source_provenance}),
        mean([m.measurement_quality for m in members]), mean([m.independence for m in members]),
        max(m.staleness for m in members), mean([m.domain_fit for m in members]),
        sorted({c for m in members for c in m.counterevidence}),
        mean([m.reproducibility for m in members]), ut,
        next((m.calibration_ref for m in members if m.calibration_ref), None),
        mean([m.decision_relevance for m in members]),
        sorted(m.evidence_level for m in members)[-1],
        sorted({o for m in members for o in m.observations}),
    )


def decorrelate(bundles: list[EvidenceBundle]) -> tuple[list[EvidenceBundle], list[str]]:
    """Bundles sharing any non-channel provenance root are one evidence family and count once."""
    groups: list[tuple[set[str], list[EvidenceBundle]]] = []
    for b in bundles:
        roots, members = _roots(b), [b]
        for g in [g for g in groups if g[0] & _roots(b)]:
            roots |= g[0]
            members = g[1] + members
            groups.remove(g)
        groups.append((roots, members))
    out, notes = [], []
    for roots, members in groups:
        if len(members) == 1:
            out.append(members[0])
        else:
            out.append(_merge(members))
            notes.append(f"{len(members)} bundles share source(s) {sorted(roots)}; counted as one")
    return out, notes


class AuthorityKernel:
    PUBLIC = frozenset({
        "ping", "status", "seal_status", "submit_evidence", "evaluate", "verify", "report_outcome",
        "record", "operator_override", "ratify", "rectify", "halt", "resume", "verify_grant",
        "ratify_charter", "charter", "axioms", "glossary", "ledger_report", "record_migration",
    })

    def __init__(self, ledger_path: str, operator_key: bytes, channel_trust: dict | None = None,
                 budget_capacity: float = 100.0, token_ttl: float = 30.0, risk_ceiling: float = 0.65,
                 viability_region: ViabilityRegion | None = None) -> None:
        self._broker = CapabilityBroker(os.urandom(32))
        self._operator_key = bytes(operator_key)
        self._op_nonces: set[str] = set()
        self.ledger = ContinuityLedger(ledger_path)
        self.channel_trust = dict(DEFAULT_CHANNEL_TRUST if channel_trust is None else channel_trust)
        self.budget_capacity, self.budget_consumed, self.token_ttl = budget_capacity, 0.0, token_ttl
        self.evidence: dict[str, EvidenceBundle] = {}
        self.issued: dict[str, dict] = {}
        self.axiom_history: list[RevealedAxiom] = []
        self.rectifications: list[dict] = []
        self._charter: dict | None = None
        self.halted = False
        self.precedents = PrecedentIndex()
        self.liveness = LivenessMonitor()
        self.constitution = ConstitutionV3()
        g: Any = Gatekeeper(self.constitution, risk_ceiling)
        g = SecondOrderObserver(g)
        g = ViabilityGate(g, viability_region or DEFAULT_REGION)
        g = AxiomGate(g, lambda: active_axioms(self.axiom_history))
        g = CounterfactualShadowGate(g)
        g = PrecedentGate(g, self.precedents)
        self.gate = TranscendentGatekeeperWrapper(g)
        self._seal = self._compute_seal()
        restored = self._restore()
        self._append("AuthorityStarted", {"gate_lineage": self.gate.lineage(), "seal_digest": sha256(self._seal),
                                          "pid": os.getpid(), "responsibilities": [
                                              "verify_proposal", "evaluate_constraints", "evaluate_invariants",
                                              "mint_capability", "append_audit"], "restored": restored})

    def _restore(self) -> dict:
        """Shell continuity: rebuild ratified axioms, rectifications and charter from history."""
        n_ax = n_rect = 0
        for row in self.ledger.read():
            t, pl = row.get("event_type"), row.get("payload", {})
            if t == "AxiomRatified":
                self.axiom_history.append(RevealedAxiom(**pl)); n_ax += 1
            elif t == "Rectification":
                self.rectifications.append(pl); n_rect += 1
            elif t == "AutonomyCharterRatified":
                self._charter = dict(pl.get("charter", {}))
        return {"axioms": n_ax, "rectifications": n_rect, "charter": bool(self._charter)}

    # -- audit custody -------------------------------------------------------
    def _append(self, event_type: str, payload: dict, provenance: list[str] | None = None,
                plane: Plane = Plane.AUTHORITY, actor: str = "authority"):
        return self.ledger.append(event_type, actor, plane, payload, provenance)

    def record(self, event_type: str, actor: str, plane: str, payload: dict, provenance: list[str] | None = None) -> str:
        if plane not in (Plane.PROPOSAL.value, Plane.ACTUATION.value):
            raise PermissionError("only proposal/actuation events may be recorded from outside Authority")
        return self._append(event_type, payload, provenance, Plane(plane), actor).event_id

    def ledger_report(self) -> dict:
        return asdict(verify_chain(self.ledger.path))

    # -- seal -----------------------------------------------------------------
    def _compute_seal(self) -> dict[str, str]:
        return {m: hashlib.sha256(Path(importlib.import_module(m).__file__).read_bytes()).hexdigest()
                for m in PROTECTED_MODULES}

    def seal_status(self) -> dict:
        current = self._compute_seal()
        changed = sorted(m for m in current if current[m] != self._seal.get(m))
        return {"intact": not changed, "changed": changed, "digest": sha256(self._seal)}

    # -- verify_proposal --------------------------------------------------------
    def submit_evidence(self, bundle: EvidenceBundle, submitter: str = "proposal") -> str:
        self.evidence[bundle.id] = bundle
        self._append("EvidenceRegistered", {"id": bundle.id, "provenance": bundle.source_provenance,
                                            "uncertainty_type": bundle.uncertainty_type,
                                            "evidence_level": bundle.evidence_level},
                     plane=Plane.PROPOSAL, actor=submitter)
        return bundle.id

    def _normalize(self, b: EvidenceBundle) -> EvidenceBundle:
        chans = [p.split(":", 1)[1] for p in b.source_provenance if str(p).startswith("channel:")]
        trust = min((self.channel_trust.get(c, UNKNOWN_CHANNEL_TRUST) for c in chans), default=UNKNOWN_CHANNEL_TRUST)
        return replace(b, measurement_quality=min(b.measurement_quality, trust),
                       reproducibility=min(b.reproducibility, trust))

    # -- evaluate + mint ---------------------------------------------------------
    def evaluate(self, proposal: Proposal) -> tuple[Decision, list[ExecutionToken], dict]:
        self._append("ProposalReceived", {"proposal": asdict(proposal)}, plane=Plane.PROPOSAL, actor=proposal.proposer)
        info: dict = {"notes": [], "escalate": False, "features": {}}
        pre = []
        if self.halted:
            pre.append("operator halt in effect")
        seal = self.seal_status()
        if not seal["intact"]:
            pre.append(f"protected evaluator seal broken: {seal['changed']}")
        missing = [b for b in proposal.evidence_bundles if b not in self.evidence]
        if missing:
            pre.append(f"unresolved evidence references: {missing}")
        if not proposal.evidence_bundles:
            pre.append("no evidence cited")
        t0 = time.perf_counter()
        if pre:
            decision = Decision(uid("decision"), proposal.id, "denied", pre, 0.0, "", "", now())
        else:
            merged, info["notes"] = decorrelate([self._normalize(self.evidence[b]) for b in proposal.evidence_bundles])
            try:
                decision, risk, constraint = self.gate.evaluate(proposal, merged, self.budget_capacity, self.budget_consumed)
                self._append("RiskRecord", asdict(risk), [proposal.id])
                self._append("ConstraintRecord", asdict(constraint), [proposal.id])
                info["features"] = proposal_features(proposal, merged, decision.epistemic_certainty)
            except EncounterWithMystery as m:
                decision = Decision(uid("decision"), proposal.id, "deferred", [str(m)], 0.0, "", "", now())
                info["escalate"] = True
                self._append("EncounterWithMystery", {"proposal_id": proposal.id, "bundles": m.bundle_ids,
                                                      "action": "halted; escalate to owner"}, [proposal.id])
        self.liveness.observe((time.perf_counter() - t0) * 1000)
        tokens = self._broker.mint(decision, proposal, self.token_ttl)
        if decision.result == "approved":
            self.budget_consumed += max(0.0, proposal.budget)
            self.precedents.add(decision.id, info["features"], decision.result)
        for t in tokens:
            self.issued[t.id] = {"decision_id": decision.id, "revoked": False, "used": False}
        self._append("Decision", asdict(decision), [proposal.id])
        if tokens:
            self._append("TokensMinted", {"tokens": [{"id": t.id, "capability": t.capability, "budget": t.budget,
                                                      "expires_at": t.expires_at} for t in tokens]}, [decision.id])
        return decision, tokens, info

    def verify(self, token: ExecutionToken) -> tuple[bool, str]:
        rec = self.issued.get(token.id)
        if rec is None:
            return False, "token was not issued by this Authority"
        if rec["revoked"]:
            return False, "token revoked"
        if rec["used"]:
            return False, "token already used"
        if now() > token.expires_at:
            return False, "token expired"
        if rec["decision_id"] != token.decision_id:
            return False, "token/decision mismatch"
        payload = {"decision_id": token.decision_id, "capability": token.capability, "scope": token.resource_scope,
                   "budget": token.budget, "issued_at": token.issued_at, "expires_at": token.expires_at,
                   "nonce": token.nonce}
        if not hmac.compare_digest(self._broker._sign(payload), token.signature):
            return False, "signature invalid"
        return True, "ok"

    def report_outcome(self, token_id: str, success: bool, residual: float | None = None,
                       resources: float = 0.0, detail: dict | None = None) -> None:
        rec = self.issued.get(token_id)
        if rec is None:
            raise KeyError(token_id)
        rec["used"] = True
        self.precedents.record_outcome(rec["decision_id"], success)
        self._append("OutcomeReported", {"token_id": token_id, "success": bool(success), "residual": residual,
                                         "resources": resources, "detail": detail or {}},
                     [token_id], Plane.ACTUATION, "actuation")

    # -- operator endpoints -----------------------------------------------------
    def _auth(self, command: dict, signature: str, expected: str, consume: bool = True) -> None:
        if not isinstance(command, dict) or command.get("cmd") != expected:
            raise PermissionError(f"operator command must be {expected!r}")
        if not hmac.compare_digest(operator_sign(self._operator_key, command), str(signature)):
            self._append("OperatorAuthFailed", {"cmd": expected}, plane=Plane.OPERATOR, actor="unknown")
            raise PermissionError("operator signature invalid")
        if consume:
            if abs(now() - float(command.get("ts", 0))) > 300:
                raise PermissionError("operator command expired")
            n = command.get("nonce")
            if not n or n in self._op_nonces:
                raise PermissionError("operator command replayed")
            self._op_nonces.add(n)

    def operator_override(self, command: dict, signature: str) -> tuple[Decision, list[ExecutionToken]]:
        self._auth(command, signature, "override")
        args = command["args"]
        p = Proposal(**args["proposal"])
        bad = [c for c in p.requested_capabilities if c.startswith(FORBIDDEN_PREFIXES)]
        if bad:
            raise PermissionError(f"override cannot grant authority-surface capabilities {bad}; use ratification")
        origin = args.get("origin", "OPERATOR")
        decision = Decision(uid("decision"), p.id, "approved",
                            [f"operator override ({origin}): {args.get('rationale', '')}"], 0.0, "", "", now())
        tokens = self._broker.mint(decision, p, self.token_ttl)
        for t in tokens:
            self.issued[t.id] = {"decision_id": decision.id, "revoked": False, "used": False}
        self._append("OperatorOverride", {"decision": asdict(decision), "origin": origin,
                                          "tokens": [t.id for t in tokens]}, [p.id], Plane.OPERATOR, "operator")
        return decision, tokens

    def ratify(self, command: dict, signature: str) -> RevealedAxiom:
        self._auth(command, signature, "ratify")
        a = command["args"]
        ax = RevealedAxiom(uid("axiom"), a["kind"], a["value"], a.get("rationale", ""),
                           a.get("origin", "TRANSCENDENT_REVELATION"), "operator", now(), a.get("supersedes"))
        ax.validate()
        self.axiom_history.append(ax)
        self._append("AxiomRatified", asdict(ax), plane=Plane.OPERATOR, actor="operator")
        return ax

    def rectify(self, command: dict, signature: str) -> dict:
        """Zhengming: the owner re-aligns a name with what it should mean. Appended, never overwritten."""
        self._auth(command, signature, "rectify")
        rec = {"term": command["args"]["term"], "definition": command["args"]["definition"], "ts": now()}
        self.rectifications.append(rec)
        self._append("Rectification", rec, plane=Plane.OPERATOR, actor="operator")
        return rec

    def halt(self, command: dict, signature: str) -> int:
        self._auth(command, signature, "halt")
        self.halted = True
        n = 0
        for rec in self.issued.values():
            if not rec["revoked"] and not rec["used"]:
                rec["revoked"] = True
                n += 1
        self._append("OperatorHalt", {"reason": command["args"].get("reason", ""), "revoked_tokens": n},
                     plane=Plane.OPERATOR, actor="operator")
        return n

    def resume(self, command: dict, signature: str) -> None:
        self._auth(command, signature, "resume")
        self.halted = False
        self._append("OperatorResume", {"reason": command["args"].get("reason", "")}, plane=Plane.OPERATOR, actor="operator")

    def verify_grant(self, command: dict, signature: str) -> bool:
        try:
            self._auth(command, signature, "authorize_permission_delta", consume=False)
            return True
        except PermissionError:
            return False

    def ratify_charter(self, command: dict, signature: str) -> str:
        self._auth(command, signature, "ratify_charter")
        self._charter = dict(command["args"]["charter"])
        digest = sha256(self._charter)
        self._append("AutonomyCharterRatified", {"digest": digest, "charter": self._charter},
                     plane=Plane.OPERATOR, actor="operator")
        return digest

    def record_migration(self, command: dict, signature: str) -> str:
        """Signed migration: history stays immutable while current code may change (ChatGPT Upgrade 2)."""
        self._auth(command, signature, "migration")
        return self._append("SignedMigration", dict(command["args"]), plane=Plane.OPERATOR, actor="operator").event_id

    # -- read-only views ----------------------------------------------------------
    def charter(self) -> dict | None:
        return dict(self._charter) if self._charter else None

    def axioms(self) -> list[RevealedAxiom]:
        return active_axioms(self.axiom_history)

    def glossary(self) -> dict[str, str]:
        return {r["term"]: r["definition"] for r in self.rectifications}

    def ping(self) -> str:
        return "pong"

    def status(self) -> dict:
        return {"pid": os.getpid(), "halted": self.halted, "issued": len(self.issued),
                "budget": [self.budget_consumed, self.budget_capacity], "axioms": len(self.axioms()),
                "seal_intact": self.seal_status()["intact"], "liveness_p95_ms": self.liveness.p95(),
                "liveness_ok": self.liveness.healthy(), "gate_lineage": self.gate.lineage(),
                "charter": bool(self._charter)}


# --- process isolation ---------------------------------------------------------

def _serve(conn, kwargs: dict) -> None:
    kernel = AuthorityKernel(**kwargs)
    conn.send(("ready", kernel.status()))
    while True:
        try:
            method, args, kw = conn.recv()
        except EOFError:
            break
        if method == "__shutdown__":
            conn.send(("ok", None))
            break
        if method not in AuthorityKernel.PUBLIC:
            conn.send(("err", "PermissionError", f"{method!r} is not part of the Authority surface"))
            continue
        try:
            conn.send(("ok", getattr(kernel, method)(*args, **kw)))
        except Exception as e:  # noqa: BLE001 - errors cross the boundary as data
            conn.send(("err", type(e).__name__, str(e)))


_ERRORS = {"PermissionError": PermissionError, "ValueError": ValueError, "KeyError": KeyError, "TypeError": TypeError}


class IsolatedAuthority:
    """Client handle. Holds a pipe, never a key."""

    def __init__(self, timeout: float = 60.0, **kernel_kwargs: Any) -> None:
        ctx = mp.get_context("spawn")
        self._conn, child = ctx.Pipe()
        self._proc = ctx.Process(target=_serve, args=(child, kernel_kwargs), daemon=True, name="apex-authorityd")
        self._proc.start()
        child.close()
        if not self._conn.poll(timeout):
            self._proc.terminate()
            raise RuntimeError("authorityd did not start")
        tag, self.started = self._conn.recv()
        if tag != "ready":
            raise RuntimeError(f"authorityd failed to start: {self.started}")

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        self._conn.send((method, args, kwargs))
        tag, *rest = self._conn.recv()
        if tag == "ok":
            return rest[0]
        raise _ERRORS.get(rest[0], RuntimeError)(rest[1])

    def __getattr__(self, name: str) -> Any:
        if name in AuthorityKernel.PUBLIC:
            return functools.partial(self._call, name)
        raise AttributeError(name)

    @property
    def pid(self) -> int | None:
        return self._proc.pid

    def close(self) -> None:
        if self._proc.is_alive():
            try:
                self._conn.send(("__shutdown__", (), {}))
                self._conn.recv()
            except (EOFError, OSError, BrokenPipeError):
                pass
            self._proc.join(5)
        self._conn.close()

    def __enter__(self) -> "IsolatedAuthority":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
