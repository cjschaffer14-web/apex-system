"""Executable contracts and the add-only extension mechanism.

v0.2 runtime rule (ABSTRACTION_MAP): every abstraction that affects action must
terminate in an executable contract declaring inputs, outputs, state,
permissions, uncertainty/error representation, budget, failure modes,
telemetry, tests and rollback behaviour. v0.2 stated the rule; v0.3 enforces it.

The Extension base class is the "Protocol Wrapper & Contract Injection"
pattern from the Gemini synthesis: an extension holds a reference to a base
object, never mutates it, and delegates anything it does not override. Base
files stay byte-identical; lineage stays inspectable through `.base`.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, replace
from typing import Any
from ..core import Plane, Decision, sha256

REQUIRED_FIELDS = (
    "inputs", "outputs", "state", "permissions", "uncertainty",
    "budget", "failure_modes", "telemetry", "tests", "rollback",
)

# Maturity levels from v0.2 core.EvidenceLevel. E4 (metaphor/philosophy) and
# E5 (unresolved frontier) may describe or interpret, never gate action.
NON_ACTIONABLE_LEVELS = ("E4", "E5")


def maturity_floor(maturity: str) -> str:
    """'E2/E3' -> 'E2'. The most mature level the abstraction claims."""
    return maturity.split("/")[0].strip()


def maturity_ceiling(maturity: str) -> str:
    """'E2/E3' -> 'E3'. The least mature level the abstraction admits to."""
    return maturity.split("/")[-1].strip()


@dataclass(frozen=True)
class ExecutableContract:
    name: str
    plane: str
    maturity: str
    affects_action: bool
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    state: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    uncertainty: str = ""
    budget: str = ""
    failure_modes: tuple[str, ...] = ()
    telemetry: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    rollback: str = ""
    source: str = ""  # traceability: which document/decision introduced it

    def missing(self) -> list[str]:
        return [f for f in REQUIRED_FIELDS if not getattr(self, f)]

    def validate(self) -> None:
        if self.plane not in {p.value for p in Plane}:
            raise ValueError(f"{self.name}: unknown plane {self.plane!r}")
        if self.affects_action:
            gaps = self.missing()
            if gaps:
                raise ValueError(f"{self.name}: action-affecting contract missing {gaps}")
            if maturity_ceiling(self.maturity) in NON_ACTIONABLE_LEVELS:
                raise ValueError(
                    f"{self.name}: maturity {self.maturity} is metaphor/frontier; "
                    "it may interpret but must not affect action"
                )

    def fingerprint(self) -> str:
        return sha256(asdict(self))


class ContractRegistry:
    """Add-only registry. Re-registering a name appends a new revision."""

    def __init__(self) -> None:
        self._revisions: dict[str, list[ExecutableContract]] = {}

    def register(self, contract: ExecutableContract) -> ExecutableContract:
        contract.validate()
        self._revisions.setdefault(contract.name, []).append(contract)
        return contract

    def current(self, name: str) -> ExecutableContract:
        return self._revisions[name][-1]

    def history(self, name: str) -> list[ExecutableContract]:
        return list(self._revisions.get(name, []))

    def names(self) -> list[str]:
        return sorted(self._revisions)

    def fingerprint(self) -> str:
        return sha256({n: [c.fingerprint() for c in revs] for n, revs in sorted(self._revisions.items())})


CONTRACTS = ContractRegistry()


class Extension:
    """Wrap a base object without touching it.

    Subclasses override only what they extend. Everything else is delegated,
    so a wrapped Gatekeeper is still a Gatekeeper to its callers: the wrapper
    is a structure-preserving map (an endofunctor on the component's interface).
    """

    contract: ExecutableContract | None = None

    def __init__(self, base: Any) -> None:
        self.__dict__["base"] = base

    def __getattr__(self, name: str) -> Any:
        base = self.__dict__.get("base")
        if base is None:
            raise AttributeError(name)
        return getattr(base, name)

    def lineage(self) -> list[str]:
        """Outermost-to-innermost chain of wrapper/base class names."""
        chain, cur = [], self
        while True:
            chain.append(type(cur).__name__)
            nxt = cur.__dict__.get("base") if isinstance(cur, Extension) else None
            if nxt is None:
                return chain
            cur = nxt

    def innermost(self) -> Any:
        cur = self
        while isinstance(cur, Extension):
            cur = cur.__dict__["base"]
        return cur


def tighten(decision: Decision, reasons: list[str]) -> Decision:
    """Tighten-only transform used by every Authority-side wrapper.

    A wrapper may turn an approval into a denial and may add reasons. It can
    never turn a denial into an approval. Only the Operator can do that, and
    only through the authenticated override path.
    """
    if not reasons:
        return decision
    result = decision.result if decision.result != "approved" else "denied"
    return replace(decision, result=result, reasons=list(decision.reasons) + list(reasons))
