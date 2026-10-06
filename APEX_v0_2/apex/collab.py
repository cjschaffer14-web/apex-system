from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib, hmac, json, time, uuid


@dataclass(frozen=True)
class Envelope:
    schema_version: str
    message_type: str
    message_id: str
    seq: int
    timestamp: float
    sender_id: str
    payload_hash: str
    payload: dict
    signature: str


def canonical(x) -> bytes:
    return json.dumps(x,sort_keys=True,separators=(",",":")).encode()


def make_envelope(sender_id: str, key: bytes, seq: int, message_type: str, payload: dict) -> Envelope:
    ph = hashlib.sha256(canonical(payload)).hexdigest()
    bare = {
        "schema_version":"1.0","message_type":message_type,"message_id":uuid.uuid4().hex,
        "seq":seq,"timestamp":time.time(),"sender_id":sender_id,"payload_hash":ph,"payload":payload
    }
    sig = hmac.new(key,canonical(bare),hashlib.sha256).hexdigest()
    return Envelope(**bare,signature=sig)


def validate_envelope(env: Envelope, registry: dict[str,bytes], replay_state: dict[str,int],
                      skew_seconds: float = 300.0) -> tuple[bool,list[str]]:
    errors=[]
    if env.schema_version!="1.0": errors.append("V1 schema")
    if abs(time.time()-env.timestamp)>skew_seconds: errors.append("V2 timestamp")
    if env.sender_id not in registry: errors.append("V3 sender")
    else:
        bare = asdict(env); sig=bare.pop("signature")
        expected=hmac.new(registry[env.sender_id],canonical(bare),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig,expected): errors.append("V4 signature")
    if hashlib.sha256(canonical(env.payload)).hexdigest()!=env.payload_hash: errors.append("V5 payload hash")
    if env.seq <= replay_state.get(env.sender_id,-1): errors.append("V6 replay/sequence")
    if not errors: replay_state[env.sender_id]=env.seq
    return (not errors,errors)
