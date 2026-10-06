from __future__ import annotations
import hashlib, hmac, time, uuid, json
from ..core import Decision, Proposal, ExecutionToken, uid, now


class CapabilityBroker:
    def __init__(self, signing_key: bytes):
        self._key = signing_key

    def _sign(self, payload: dict) -> str:
        msg = json.dumps(payload,sort_keys=True,separators=(",",":")).encode()
        return hmac.new(self._key,msg,hashlib.sha256).hexdigest()

    def mint(self, decision: Decision, proposal: Proposal, ttl_seconds: float = 30.0) -> list[ExecutionToken]:
        if decision.result != "approved":
            return []
        tokens = []
        for cap in proposal.requested_capabilities:
            issued = now()
            payload = {
                "decision_id":decision.id,"capability":cap,"scope":proposal.scope,
                "budget":proposal.budget,"issued_at":issued,
                "expires_at":issued+ttl_seconds,"nonce":uuid.uuid4().hex
            }
            tokens.append(ExecutionToken(
                id=uid("token"), decision_id=decision.id, capability=cap,
                resource_scope=proposal.scope, budget=proposal.budget,
                issued_at=issued, expires_at=issued+ttl_seconds,
                nonce=payload["nonce"], signature=self._sign(payload)
            ))
        return tokens
