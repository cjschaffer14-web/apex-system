"""The Shell: append-only, hash-chained provenance, verified.

v0.2 EventLedger appends a hash chain but nothing verified it, and its Lamport
clock restarted at 1 on every reload. v0.3 adds both without editing it.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import json
from ..core import EventLedger, sha256


@dataclass
class ChainReport:
    ok: bool
    events: int
    tail_hash: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def verify_chain(path: str | Path) -> ChainReport:
    """Recompute every parent hash and payload hash. Tampering anywhere breaks the chain."""
    p = Path(path)
    if not p.exists():
        return ChainReport(True, 0, "GENESIS")
    prev, last_lt, errors, warnings, n = "GENESIS", 0, [], [], 0
    for i, line in enumerate(x for x in p.read_text(encoding="utf-8").splitlines() if x.strip()):
        n += 1
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"event {i}: not valid JSON")
            prev = "CORRUPT"
            continue
        if row.get("parent_hash") != prev:
            errors.append(f"event {i} ({row.get('event_type')}): parent hash mismatch")
        if sha256(row.get("payload")) != row.get("payload_hash"):
            errors.append(f"event {i} ({row.get('event_type')}): payload hash mismatch")
        lt = int(row.get("logical_time", 0))
        if lt <= last_lt:
            warnings.append(f"event {i}: logical clock restarted ({last_lt} -> {lt}); v0.2 ledger reload behaviour")
        last_lt = lt
        prev = sha256(row)
    return ChainReport(not errors, n, prev, errors, warnings)


def replay(path: str | Path, until_logical: int | None = None, until_ts: float | None = None) -> list[dict]:
    """Events up to a point in history ("what did APEX believe at 3:14 PM yesterday?")."""
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for i, line in enumerate(x for x in p.read_text(encoding="utf-8").splitlines() if x.strip()):
        row = json.loads(line)
        if until_ts is not None and row.get("timestamp", 0) > until_ts:
            break
        if until_logical is not None and i >= until_logical:
            break
        rows.append(row)
    return rows


def project(rows: list[dict]) -> dict:
    """One event stream, many projections (ChatGPT Upgrade 4): audit, capability, timeline, beliefs, experiments."""
    audit: dict[str, int] = {}
    caps = {"minted": 0, "outcomes_ok": 0, "outcomes_failed": 0, "revoked": 0}
    decisions = {"approved": 0, "denied": 0, "deferred": 0}
    beliefs: dict[str, dict] = {}
    experiments = {"evaluated": 0, "promoted": 0, "rejected": 0, "archived": 0, "awaiting_capability": 0}
    axioms, timeline = [], []
    for r in rows:
        t, pl = r.get("event_type", "?"), r.get("payload", {}) or {}
        audit[t] = audit.get(t, 0) + 1
        timeline.append((r.get("logical_time"), t, r.get("plane")))
        if t == "Decision":
            decisions[pl.get("result", "denied")] = decisions.get(pl.get("result", "denied"), 0) + 1
        elif t == "TokensMinted":
            caps["minted"] += len(pl.get("tokens", []))
        elif t == "OutcomeReported":
            caps["outcomes_ok" if pl.get("success") else "outcomes_failed"] += 1
        elif t == "OperatorHalt":
            caps["revoked"] += int(pl.get("revoked_tokens", 0))
        elif t == "Belief":
            beliefs[pl["id"]] = pl
        elif t == "AxiomRatified":
            axioms.append(pl.get("id"))
        elif t == "Experiment":
            experiments["evaluated"] += 1
            key = {"champion": "promoted", "rejected": "rejected", "awaiting-capability": "awaiting_capability"}.get(
                pl.get("status"), "archived")
            experiments[key] += 1
    return {"audit": audit, "decisions": decisions, "capabilities": caps, "beliefs": beliefs,
            "experiments": experiments, "axioms": axioms, "timeline": timeline}


def file_manifest(root: str | Path, exclude: tuple[str, ...] = ("__pycache__", ".DS_Store", "state/")) -> dict[str, str]:
    """sha256 of every file under root; used for add-only checks and signed migrations."""
    import hashlib
    root = Path(root)
    out = {}
    for f in sorted(root.rglob("*")):
        rel = f.relative_to(root).as_posix()
        if f.is_file() and not any(x in rel for x in exclude):
            out[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


class ContinuityLedger(EventLedger):
    """EventLedger whose Lamport clock resumes from the stored history."""

    def __init__(self, path: str | Path = "events.jsonl") -> None:
        super().__init__(path)
        rows = self.read()
        if rows:
            self.clock.value = max(int(r.get("logical_time", 0)) for r in rows)

    def verify(self) -> ChainReport:
        return verify_chain(self.path)

    def tail(self, n: int = 10) -> list[dict]:
        return self.read()[-n:]
