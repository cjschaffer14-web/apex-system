"""Operator sovereignty: owner identity, reachability and the P-1 channel.

Owner's vision: the system can identify its owner and find them through
real-world channels such as email. APEX is single-user. The owner is the sole
principal, and owner action must be possible at all times.

* OwnerProfile holds identity and ranked contact channels. No address is
  hard-coded; channels come from local configuration.
* OperatorChannel signs commands with the operator key. Halt is always
  available and never waits for Proposal-plane approval.
* Escalation always writes to the local outbox (no network needed). Reaching
  the owner over email is an external actuation: it is proposed, gated and
  token-checked like any other action. The reference build's email capability
  is a dry run that records what it would send.
* PropheticOperatorChannel keeps the Gemini Block X vocabulary (miracle
  override, Zhengming) as aliases over the same authenticated mechanism.

Limitation (stated honestly): the operator key is an HMAC secret held in this
process. Production should keep it in the Secure Enclave behind a
user-presence check so Proposal-plane code in the same process cannot sign.
`presence_check` is the hook for that.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable
from ..core import Proposal, uid, now
from .authority_service import operator_sign, new_command


@dataclass(frozen=True)
class ContactChannel:
    kind: str            # local_console | outbox_file | email | sms | push
    address: str
    verified: bool = False
    priority: int = 0


@dataclass
class OwnerProfile:
    owner_id: str
    display_name: str
    channels: list[ContactChannel] = field(default_factory=list)

    def reachable(self) -> list[ContactChannel]:
        return sorted((c for c in self.channels if c.verified), key=lambda c: c.priority)

    @classmethod
    def from_file(cls, path: str | Path) -> "OwnerProfile":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(d["owner_id"], d.get("display_name", d["owner_id"]),
                   [ContactChannel(**c) for c in d.get("channels", [])])


class OperatorChannel:
    def __init__(self, authority: Any, key: bytes, owner: OwnerProfile, runtime: Any = None, scheduler: Any = None,
                 outbox: str | Path = "state/operator_outbox.jsonl",
                 presence_check: Callable[[str], bool] | None = None) -> None:
        self.authority, self._key, self.owner = authority, bytes(key), owner
        self.runtime, self.scheduler = runtime, scheduler
        self.outbox = Path(outbox)
        self.presence_check = presence_check

    def _signed(self, cmd: str, **args: Any) -> tuple[dict, str]:
        if self.presence_check and not self.presence_check(cmd):
            raise PermissionError("operator presence not confirmed")
        c = new_command(cmd, **args)
        return c, operator_sign(self._key, c)

    # -- always-available controls ---------------------------------------------
    def halt(self, reason: str = "") -> dict:
        if self.runtime is not None:
            self.runtime.halt()
        stopped = self.scheduler.halt() if self.scheduler is not None else []
        revoked = self.authority.halt(*self._signed("halt", reason=reason))
        return {"revoked_tokens": revoked, "stopped_jobs": stopped}

    def resume(self, reason: str = "") -> None:
        self.authority.resume(*self._signed("resume", reason=reason))
        if self.runtime is not None:
            self.runtime.resume()

    # -- sovereign decisions -------------------------------------------------------
    def override(self, proposal: Proposal, rationale: str, origin: str = "OPERATOR"):
        return self.authority.operator_override(*self._signed(
            "override", proposal=asdict(proposal), rationale=rationale, origin=origin))

    def ratify(self, kind: str, value: Any, rationale: str, supersedes: str | None = None,
               origin: str = "TRANSCENDENT_REVELATION"):
        return self.authority.ratify(*self._signed("ratify", kind=kind, value=value, rationale=rationale,
                                                   supersedes=supersedes, origin=origin))

    def rectify(self, term: str, definition: str) -> dict:
        return self.authority.rectify(*self._signed("rectify", term=term, definition=definition))

    def ratify_charter(self, charter: dict) -> str:
        return self.authority.ratify_charter(*self._signed("ratify_charter", charter=charter))

    def grant_permission_delta(self, candidate_id: str, delta: list[str]) -> tuple[dict, str]:
        """A reusable, candidate-specific grant for a permission expansion."""
        return self._signed("authorize_permission_delta", candidate=candidate_id, delta=sorted(delta))

    # -- reachability ---------------------------------------------------------------
    def notify(self, message: str, severity: str = "info", **context: Any) -> dict:
        rec = {"id": uid("note"), "ts": now(), "owner": self.owner.owner_id, "severity": severity,
               "message": message, "context": context}
        self.outbox.parent.mkdir(parents=True, exist_ok=True)
        with self.outbox.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        return rec

    def escalation_proposals(self, message: str, evidence_ids: list[str]) -> list[Proposal]:
        """Proposals to reach the owner on external channels. Each still needs a token."""
        out = []
        for ch in self.owner.reachable():
            if ch.kind in ("local_console", "outbox_file"):
                continue
            out.append(Proposal(uid("proposal"), "operator-reachability", f"reach owner via {ch.kind}",
                                f"notify.{ch.kind}", list(evidence_ids), [f"notify.{ch.kind}"], 1, False,
                                budget=1.0, scope={"to": ch.address, "message": message}))
        return out


class PropheticOperatorChannel(OperatorChannel):
    """Gemini Block X names (E4 interpretation) over the E1 mechanism above."""

    def invoke_miracle_override(self, proposal: Proposal, transcendent_rationale: str):
        return self.override(proposal, transcendent_rationale, origin="STEWARD_REVELATION")

    def zhengming(self, term: str, definition: str) -> dict:
        return self.rectify(term, definition)
