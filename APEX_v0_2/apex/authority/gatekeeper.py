from __future__ import annotations
from dataclasses import asdict
from ..core import Proposal, EvidenceBundle, RiskRecord, ConstraintRecord, Decision, uid, now
from ..cognition.math_systems import evidence_certainty, risk_score
from .constitution import Constitution


class Gatekeeper:
    def __init__(self, constitution: Constitution, risk_ceiling: float = 0.65):
        self.constitution = constitution
        self.risk_ceiling = risk_ceiling

    def _recompute_e(self, bundles: list[EvidenceBundle]) -> float:
        if not bundles:
            return 0.0
        vals = [
            evidence_certainty(
                b.measurement_quality, b.independence, b.reproducibility,
                b.domain_fit, b.staleness,
                contradiction=min(1.0, len(b.counterevidence)/max(1, len(b.observations)+1))
            ) for b in bundles
        ]
        return sum(vals)/len(vals)

    def evaluate(self, proposal: Proposal, bundles: list[EvidenceBundle],
                 constraint_capacity: float = 1.0, constraint_consumed: float = 0.0) -> tuple[Decision,RiskRecord,ConstraintRecord]:
        e = self._recompute_e(bundles)
        # Authority ignores proposal confidence/risk advisory values and recomputes.
        p = min(1.0, max(0.0, 1.0-e))
        impact = min(1.0, 0.2 + 0.25*proposal.consequence_tier)
        irreversibility = 0.0 if proposal.reversible else 1.0
        rscore = risk_score(p, impact, irreversibility, 0.25, min(1.0,0.25*proposal.consequence_tier))
        risk = RiskRecord(uid("risk"),p,impact,1-irreversibility,0.75,
                          min(1.0,0.25*proposal.consequence_tier),rscore)
        remaining = max(0.0, constraint_capacity-constraint_consumed)
        headroom = remaining/max(1e-9,constraint_capacity)
        constraint = ConstraintRecord(uid("constraint"),"default",constraint_capacity,
                                      constraint_consumed,remaining,headroom,0.1)

        reasons = []
        if rscore > self.risk_ceiling:
            reasons.append(f"risk score {rscore:.3f} exceeds ceiling {self.risk_ceiling:.3f}")
        if headroom <= constraint.failure_threshold:
            reasons.append("insufficient resource headroom")
        cr = self.constitution.evaluate(proposal.requested_capabilities,
                                        proposal.consequence_tier,e,proposal.reversible)
        reasons.extend(cr.reasons)
        result = "approved" if not reasons else "denied"
        decision = Decision(uid("decision"),proposal.id,result,reasons,e,
                            risk.id,constraint.id,now())
        return decision,risk,constraint
