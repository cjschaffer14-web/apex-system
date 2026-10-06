"""Read the trial ledger back into validated TrialRecord objects (no numpy, no frozen code needed)."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Iterator

from ..interfaces import ReturnsStatus, TrialKind, TrialRecord, TrialStatus, canonical_json


def record_from_dict(d: dict) -> TrialRecord:
    """Inverse of canonical_json(record). Every invariant in TrialRecord.__post_init__ is re-checked."""
    d = dict(d)
    d["kind"] = TrialKind(d["kind"])
    d["returns_status"] = ReturnsStatus(d["returns_status"])
    d["status"] = TrialStatus(d["status"])
    d["artifact_refs"] = tuple(d.get("artifact_refs") or ())
    return TrialRecord(**d)


def iter_ledger(path: Path) -> Iterator[tuple[str, TrialRecord]]:
    for line in Path(path).read_text().splitlines():
        if line.strip():
            yield line, record_from_dict(json.loads(line))


def load_ledger(path: Path) -> list[TrialRecord]:
    return [r for _, r in iter_ledger(path)]


def roundtrip_ok(line: str, rec: TrialRecord) -> bool:
    return canonical_json(rec) == line


def read_returns(root: Path, rec: TrialRecord) -> tuple[list[int], list[float]]:
    """The stored series of a trial; raises if the file hash does not match the ledger.

    Daily series: (epoch ts, return). Event series (`file#horizon=..&scale=..&ref=..&ratio=..`): the cell's events as
    (bar index t, signed_return), the same pairs its return_equivalence_id was computed from."""
    path, _, frag = rec.returns_ref.partition("#")
    raw = (Path(root) / path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != rec.returns_sha256:
        raise ValueError(f"{rec.trial_id}: stored return file hash mismatch")
    rows = gzip.decompress(raw).decode().splitlines()
    ts, ret = [], []
    if not frag:
        if rows[0] != "ts,ret":
            raise ValueError(f"{rec.trial_id}: not a return series")
        for x in rows[1:]:
            a, b = x.split(",")
            ts.append(int(a))
            ret.append(float(b))
        return ts, ret
    want = dict(kv.split("=", 1) for kv in frag.split("&"))
    head = rows[0].split(",")
    for x in rows[1:]:
        r = dict(zip(head, x.split(",")))
        if (r["horizon"] == want["horizon"] and r["scale"] == want["scale"] and r["ref"] == want["ref"]
                and float(r["ratio"]) == float(want["ratio"])):
            ts.append(int(r["t"]))
            ret.append(float(r["signed_return"]))
    return ts, ret


def equivalence_id(ts, ret) -> str:
    """Same definition as build_ledger.Store.equivalence_id."""
    return hashlib.sha256("".join(f"{int(t)}:{float(r)!r}\n" for t, r in zip(ts, ret)).encode()).hexdigest()
