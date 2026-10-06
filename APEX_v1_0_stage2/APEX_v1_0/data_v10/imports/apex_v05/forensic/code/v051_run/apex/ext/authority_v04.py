"""authorityd v0.4: ratified changes layered over the v0.3 kernel (no v0.3 file edited).

Adds, by subclassing AuthorityKernel:
  * GatekeeperV4: two-stage certainty (CertaintyModel) in place of the linear aggregate.
  * Channel trust split: static AuthorizationTrust (channel table) capped by learned
    EpistemicReliability (ReliabilityBook); updated only from reported outcomes.
  * MahalanobisShadowGate: SIG_* signatures replace timeline letters (tighten-only).
  * Capability leases: one lease per capability, expiry, revoke without a new charter.
    Sensor leases (audio.capture, vision.capture) may be granted from any owner input
    in an unlocked session; every other lease needs verified presence or a ratified
    pre-approval (e.g. the six-host web lease that opens once the T0 gate passes).
  * Token lifetime by tier: 30 / 10 / 5 s for tiers 0-1 / 2 / 3. Every token is still
    verified online by authorityd, which satisfies "tier 3 always checked online".
  * Shell continuity: leases, pre-approvals, reliability and calibration rebuild from the ledger.
"""
from __future__ import annotations
import functools, os, time
import multiprocessing as mp
from dataclasses import asdict, dataclass, replace
from typing import Any
from ..core import Proposal, EvidenceBundle, Plane, uid, now
from ..authority.gatekeeper import Gatekeeper
from .contracts import Extension, ExecutableContract, CONTRACTS, tighten
from .authority_service import (AuthorityKernel, IsolatedAuthority, PROTECTED_MODULES, decorrelate,
                                UNKNOWN_CHANNEL_TRUST, _ERRORS)
from .design_space import PrecedentGate, proposal_features, vec
from .transcendent import TranscendentGatekeeperWrapper, AxiomGate, active_axioms
from .cybernetics import SecondOrderObserver
from .epistemics import ViabilityGate, DEFAULT_REGION
from .v04_math import CertaintyModel, ReliabilityBook, SignatureSpace, SIGNATURES

TTL_BY_TIER = {0: 30.0, 1: 30.0, 2: 10.0, 3: 5.0}
SENSOR_CAPABILITIES = ("audio.capture", "vision.capture")
LEASE_FOR = {"data.fetch": "network.web"}          # capability -> the lease that covers it
LEASED_PREFIXES = ("network.", "data.fetch", "audio.capture", "vision.capture", "market.", "cloud.", "apps.", "services.")
PROTECTED_MODULES_V4 = PROTECTED_MODULES + ("apex.ext.v04_math", "apex.ext.authority_v04")


def lease_name(capability: str) -> str:
    return LEASE_FOR.get(capability, capability)


def needs_lease(capability: str) -> bool:
    return capability.startswith(LEASED_PREFIXES)


@dataclass
class Lease:
    id: str
    capability: str
    granted_at: float
    expires_at: float
    scope: dict
    via: str
    presence: str
    revoked: bool = False

    def active(self, t: float) -> bool:
        return not self.revoked and t < self.expires_at


class GatekeeperV4(Gatekeeper):
    def __init__(self, constitution, risk_ceiling: float = 0.65, certainty: CertaintyModel | None = None) -> None:
        super().__init__(constitution, risk_ceiling)
        self.certainty = certainty or CertaintyModel()
        self.last_raw = 0.0

    def _recompute_e(self, bundles: list[EvidenceBundle]) -> float:
        if not bundles:
            self.last_raw = 0.0
            return 0.0
        raws, cals = [], []
        for b in bundles:
            c = min(1.0, len(b.counterevidence) / max(1, len(b.observations) + 1))
            args = (b.measurement_quality, b.independence, b.reproducibility, b.domain_fit, b.staleness, c)
            raws.append(self.certainty.raw(*args))
            cals.append(self.certainty.score(*args))
        self.last_raw = sum(raws) / len(raws)
        return sum(cals) / len(cals)


class MahalanobisShadowGate(Extension):
    def __init__(self, base: Any, space: SignatureSpace, min_tier: int = 2) -> None:
        super().__init__(base)
        self.__dict__.update(space=space, min_tier=min_tier, last={})

    def evaluate(self, proposal: Proposal, bundles: list[EvidenceBundle], *args, **kwargs):
        decision, risk, constraint = self.base.evaluate(proposal, bundles, *args, **kwargs)
        f = proposal_features(proposal, bundles, decision.epistemic_certainty)
        hits = self.space.hits(vec(f))
        reasons = []
        if proposal.consequence_tier >= self.min_tier:
            for sig, d in hits:
                reasons.append(f"shadow: resembles {sig} ({SIGNATURES[sig]['meaning']}) at Mahalanobis distance {d}")
            if f["capital_fraction"] > 0.5 and f["epistemic_certainty"] < 0.85:
                reasons.append("ruin-adjacent: high capital fraction with certainty < 0.85; re-propose smaller")
        self.__dict__["last"] = {"features": f, "hits": hits}
        return tighten(decision, reasons), risk, constraint


class LeaseGate(Extension):
    """A leased capability needs an active lease, and a host inside the lease's scope (tighten-only)."""

    def __init__(self, base: Any, kernel: "AuthorityKernelV4") -> None:
        super().__init__(base)
        self.__dict__["kernel"] = kernel

    def evaluate(self, proposal: Proposal, bundles: list[EvidenceBundle], *args, **kwargs):
        decision, risk, constraint = self.base.evaluate(proposal, bundles, *args, **kwargs)
        reasons = []
        for cap in proposal.requested_capabilities:
            if not needs_lease(cap):
                continue
            lease = self.kernel.active_lease(lease_name(cap))
            if lease is None:
                reasons.append(f"no active lease for {lease_name(cap)}")
                continue
            hosts = lease.scope.get("hosts")
            host = (proposal.scope or {}).get("host")
            if hosts and host not in hosts:
                reasons.append(f"host {host!r} is outside the {lease.capability} lease")
        return tighten(decision, reasons), risk, constraint


class AuthorityKernelV4(AuthorityKernel):
    PUBLIC = AuthorityKernel.PUBLIC | frozenset({
        "grant_lease", "revoke_lease", "leases", "preapprove_lease", "preapprovals", "reliability", "calibration_status"})

    def __init__(self, *args: Any, certainty: CertaintyModel | None = None, **kwargs: Any) -> None:
        self.certainty = certainty or CertaintyModel()
        self.reliability = ReliabilityBook()
        self.sigspace = SignatureSpace()
        self._leases: dict[str, Lease] = {}
        self._preapprovals: dict[str, dict] = {}
        self._calib_pairs: list[tuple[float, bool]] = []
        self._decision_meta: dict[str, dict] = {}
        super().__init__(*args, **kwargs)
        g: Any = GatekeeperV4(self.constitution, kwargs.get("risk_ceiling", 0.65), self.certainty)
        g = SecondOrderObserver(g)
        g = ViabilityGate(g, kwargs.get("viability_region") or DEFAULT_REGION)
        g = AxiomGate(g, lambda: active_axioms(self.axiom_history))
        g = LeaseGate(g, self)
        g = MahalanobisShadowGate(g, self.sigspace)
        g = PrecedentGate(g, self.precedents)
        self.gate = TranscendentGatekeeperWrapper(g)
        self._append("AuthorityUpgraded", {"version": "0.4", "gate_lineage": self.gate.lineage(),
                                           "ttl_by_tier": TTL_BY_TIER, "leases": len(self._leases),
                                           "calibrated": bool(self.certainty.calibration)})

    # -- seal and continuity --------------------------------------------------------
    def _compute_seal(self) -> dict[str, str]:
        import hashlib, importlib
        from pathlib import Path
        return {m: hashlib.sha256(Path(importlib.import_module(m).__file__).read_bytes()).hexdigest()
                for m in PROTECTED_MODULES_V4}

    def _restore(self) -> dict:
        out = super()._restore()
        for row in self.ledger.read():
            t, pl = row.get("event_type"), row.get("payload", {}) or {}
            if t == "LeaseGranted":
                self._leases[pl["capability"]] = Lease(**pl)
            elif t == "LeaseRevoked" and pl.get("capability") in self._leases:
                self._leases[pl["capability"]].revoked = True
            elif t == "LeasePreapproved":
                self._preapprovals[pl["capability"]] = pl
            elif t == "ReliabilityUpdated":
                self.reliability.restore(pl["source"], pl["alpha"], pl["beta"])
            elif t == "CalibrationSample":
                self._calib_pairs.append((float(pl["raw"]), bool(pl["success"])))
        self.certainty.fit_calibration(self._calib_pairs)
        out.update(leases=len(self._leases), reliability_sources=len(self.reliability.book),
                   calibration_samples=len(self._calib_pairs))
        return out

    # -- trust split --------------------------------------------------------------------
    def _channel_trust(self, b: EvidenceBundle) -> float:
        chans = [p.split(":", 1)[1] for p in b.source_provenance if str(p).startswith("channel:")]
        return min((self.channel_trust.get(c, UNKNOWN_CHANNEL_TRUST) for c in chans), default=UNKNOWN_CHANNEL_TRUST)

    def _normalize(self, b: EvidenceBundle) -> EvidenceBundle:
        nb = super()._normalize(b)
        roots = [p for p in nb.source_provenance if str(p).startswith("source:")]
        if roots:
            auth = self._channel_trust(nb)
            rel = min(self.reliability.cap(r, auth) for r in roots)
            nb = replace(nb, measurement_quality=min(nb.measurement_quality, rel),
                         reproducibility=min(nb.reproducibility, rel))
        return nb

    # -- evaluate / outcomes ------------------------------------------------------------
    def evaluate(self, proposal: Proposal):
        self.token_ttl = TTL_BY_TIER.get(int(proposal.consequence_tier), 5.0)
        decision, tokens, info = super().evaluate(proposal)
        bundles = [self.evidence[b] for b in proposal.evidence_bundles if b in self.evidence]
        clean = [b for b in bundles if not any(str(p) == "flag:quarantined" for p in b.source_provenance)]
        groups = [sorted({p for p in m.source_provenance if str(p).startswith("source:")}) for m in decorrelate(clean)[0]]
        raw = getattr(self.gate.innermost(), "last_raw", 0.0)
        self._decision_meta[decision.id] = {"groups": [g for g in groups if g], "raw": raw,
                                            "trust": {s: self._channel_trust(b) for b in clean for s in b.source_provenance
                                                      if str(s).startswith("source:")}}
        for t in tokens:
            if needs_lease(t.capability):
                self.issued[t.id]["lease"] = lease_name(t.capability)
        if decision.result == "approved" and info.get("features"):
            self.sigspace.add(vec(info["features"]))
        info["ttl_s"] = self.token_ttl
        return decision, tokens, info

    def report_outcome(self, token_id: str, success: bool, residual: float | None = None,
                       resources: float = 0.0, detail: dict | None = None) -> None:
        super().report_outcome(token_id, success, residual, resources, detail)
        meta = self._decision_meta.get(self.issued[token_id]["decision_id"])
        if not meta:
            return
        for group in meta["groups"]:
            w = 1.0 / len(group)
            for src in group:
                applied, m = self.reliability.update(src, success, meta["trust"].get(src, UNKNOWN_CHANNEL_TRUST), w)
                if applied:
                    b = self.reliability.book[src]
                    self._append("ReliabilityUpdated", {"source": src, "alpha": b.alpha, "beta": b.beta, "mean": m})
        self._calib_pairs.append((meta["raw"], bool(success)))
        self._append("CalibrationSample", {"raw": meta["raw"], "success": bool(success)})
        if len(self._calib_pairs) >= self.certainty.min_outcomes and len(self._calib_pairs) % 10 == 0:
            if self.certainty.fit_calibration(self._calib_pairs):
                self._append("CertaintyCalibrated", {"samples": len(self._calib_pairs), "blocks": len(self.certainty.calibration)})

    # -- leases -----------------------------------------------------------------------------
    def active_lease(self, capability: str) -> Lease | None:
        lease = self._leases.get(capability)
        return lease if lease and lease.active(now()) else None

    def preapprove_lease(self, command: dict, signature: str) -> dict:
        self._auth(command, signature, "preapprove_lease")
        a = command["args"]
        if a.get("presence") != "verified":
            raise PermissionError("a lease pre-approval needs verified owner presence")
        rec = {"capability": a["capability"], "scope": dict(a.get("scope") or {}), "ttl_s": float(a["ttl_s"]),
               "condition": a.get("condition", ""), "approved_on": a.get("approved_on", ""),
               "revision": int(a.get("revision", 1))}
        self._preapprovals[rec["capability"]] = rec
        self._append("LeasePreapproved", rec, plane=Plane.OPERATOR, actor="operator")
        return rec

    def _condition_met(self, condition: str) -> bool:
        """A pre-approval may name a condition. Known conditions are checked against the ledger, so the
        opening is auditable; an unknown condition is never treated as met."""
        if not condition:
            return True
        if condition == "t0_gate_passed":
            return any(r.get("event_type") == "T0GateEvaluated" and (r.get("payload") or {}).get("passed") is True
                       for r in self.ledger.read())
        return False

    def _within_preapproval(self, cap: str, scope: dict, ttl_s: float) -> bool:
        pre = self._preapprovals.get(cap)
        if not pre or ttl_s > pre["ttl_s"]:
            return False
        hosts, allowed = set(scope.get("hosts") or []), set(pre["scope"].get("hosts") or [])
        methods, allowed_m = set(scope.get("methods") or ["GET"]), set(pre["scope"].get("methods") or ["GET"])
        return bool(hosts) and hosts <= allowed and methods <= allowed_m and self._condition_met(pre.get("condition", ""))

    def grant_lease(self, command: dict, signature: str) -> dict:
        self._auth(command, signature, "grant_lease")
        a = command["args"]
        cap, scope, ttl = a["capability"], dict(a.get("scope") or {}), float(a.get("ttl_s", 3600))
        presence = a.get("presence", "session")
        if cap.startswith(("authority.", "operator.", "ledger.", "evaluator.")):
            raise PermissionError("leases cannot cover the authority surface")
        if cap not in SENSOR_CAPABILITIES:
            if presence == "preapproved":
                if not self._within_preapproval(cap, scope, ttl):
                    raise PermissionError(f"{cap}: outside the ratified pre-approval, or its condition is not yet met")
            elif presence != "verified":
                raise PermissionError(f"{cap}: needs verified owner presence or a ratified pre-approval")
        t = now()
        lease = Lease(uid("lease"), cap, t, t + ttl, scope, a.get("via", "typed"), presence)
        self._leases[cap] = lease
        self._append("LeaseGranted", asdict(lease), plane=Plane.OPERATOR, actor="operator")
        return asdict(lease)

    def revoke_lease(self, command: dict, signature: str) -> int:
        """Returns 0 if nothing was active, else 1 + the number of live tokens revoked with it."""
        self._auth(command, signature, "revoke_lease")
        cap = command["args"]["capability"]
        lease = self._leases.get(cap)
        if lease is None or lease.revoked:
            return 0
        lease.revoked = True
        n = 0
        for rec in self.issued.values():  # tokens minted under this lease die with it
            if not rec["revoked"] and not rec["used"] and rec.get("lease") == cap:
                rec["revoked"] = True
                n += 1
        self._append("LeaseRevoked", {"capability": cap, "via": command["args"].get("via", "typed"),
                                       "revoked_tokens": n}, plane=Plane.OPERATOR, actor="operator")
        return n + 1

    def leases(self) -> list[dict]:
        t = now()
        return [dict(asdict(l), active=l.active(t)) for l in self._leases.values()]

    def preapprovals(self) -> list[dict]:
        return list(self._preapprovals.values())

    def calibration_status(self) -> dict:
        return {"samples": len(self._calib_pairs), "fitted": bool(self.certainty.calibration),
                "min_outcomes": self.certainty.min_outcomes}


# `kernel.reliability` is the ReliabilityBook itself; the public "reliability" read returns this view.
def _reliability_view(kernel: AuthorityKernelV4) -> dict[str, float]:
    return {k: round(v.mean, 4) for k, v in kernel.__dict__["reliability"].book.items()}


def _serve_v4(conn, kwargs: dict) -> None:
    kernel = AuthorityKernelV4(**kwargs)
    conn.send(("ready", kernel.status()))
    while True:
        try:
            method, args, kw = conn.recv()
        except EOFError:
            break
        if method == "__shutdown__":
            conn.send(("ok", None))
            break
        if method not in AuthorityKernelV4.PUBLIC:
            conn.send(("err", "PermissionError", f"{method!r} is not part of the Authority surface"))
            continue
        try:
            fn = (lambda: _reliability_view(kernel)) if method == "reliability" else getattr(kernel, method)
            conn.send(("ok", fn(*args, **kw)))
        except Exception as e:  # noqa: BLE001
            conn.send(("err", type(e).__name__, str(e)))


class IsolatedAuthorityV4(IsolatedAuthority):
    def __init__(self, timeout: float = 60.0, **kernel_kwargs: Any) -> None:  # noqa: D401 - same contract as v0.3
        ctx = mp.get_context("spawn")
        self._conn, child = ctx.Pipe()
        self._proc = ctx.Process(target=_serve_v4, args=(child, kernel_kwargs), daemon=True, name="apex-authorityd-v4")
        self._proc.start()
        child.close()
        if not self._conn.poll(timeout):
            self._proc.terminate()
            raise RuntimeError("authorityd did not start")
        tag, self.started = self._conn.recv()
        if tag != "ready":
            raise RuntimeError(f"authorityd failed to start: {self.started}")

    def __getattr__(self, name: str) -> Any:
        if name in AuthorityKernelV4.PUBLIC:
            return functools.partial(self._call, name)
        raise AttributeError(name)


class LocalAuthorityV4:
    """In-process handle with the same surface (tests and --no-isolation)."""

    def __init__(self, **kernel_kwargs: Any) -> None:
        self._kernel = AuthorityKernelV4(**kernel_kwargs)

    def __getattr__(self, name: str) -> Any:
        if name == "reliability":
            return lambda: _reliability_view(self._kernel)
        if name in AuthorityKernelV4.PUBLIC:
            return getattr(self._kernel, name)
        raise AttributeError(name)


CONTRACTS.register(ExecutableContract(
    name="LeaseGate", plane="authority", maturity="E1", affects_action=True,
    inputs=("Proposal", "Lease[]"), outputs=("Decision (tightened)",), state=("lease book (ledger-backed)",),
    permissions=("read:leases",), uncertainty="deterministic", budget="O(capabilities)",
    failure_modes=("expired lease denies a long task -> owner renews by voice or command",),
    telemetry=("LeaseGranted / LeaseRevoked events",), tests=("test_leases_gate_and_revoke",),
    rollback="revoke_lease; history kept", source="Ratified decision 7 (DeepSeek 2.13, Gemini Q17)",
))
