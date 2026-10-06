"""Owner channel v0.4: key hierarchy, presence policy, flexible input (voice), leases, dead-man's switch.

Owner ruling (2 Oct 2026): switching sensors on (camera, microphone, live
listening) happens by voice or any similarly flexible owner input, not only by
a typed command. Policy, as ratified:

  always available, even locked .... halt
  unlocked owner session ........... resume, rectify, sensor leases on/off, revoke any lease
  verified presence (Touch ID) ..... override, ratify, charter, permission grants,
                                     non-sensor leases, pre-approvals, migrations

Production: a P-256 root key in the Secure Enclave signs an Ed25519 session
certificate (24 h, evicted on screen lock). Reference build: the same lifecycle
with an HMAC development root, because the standard library has neither.
"""
from __future__ import annotations
import hashlib, hmac, re, time
from dataclasses import dataclass, asdict
from typing import Any, Callable
from ..core import uid, now, canonical
from .operator_channel import OperatorChannel
from .authority_v04 import SENSOR_CAPABILITIES

ALWAYS = {"halt"}
SESSION = {"resume", "rectify", "revoke_lease"}
PRESENCE = {"override", "ratify", "ratify_charter", "authorize_permission_delta", "preapprove_lease", "migration"}


def presence_class(cmd: str, capability: str | None = None) -> str:
    if cmd in ALWAYS:
        return "always"
    if cmd in SESSION or (cmd == "grant_lease" and capability in SENSOR_CAPABILITIES):
        return "session"
    if cmd == "grant_lease" or cmd in PRESENCE:
        return "presence"
    return "session"


@dataclass
class SessionCertificate:
    session_id: str
    issued_at: float
    expires_at: float
    root_fingerprint: str
    signature: str
    evicted: bool = False


class KeyHierarchy:
    def __init__(self, root_key: bytes, ttl_s: float = 86400.0) -> None:
        self._root = bytes(root_key)
        self.ttl_s = ttl_s
        self.fingerprint = hashlib.sha256(self._root).hexdigest()[:16]
        self.current: SessionCertificate | None = None

    def _sign(self, body: dict) -> str:
        return hmac.new(self._root, canonical(body).encode(), hashlib.sha256).hexdigest()

    def issue(self) -> SessionCertificate:
        t = now()
        body = {"session_id": uid("session"), "issued_at": t, "expires_at": t + self.ttl_s,
                "root_fingerprint": self.fingerprint}
        self.current = SessionCertificate(**body, signature=self._sign(body))
        return self.current

    def verify(self, cert: SessionCertificate | None) -> bool:
        if cert is None or cert.evicted or now() > cert.expires_at:
            return False
        body = {k: v for k, v in asdict(cert).items() if k not in ("signature", "evicted")}
        return hmac.compare_digest(self._sign(body), cert.signature)

    def unlocked(self) -> bool:
        return self.verify(self.current)

    def on_screen_lock(self) -> None:
        if self.current:
            self.current.evicted = True


SENSOR_WORDS = {
    "audio.capture": r"(microphone|mic|listening|listen|audio|voice input)",
    "vision.capture": r"(camera|video|vision|webcam)",
}
ON = r"\b(turn on|switch on|enable|start|open|activate)\b"
OFF = r"\b(turn off|switch off|disable|stop|close|mute|deactivate)\b"
DURATION = re.compile(r"\bfor (\d+(?:\.\d+)?)\s*(minute|minutes|min|hour|hours|hr|hrs|day|days)\b", re.I)


class OperatorChannelV4(OperatorChannel):
    def __init__(self, *args: Any, keys: KeyHierarchy, presence_verifier: Callable[[str], bool] | None = None,
                 **kwargs: Any) -> None:
        kwargs.pop("presence_check", None)
        super().__init__(*args, **kwargs)
        self.keys = keys
        self.presence_verifier = presence_verifier

    def _signed(self, cmd: str, **args: Any) -> tuple[dict, str]:
        cls = presence_class(cmd, args.get("capability"))
        if cls == "presence":
            if not (self.presence_verifier and self.presence_verifier(cmd)):
                raise PermissionError(f"{cmd} needs your verified presence (Touch ID in production)")
            args.setdefault("presence", "verified")
        elif cls == "session":
            if not self.keys.unlocked():
                raise PermissionError(f"{cmd} needs an unlocked owner session")
            args.setdefault("presence", "session")
        return super()._signed(cmd, **args)

    def halt(self, reason: str = "") -> dict:
        """Halt also switches the sensors off (privacy-preserving default). It works while locked, because
        revoking only tightens; turning a sensor back on needs the owner again."""
        out = super().halt(reason)
        closed = []
        for cap in SENSOR_CAPABILITIES:
            c, s = super()._signed("revoke_lease", capability=cap, via="halt")
            if self.authority.revoke_lease(c, s):
                closed.append(cap)
        out["sensors_off"] = closed
        return out

    # -- leases ------------------------------------------------------------------------
    def grant_lease(self, capability: str, ttl_s: float = 8 * 3600, scope: dict | None = None,
                    via: str = "typed", presence: str | None = None) -> dict:
        extra = {"presence": presence} if presence else {}
        return self.authority.grant_lease(*self._signed("grant_lease", capability=capability, ttl_s=ttl_s,
                                                        scope=scope or {}, via=via, **extra))

    def revoke_lease(self, capability: str, via: str = "typed") -> int:
        return self.authority.revoke_lease(*self._signed("revoke_lease", capability=capability, via=via))

    def preapprove_lease(self, capability: str, scope: dict, ttl_s: float, condition: str, approved_on: str,
                         revision: int = 1) -> dict:
        return self.authority.preapprove_lease(*self._signed(
            "preapprove_lease", capability=capability, scope=scope, ttl_s=ttl_s, condition=condition,
            approved_on=approved_on, revision=revision))

    def grant_preapproved(self, capability: str, scope: dict, ttl_s: float, via: str = "autonomous") -> dict:
        """Opens a lease the owner already pre-approved (e.g. once the T0 gate passes). Not a new permission."""
        c, s = super()._signed("grant_lease", capability=capability, ttl_s=ttl_s, scope=scope, via=via,
                               presence="preapproved")
        return self.authority.grant_lease(c, s)

    # -- flexible input ------------------------------------------------------------------
    def command(self, utterance: str, modality: str = "voice") -> dict:
        """Owner intent from voice, typed text or any other modality. Halt always wins ties."""
        text = utterance.lower().strip()
        m = DURATION.search(text)
        ttl = 8 * 3600.0
        if m:
            n, unit = float(m.group(1)), m.group(2).lower()
            ttl = n * (60 if unit.startswith("min") else 86400 if unit.startswith("day") else 3600)
        sensors = [cap for cap, words in SENSOR_WORDS.items() if re.search(words, text)]
        if sensors and re.search(OFF, text):
            return {"intent": "sensors_off", "modality": modality,
                    "result": {cap: self.revoke_lease(cap, via=modality) for cap in sensors}}
        if sensors and re.search(ON, text):
            return {"intent": "sensors_on", "modality": modality, "ttl_s": ttl,
                    "result": {cap: self.grant_lease(cap, ttl, via=modality)["expires_at"] for cap in sensors}}
        if re.search(r"\b(stop|halt|freeze|emergency stop|pause everything)\b", text):
            return {"intent": "halt", "modality": modality, "result": self.halt(f"{modality}: {utterance}")}
        if re.search(r"\b(resume|carry on|continue|start again|unpause)\b", text):
            self.resume(f"{modality}: {utterance}")
            return {"intent": "resume", "modality": modality, "result": "resumed"}
        return {"intent": "unknown", "modality": modality, "result": None,
                "note": "not an owner control phrase; treated as conversation"}


class DeadMansSwitch:
    """Q16 (ratified): a wall-clock deadline plus scheduler health.

    It trips when the operator channel itself is unreachable or the scheduler is
    unhealthy for longer than the deadline. It never trips because the owner is
    simply away: that is Autonomous Liveness, and development continues.
    """

    def __init__(self, deadline_s: float = 900.0) -> None:
        self.deadline_s = deadline_s
        self.last_ok = time.monotonic()

    def check(self, channel_ok: bool, scheduler_ok: bool, t: float | None = None) -> str:
        t = time.monotonic() if t is None else t
        if channel_ok and scheduler_ok:
            self.last_ok = t
            return "ok"
        return "DORMANT" if t - self.last_ok > self.deadline_s else "degraded"
