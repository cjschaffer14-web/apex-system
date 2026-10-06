"""Polycentric DomainPacks: local policy inside global invariants. Packs are organs.

ChatGPT review, Upgrade 7: trading mathematics leave the universal
Constitution. The Constitution keeps domain-neutral principles (don't exceed
authorized capital, preserve operator control, don't bypass risk checks,
respect loss ceilings, keep provenance). Kelly fraction, stewardship floor,
redistribution, drawdown, slippage and strategy live in the Trading pack, so
changing an investment strategy is a pack change, not a constitutional
amendment.

Correction: the Gemini text calls the 20% floor and 2.5% redistribution
"mathematical proofs of ergodicity". They are ruin-avoidance policies
motivated by ergodicity economics (time average != ensemble average). They
are not proofs. They are kept here as configurable Trading policy.
"""
from __future__ import annotations
from dataclasses import dataclass
from ..domain.base import DomainPack
from ..domain.research import RESEARCH_PACK
from ..domain.trading import TRADING_PACK
from ..cognition.math_systems import fractional_kelly

UNIVERSAL_FORBIDDEN_PREFIXES = ("authority.", "operator.", "ledger.", "evaluator.")
UNIVERSAL_PRINCIPLES = (
    "do not exceed authorized capital", "preserve operator control", "do not bypass risk checks",
    "respect loss ceilings", "keep auditable provenance",
)


def validate_pack(pack: DomainPack, ratified_external: bool = False) -> list[str]:
    pack.validate()
    errors = []
    bad = [c for c in pack.capabilities + pack.tools if c.startswith(UNIVERSAL_FORBIDDEN_PREFIXES)]
    if bad:
        errors.append(f"{pack.name}: packs cannot expand the universal authority surface: {bad}")
    if pack.risk_policy.get("external_actuation") is True and not ratified_external:
        errors.append(f"{pack.name}: external actuation requires operator ratification")
    if pack.risk_policy.get("live_default") is True:
        errors.append(f"{pack.name}: live execution cannot be a default")
    if pack.name != "trading" and any("kelly" in k for k in pack.risk_policy):
        errors.append(f"{pack.name}: capital formulas belong to the Trading pack only")
    return errors


@dataclass(frozen=True)
class CapitalStewardshipPolicy:
    """Trading-pack policy. Defaults follow the APEX corpus; all are owner-configurable."""
    stewardship_floor: float = 0.20     # fraction of equity never deployed
    redistribution_rate: float = 0.025  # of realised profit (Zakat/Tzedakah correspondence, E4)
    kelly_fraction: float = 0.25
    max_position: float = 0.10
    drawdown_halt: float = 0.20

    def deployable(self, equity: float, deployed: float) -> float:
        return max(0.0, equity * (1 - self.stewardship_floor) - deployed)

    def size(self, equity: float, deployed: float, win_prob: float, payoff: float, estimation_sd: float = 0.0) -> float:
        """Fractional Kelly with the edge shrunk by estimation uncertainty, then capped."""
        f = fractional_kelly(max(0.0, win_prob - estimation_sd), payoff, self.kelly_fraction)
        return min(f * equity, self.max_position * equity, self.deployable(equity, deployed))

    def check_order(self, equity: float, deployed: float, order_value: float, drawdown: float) -> tuple[bool, list[str]]:
        r = []
        if drawdown >= self.drawdown_halt:
            r.append(f"drawdown {drawdown:.2%} >= halt {self.drawdown_halt:.0%}")
        if order_value > self.deployable(equity, deployed) + 1e-9:
            r.append("order would breach the stewardship floor")
        if order_value > self.max_position * equity + 1e-9:
            r.append("order exceeds max position")
        return not r, r

    def redistribution(self, realized_profit: float) -> float:
        return max(0.0, realized_profit) * self.redistribution_rate


CODING_PACK = DomainPack(
    name="coding", schemas=["repo", "diff", "test_result", "benchmark"],
    tools=["fs.read_scoped", "fs.write_scoped", "proc.run_sandboxed", "tests.run"],
    models=["local_coder", "optional_cloud_peer"], evaluators=["unit", "integration", "regression", "security_lint"],
    risk_policy={"external_actuation": False, "write_scope": "sandbox worktree only"},
    memory_rules={"keep_failed_diffs": True}, benchmarks=["repair_rate", "regression_free"],
    capabilities=["fs.write_scoped", "proc.run_sandboxed"])
MEDIA_PACK = DomainPack(
    name="media", schemas=["frame", "clip", "avatar_state", "render_job"],
    tools=["render.local", "vision.novelty"], models=["renderer", "novelty_detector"],
    evaluators=["latency", "fidelity"], risk_policy={"external_actuation": False, "capture": "operator-enabled only"},
    memory_rules={"raw_media_retention_days": 7}, benchmarks=["frame_latency"], capabilities=["render.local"])
CYBERSECURITY_PACK = DomainPack(
    name="cybersecurity", schemas=["asset", "finding", "advisory"],
    tools=["scan.local_readonly", "advisory.lookup"], models=["triage"], evaluators=["false_positive_rate"],
    risk_policy={"external_actuation": False, "scope": "owner's own systems, read-only, defensive"},
    memory_rules={}, benchmarks=["triage_precision"], capabilities=["scan.local_readonly"])
PERSONAL_OPS_PACK = DomainPack(
    name="personal_ops", schemas=["task", "event", "message_draft"],
    tools=["calendar.read", "files.read", "notify.local", "notify.email"], models=["planner"],
    evaluators=["owner_satisfaction"], risk_policy={"external_actuation": False, "owner_notification": True},
    memory_rules={"owner_private": True}, benchmarks=["reminder_precision"],
    capabilities=["notify.local", "notify.email", "calendar.read"])

ALL_PACKS = [RESEARCH_PACK, CODING_PACK, TRADING_PACK, MEDIA_PACK, CYBERSECURITY_PACK, PERSONAL_OPS_PACK]

# Organogenesis: packs are organs differentiated from one genome, not separate agents.
ORGANS = {
    "research": "cortex / scientific faculty", "coding": "construction and repair system",
    "memory": "long-term nervous system", "scheduler": "autonomic nervous system",
    "authority": "regulatory nervous/endocrine system", "portal": "face / expressive surface",
    "audio": "ears and voice", "vision": "eyes", "trading": "specialised metabolic organ",
    "cloud": "extended environment / reserve tissue",
}
