from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class DeliberationPlan:
    mode: str
    steps: list[str]
    max_iterations: int


def choose_deliberation(consequence: float, uncertainty: float, expected_gain: float, compute_cost: float) -> DeliberationPlan:
    if consequence < 0.25 and uncertainty < 0.25:
        return DeliberationPlan("FAST", ["retrieve-minimum","respond-or-simple-tool"], 1)
    if consequence < 0.7 and expected_gain > compute_cost:
        return DeliberationPlan("DEEP", [
            "generate-alternatives","retrieve-evidence","deterministic-tools",
            "counterfactual-test","critic","verifier"
        ], 6)
    return DeliberationPlan("GOVERNED", [
        "generate-alternatives","retrieve-evidence","formalize-claims",
        "counterfactual-test","critic","verifier","emit-proposal"
    ], 8)
