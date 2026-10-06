"""authorityd v0.5: v0.4 plus the leases the owner opened on 2 Oct 2026 (add-only subclass; v0.4 unchanged).

  * data.backfill is covered by the network.web lease (a bounded batch of GETs inside the lease's hosts)
  * market.paper_order needs its own lease; its scope names the venue host. The paper venue is "paper.local"
    (in-process, no network). A later live lease would name the exchange's API host the same way.
  * Pre-approvals are checked key by key: every scope list must be a subset of the pre-approved list, so a
    lease without hosts (or with other keys) is handled exactly, not by special cases.
"""
from __future__ import annotations
import functools
import multiprocessing as mp
from typing import Any
from ..core import Proposal, EvidenceBundle, now
from .contracts import Extension, tighten
from .authority_service import IsolatedAuthority
from .authority_v04 import (AuthorityKernelV4, LeaseGate, GatekeeperV4, MahalanobisShadowGate, LEASE_FOR,
                            PROTECTED_MODULES_V4, needs_lease, _reliability_view)
from .design_space import PrecedentGate
from .transcendent import TranscendentGatekeeperWrapper, AxiomGate, active_axioms
from .cybernetics import SecondOrderObserver
from .epistemics import ViabilityGate, DEFAULT_REGION

LEASE_FOR_V5 = {**LEASE_FOR, "data.backfill": "network.web", "market.paper_order": "market.paper_order"}
PROTECTED_MODULES_V5 = PROTECTED_MODULES_V4 + ("apex.ext.authority_v05",)
PAPER_VENUE = "paper.local"


def lease_name_v5(capability: str) -> str:
    return LEASE_FOR_V5.get(capability, capability)


def needs_lease_v5(capability: str) -> bool:
    return needs_lease(capability) or capability in LEASE_FOR_V5


class LeaseGateV5(LeaseGate):
    def evaluate(self, proposal: Proposal, bundles: list[EvidenceBundle], *args, **kwargs):
        decision, risk, constraint = self.base.evaluate(proposal, bundles, *args, **kwargs)
        reasons = []
        for cap in proposal.requested_capabilities:
            if not needs_lease_v5(cap):
                continue
            lease = self.kernel.active_lease(lease_name_v5(cap))
            if lease is None:
                reasons.append(f"no active lease for {lease_name_v5(cap)}")
                continue
            hosts = lease.scope.get("hosts")
            host = (proposal.scope or {}).get("host")
            if hosts and host not in hosts:
                reasons.append(f"host {host!r} is outside the {lease.capability} lease")
        return tighten(decision, reasons), risk, constraint


class AuthorityKernelV5(AuthorityKernelV4):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        g: Any = GatekeeperV4(self.constitution, kwargs.get("risk_ceiling", 0.65), self.certainty)
        g = SecondOrderObserver(g)
        g = ViabilityGate(g, kwargs.get("viability_region") or DEFAULT_REGION)
        g = AxiomGate(g, lambda: active_axioms(self.axiom_history))
        g = LeaseGateV5(g, self)
        g = MahalanobisShadowGate(g, self.sigspace)
        g = PrecedentGate(g, self.precedents)
        self.gate = TranscendentGatekeeperWrapper(g)
        self._append("AuthorityUpgraded", {"version": "0.5", "gate_lineage": self.gate.lineage(),
                                           "leased_capabilities": sorted(LEASE_FOR_V5)})

    def _compute_seal(self) -> dict[str, str]:
        import hashlib, importlib
        from pathlib import Path
        return {m: hashlib.sha256(Path(importlib.import_module(m).__file__).read_bytes()).hexdigest()
                for m in PROTECTED_MODULES_V5}

    def _within_preapproval(self, cap: str, scope: dict, ttl_s: float) -> bool:
        pre = self._preapprovals.get(cap)
        if not pre or ttl_s > pre["ttl_s"]:
            return False
        allowed = dict(pre["scope"])
        for key, val in dict(scope).items():
            if key not in allowed:
                return False
            want = set(val) if isinstance(val, (list, tuple, set)) else {val}
            have = set(allowed[key]) if isinstance(allowed[key], (list, tuple, set)) else {allowed[key]}
            if not want <= have:
                return False
        if "hosts" in allowed and not scope.get("hosts"):
            return False
        return self._condition_met(pre.get("condition", ""))

    BUDGET_WINDOW_S = 86400.0

    def evaluate(self, proposal: Proposal):
        """v0.5 also makes the action budget a rolling 24-hour window. Before, it never refilled, so a long-running
        organism would have been refused everything after about 90 approved actions."""
        t0 = now()
        self._spend = [(ts, b) for ts, b in getattr(self, "_spend", []) if t0 - ts < self.BUDGET_WINDOW_S]
        self.budget_consumed = sum(b for _, b in self._spend)
        decision, tokens, info = super().evaluate(proposal)
        if decision.result == "approved":
            self._spend.append((t0, max(0.0, float(proposal.budget))))
        for t in tokens:
            if needs_lease_v5(t.capability):
                self.issued[t.id]["lease"] = lease_name_v5(t.capability)
        return decision, tokens, info


def _serve_v5(conn, kwargs: dict) -> None:
    kernel = AuthorityKernelV5(**kwargs)
    conn.send(("ready", kernel.status()))
    while True:
        try:
            method, args, kw = conn.recv()
        except EOFError:
            break
        if method == "__shutdown__":
            conn.send(("ok", None))
            break
        if method not in AuthorityKernelV5.PUBLIC:
            conn.send(("err", "PermissionError", f"{method!r} is not part of the Authority surface"))
            continue
        try:
            fn = (lambda: _reliability_view(kernel)) if method == "reliability" else getattr(kernel, method)
            conn.send(("ok", fn(*args, **kw)))
        except Exception as e:  # noqa: BLE001
            conn.send(("err", type(e).__name__, str(e)))


class IsolatedAuthorityV5(IsolatedAuthority):
    def __init__(self, timeout: float = 60.0, **kernel_kwargs: Any) -> None:
        ctx = mp.get_context("spawn")
        self._conn, child = ctx.Pipe()
        self._proc = ctx.Process(target=_serve_v5, args=(child, kernel_kwargs), daemon=True, name="apex-authorityd-v5")
        self._proc.start()
        child.close()
        if not self._conn.poll(timeout):
            self._proc.terminate()
            raise RuntimeError("authorityd did not start")
        tag, self.started = self._conn.recv()
        if tag != "ready":
            raise RuntimeError(f"authorityd failed to start: {self.started}")

    def __getattr__(self, name: str) -> Any:
        if name in AuthorityKernelV5.PUBLIC:
            return functools.partial(self._call, name)
        raise AttributeError(name)


class LocalAuthorityV5:
    def __init__(self, **kernel_kwargs: Any) -> None:
        self._kernel = AuthorityKernelV5(**kernel_kwargs)

    def __getattr__(self, name: str) -> Any:
        if name == "reliability":
            return lambda: _reliability_view(self._kernel)
        if name in AuthorityKernelV5.PUBLIC:
            return getattr(self._kernel, name)
        raise AttributeError(name)
