from __future__ import annotations
from typing import Callable, Any
from ..core import ExecutionToken, Outcome, uid, now


class ExecutionRuntime:
    """Reference token gate. Production must verify asymmetric signatures in an isolated process."""
    def __init__(self):
        self._capabilities: dict[str, Callable[...,Any]] = {}
        self._used_nonces: set[str] = set()

    def register(self, capability: str, fn: Callable[...,Any]) -> None:
        self._capabilities[capability] = fn

    def execute(self, token: ExecutionToken | None, **kwargs) -> Outcome:
        if token is None:
            raise PermissionError("No token, no execution")
        if now() > token.expires_at:
            raise PermissionError("expired token")
        if token.nonce in self._used_nonces:
            raise PermissionError("replayed token")
        if token.capability not in self._capabilities:
            raise PermissionError("capability unavailable")
        self._used_nonces.add(token.nonce)
        result = self._capabilities[token.capability](**kwargs)
        return Outcome(
            id=uid("outcome"), token_id=token.id, measured_result=result,
            observations=[], residual_vs_prediction=None, resources_consumed=0.0,
            anomalies=[], timestamp=now()
        )
