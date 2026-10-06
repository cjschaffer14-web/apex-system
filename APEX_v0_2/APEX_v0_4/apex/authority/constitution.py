from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ConstitutionalResult:
    allowed: bool
    reasons: list[str]


class Constitution:
    """Small invariant surface. Domain-specific policies live in DomainPacks."""
    FORBIDDEN_DIRECT_CAPABILITIES = {"authority.mint", "authority.modify_evaluator"}

    def evaluate(self, requested_capabilities: list[str], consequence_tier: int,
                 epistemic_certainty: float, reversible: bool) -> ConstitutionalResult:
        reasons = []
        forbidden = self.FORBIDDEN_DIRECT_CAPABILITIES.intersection(requested_capabilities)
        if forbidden:
            reasons.append(f"forbidden authority capabilities: {sorted(forbidden)}")
        threshold = 0.95 if consequence_tier < 3 else 0.999
        if epistemic_certainty < threshold:
            reasons.append(f"epistemic threshold not met: {epistemic_certainty:.3f} < {threshold}")
        if consequence_tier >= 3 and not reversible:
            # v0.2 requires explicit recovery metadata before such actions;
            # this reference implementation denies by default.
            reasons.append("irreversible tier-3 action requires explicit recovery/second authorization")
        return ConstitutionalResult(not reasons, reasons)
