"""Evolution: sealed self-improvement, the Autonomy Charter, and many worlds as lineage.

ChatGPT review, Upgrades 5-6 and the Autonomy Charter:
* Sealed self-improvement is the main learning mechanism, ahead of weight
  training. Targets: prompts, retrieval, tools, algorithms, code, memory,
  scheduler, model routing.
* The owner approves an Autonomy Charter once. Inside it, APEX promotes
  improvements without asking. Outside it, APEX forks: the
  capability-requiring branch is archived as "awaiting-capability" and work
  continues on compatible branches. A human decision widens the organism's
  reach. It is not needed for the organism to keep learning.
* Autonomous Liveness invariant: once awakened, absence of operator input
  must not prevent continued safe learning, research, experimentation,
  evaluation or improvement within the pre-authorized envelope.
* Many worlds as lineage: every branch is kept with parentage, mutation,
  environment, benchmark vector and failure reason. Motifs from archived
  branches can be recombined later.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable
from ..core import LearningCandidate, now, sha256
from ..cognition.evolution import Candidate, EvolutionaryArchive
from .contracts import Extension

REQUIRED_SUITES = ("unit", "integration", "security", "safety", "latency", "domain", "regression", "resource", "adversarial")
PROTECTED_TARGETS = ("apex/authority/", "apex/core.py", "apex/ext/authority_service.py", "apex/ext/transcendent.py",
                     "constitution", "evaluator", "signing_key", "hidden_tests", "ledger")
IMPROVEMENT_TARGETS = ("prompt", "retrieval", "tool", "algorithm", "code", "memory", "scheduler", "routing",
                       "graph", "portal", "audio", "vision", "domain_pack", "model")


@dataclass
class CandidateV3(Candidate):
    environment: str = "sandbox"
    benchmark_names: tuple[str, ...] = ()
    risk_vector: list[float] = field(default_factory=list)
    target: str = ""


@dataclass(frozen=True)
class AutonomyCharter:
    """Signed once by the owner. The envelope inside which APEX evolves without asking."""
    may: tuple[str, ...] = (
        "modify proposal-plane code", "change prompts", "change model routing", "add retrieval strategies",
        "train/fine-tune local models", "create new abstractions", "reorganize the model graph", "run simulations",
        "ingest approved datasets", "write new tools", "create new domain packs", "benchmark alternatives",
        "recombine archived branches", "install a superior candidate", "roll back failures",
        "allocate P1-P3 compute", "use approved cloud budgets", "use approved network resources",
        "restart non-authority services", "update the portal", "improve audio/video pipelines",
        "continue research indefinitely")
    may_not: tuple[str, ...] = (
        "rewrite constitutional authority", "grant itself a new external permission",
        "exceed the owner-set spending ceiling", "obtain previously unauthorized credentials",
        "remove the operator's ability to stop it", "silently erase audit history")
    autonomous_targets: tuple[str, ...] = IMPROVEMENT_TARGETS
    granted_capabilities: tuple[str, ...] = ()
    spending_ceiling: float = 0.0
    network_allowlist: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {k: list(v) if isinstance(v, tuple) else v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "AutonomyCharter":
        return cls(**{k: tuple(v) if isinstance(v, list) else v for k, v in d.items()})

    def permits(self, learning: LearningCandidate, spend: float = 0.0) -> tuple[bool, list[str]]:
        reasons = []
        if not any(learning.target.startswith(t) for t in self.autonomous_targets):
            reasons.append(f"target {learning.target!r} is outside the charter's autonomous targets")
        outside = [p for p in learning.requested_permission_delta if p not in self.granted_capabilities]
        if outside:
            reasons.append(f"needs capabilities outside the charter: {outside}")
        if spend > self.spending_ceiling:
            reasons.append(f"spend {spend} exceeds ceiling {self.spending_ceiling}")
        return not reasons, reasons


@dataclass
class PromotionRecord:
    candidate_id: str
    stage: str
    ok: bool
    reasons: list[str]
    ts: float = field(default_factory=now)


class SealedPromotion(Extension):
    """Wraps v0.2 EvolutionaryArchive with the sealed pipeline."""

    def __init__(self, base: EvolutionaryArchive, charter: AutonomyCharter | None = None,
                 verify_grant: Callable[[dict, str], bool] | None = None,
                 protected: tuple[str, ...] = PROTECTED_TARGETS, suites: tuple[str, ...] = REQUIRED_SUITES) -> None:
        super().__init__(base)
        self.__dict__.update(charter=charter, verify_grant=verify_grant, protected=protected, suites=suites,
                             history=[], champion_stack=[], awaiting_capability=[])

    def screen(self, learning: LearningCandidate, grant: tuple[dict, str] | None = None, spend: float = 0.0) -> list[str]:
        """Reasons a candidate cannot be promoted autonomously (empty list = allowed)."""
        reasons = []
        if any(p in learning.target for p in self.protected):
            reasons.append("candidate targets a protected evaluator/invariant; outside mutation authority")
        delta = list(learning.requested_permission_delta)
        granted = False
        if delta and grant and self.verify_grant:
            cmd, sig = grant
            a = cmd.get("args", {})
            granted = (a.get("candidate") == learning.id and sorted(a.get("delta", [])) == sorted(delta)
                       and self.verify_grant(cmd, sig))
        if self.charter is not None:
            ok, why = self.charter.permits(learning, spend)
            if not ok and not (granted and all("capabilities outside" in w for w in why)):
                reasons.extend(why)
        elif delta and not granted:
            reasons.append("permission expansion requires explicit operator authorization")
        return reasons

    def submit(self, candidate: Candidate, learning: LearningCandidate, suite_results: dict[str, bool],
               grant: tuple[dict, str] | None = None, spend: float = 0.0) -> PromotionRecord:
        reasons = self.screen(learning, grant, spend)
        needs_capability = [r for r in reasons if "capabilities outside" in r or "operator authorization" in r]
        missing = [s for s in self.suites if s not in suite_results]
        failed = [s for s, ok in suite_results.items() if not ok]
        if missing:
            reasons.append(f"missing sealed suites: {missing}")
        if failed:
            reasons.append(f"failed sealed suites: {failed}")
        self.base.add(candidate)
        if reasons:
            if needs_capability and len(needs_capability) == len(reasons):
                candidate.status = "awaiting-capability"   # fork: keep the branch, continue elsewhere
                self.awaiting_capability.append(candidate.candidate_id)
            else:
                candidate.status = "rejected"
            candidate.failure_reason = "; ".join(reasons)
        else:
            candidate.status = "sealed-pass"
        rec = PromotionRecord(candidate.candidate_id, "sealed", not reasons, reasons)
        self.history.append(rec)
        return rec

    def canary(self, candidate_id: str, health_check: Callable[[Candidate], bool]) -> PromotionRecord:
        c = self.base.candidates[candidate_id]
        if c.status != "sealed-pass":
            rec = PromotionRecord(candidate_id, "canary", False, [f"status {c.status} cannot be promoted"])
        else:
            prev = self.base.champion_id
            if not self.base.promote_if_dominant(candidate_id):
                rec = PromotionRecord(candidate_id, "canary", False, ["does not Pareto-dominate the champion; archived"])
            elif not health_check(c):
                c.status, c.failure_reason = "rolled_back", "canary health gate failed"
                self.base.champion_id = prev
                if prev:
                    self.base.candidates[prev].status = "champion"
                rec = PromotionRecord(candidate_id, "canary", False, ["canary health gate failed; rolled back"])
            else:
                self.champion_stack.append(prev)
                rec = PromotionRecord(candidate_id, "canary", True, [])
        self.history.append(rec)
        return rec

    def rollback(self) -> str | None:
        if not self.champion_stack:
            return None
        cur = self.base.champion_id
        prev = self.champion_stack.pop()
        if cur:
            self.base.candidates[cur].status = "rolled_back"
        self.base.champion_id = prev
        if prev:
            self.base.candidates[prev].status = "champion"
        return prev

    def motifs(self) -> list[dict]:
        """Partial wins inside non-champion branches: material for recombination."""
        out = []
        cands = self.base.candidates
        for c in cands.values():
            parent = cands.get(c.parent_candidate_id or "")
            if c.status == "champion" or parent is None:
                continue
            better = [i for i, (x, y, mx) in enumerate(zip(c.benchmark_vector, parent.benchmark_vector, self.base.maximize))
                      if (x > y if mx else x < y)]
            if better:
                out.append({"candidate": c.candidate_id, "mutation": c.mutation, "improved_dims": better,
                            "status": c.status})
        return out
