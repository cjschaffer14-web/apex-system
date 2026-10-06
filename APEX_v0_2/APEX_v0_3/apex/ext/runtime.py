"""Actuation: VerifiedRuntime and ResourceBroker (the broker split).

The v0.2 ExecutionRuntime checked expiry, nonce and capability presence. It did
not verify the signature, scope or budget that spec section 9 requires.
VerifiedRuntime subclasses it and adds those checks, plus:

* Zero ambient authority (object-capability model): a capability function
  receives only what its token scope allows, optionally as a CapabilityHandle.
* Rectification of names (Zhengming): every capability is registered with a
  manifest of declared effects and a fingerprint of its code. If the code
  behind a name changes, the name no longer matches reality and execution is
  refused.
* Operator halt: when halted, nothing executes.

Broker split (owner's critical review): two brokers, two planes, no overlap.
  CapabilityBroker (Authority) decides what may be done. It mints rights.
  ResourceBroker   (Actuation) decides how much may be spent. It leases
                   compute and budget and protects the P-1 reserve. It can
                   never mint or widen a right.
"""
from __future__ import annotations
import os, time
from dataclasses import dataclass, field, replace
from typing import Any, Callable
from ..core import ExecutionToken, Outcome, sha256
from ..actuation.runtime import ExecutionRuntime


@dataclass(frozen=True)
class CapabilityManifest:
    name: str
    effects: tuple[str, ...]          # e.g. ("none",), ("write:outbox",), ("network",)
    reversible: bool
    cost: float = 1.0
    allowed_args: tuple[str, ...] = ()
    wants_handle: bool = False
    description: str = ""


def code_fingerprint(fn: Callable[..., Any]) -> str:
    code = getattr(fn, "__code__", None)
    if code is None:
        return sha256(repr(fn))
    return sha256({"name": code.co_name, "code": code.co_code.hex(), "consts": repr(code.co_consts),
                   "names": list(code.co_names)})


@dataclass(frozen=True)
class CapabilityHandle:
    token_id: str
    capability: str
    scope: dict
    budget: float

    def allows_path(self, path: str) -> bool:
        prefix = self.scope.get("path_prefix")
        if not prefix:
            return False
        return os.path.normpath(os.path.abspath(path)).startswith(os.path.normpath(os.path.abspath(prefix)))


@dataclass
class Lease:
    token_id: str
    cost: float
    priority: int
    committed: bool = False


class ResourceBroker:
    def __init__(self, capacity: float = 100.0, reserve_fraction: float = 0.1) -> None:
        self.capacity = capacity
        self.reserve = capacity * reserve_fraction
        self.in_use = 0.0
        self.consumed: dict[str, float] = {}

    def available(self, priority: int) -> float:
        return self.capacity - self.in_use - (0.0 if priority < 0 else self.reserve)

    def lease(self, token: ExecutionToken, cost: float, priority: int = 1) -> Lease:
        spent = self.consumed.get(token.id, 0.0)
        if spent + cost > token.budget + 1e-9:
            raise PermissionError(f"token budget exhausted ({spent}+{cost} > {token.budget})")
        if cost > self.available(priority) + 1e-9:
            raise PermissionError("lease would breach the P-1 operator reserve")
        self.in_use += cost
        return Lease(token.id, cost, priority)

    def commit(self, lease: Lease) -> None:
        if not lease.committed:
            self.consumed[lease.token_id] = self.consumed.get(lease.token_id, 0.0) + lease.cost
            lease.committed = True

    def release(self, lease: Lease) -> None:
        self.in_use = max(0.0, self.in_use - lease.cost)


class VerifiedRuntime(ExecutionRuntime):
    def __init__(self, verifier: Callable[[ExecutionToken], tuple[bool, str]],
                 resource_broker: ResourceBroker | None = None) -> None:
        super().__init__()
        self._verifier = verifier
        self.resources = resource_broker or ResourceBroker()
        self.manifests: dict[str, CapabilityManifest] = {}
        self._fingerprints: dict[str, str] = {}
        self.halted = False

    def register(self, capability: str, fn: Callable[..., Any], manifest: CapabilityManifest | None = None) -> None:
        if manifest is None or manifest.name != capability:
            raise ValueError("VerifiedRuntime requires a CapabilityManifest whose name matches the capability")
        super().register(capability, fn)
        self.manifests[capability] = manifest
        self._fingerprints[capability] = code_fingerprint(fn)

    def halt(self) -> None:
        self.halted = True

    def resume(self) -> None:
        self.halted = False

    def _check_scope(self, token: ExecutionToken, man: CapabilityManifest, kwargs: dict) -> None:
        if man.allowed_args:
            extra = sorted(set(kwargs) - set(man.allowed_args))
            if extra:
                raise PermissionError(f"arguments {extra} not declared by capability {man.name}")
        for k, v in (token.resource_scope or {}).items():
            if k == "path_prefix":
                for arg in ("path", "src", "dst"):
                    if arg in kwargs and not CapabilityHandle(token.id, man.name, token.resource_scope, 0).allows_path(kwargs[arg]):
                        raise PermissionError(f"{arg}={kwargs[arg]!r} is outside token scope {v!r}")
            elif k in kwargs and kwargs[k] != v:
                raise PermissionError(f"argument {k}={kwargs[k]!r} differs from token scope {v!r}")

    def execute(self, token: ExecutionToken | None, **kwargs: Any) -> Outcome:
        if self.halted:
            raise PermissionError("operator halt in effect")
        if token is None:
            raise PermissionError("No token, no execution")
        ok, reason = self._verifier(token)
        if not ok:
            raise PermissionError(f"token rejected by Authority: {reason}")
        man = self.manifests.get(token.capability)
        if man is None or token.capability not in self._capabilities:
            raise PermissionError("capability unavailable")
        if code_fingerprint(self._capabilities[token.capability]) != self._fingerprints[token.capability]:
            raise PermissionError("capability code changed since registration; the name no longer matches reality")
        self._check_scope(token, man, kwargs)
        lease = self.resources.lease(token, man.cost)
        try:
            if man.wants_handle:
                kwargs["handle"] = CapabilityHandle(token.id, token.capability, dict(token.resource_scope), token.budget)
            t0 = time.perf_counter()
            outcome = super().execute(token, **kwargs)
            self.resources.commit(lease)
        finally:
            self.resources.release(lease)
        return replace(outcome, resources_consumed=man.cost,
                       observations=[f"latency_ms:{(time.perf_counter() - t0) * 1000:.3f}"])
