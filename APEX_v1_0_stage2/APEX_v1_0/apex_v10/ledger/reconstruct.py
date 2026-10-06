"""Rebuild per-period return series of the frozen v0.6 / v0.8 / v0.9 trials, without changing any definition.

Method: the frozen orchestrators (v06.batch, v08.run_real_single, v09.expert_streams / mixture_returns /
matrix_kelly_pair) are called UNMODIFIED. Their internal helpers (run_vector, one, stats_from_returns, stats) are
wrapped only to record the series that pass through them, then restored. Each recorded series is accepted only if
recomputing its summary statistics with the frozen statistics function reproduces the frozen result file.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

sys.dont_write_bytecode = True

import numpy as np  # noqa: E402

BASELINE_DB_SHA256 = "ac53b123361e5de0f4aa00530cbe1c35286cfd3959224d4e2bf845f634267596"


@dataclass
class Series:
    name: str
    ts: np.ndarray
    ret: np.ndarray
    turn: np.ndarray | None = None
    extra: dict = field(default_factory=dict)


@contextlib.contextmanager
def wrap(module: Any, attr: str, make: Callable[[Callable], Callable]) -> Iterator[None]:
    orig = getattr(module, attr)
    setattr(module, attr, make(orig))
    try:
        yield
    finally:
        setattr(module, attr, orig)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class Frozen:
    """The frozen v0.9 code and a hash-verified scratch copy of the frozen database."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.code = self.root / "baseline_v09" / "code"
        self._tmp = tempfile.TemporaryDirectory(prefix="apex_v10_reconstruct_")
        self.db = Path(self._tmp.name) / "market_2026-10-03.sqlite"
        shutil.copyfile(self.root / "baseline_v09" / "data" / "market_2026-10-03.sqlite", self.db)
        if _sha(self.db) != BASELINE_DB_SHA256:
            raise RuntimeError("scratch database copy does not match the frozen hash")
        if str(self.code) not in sys.path:
            sys.path.insert(0, str(self.code))
        self.v6 = importlib.import_module("trading_backtest_v06")
        self.v7 = importlib.import_module("trading_backtest_v07")
        self.v8 = importlib.import_module("trading_backtest_v08")
        self.v9 = importlib.import_module("trading_backtest_v09")
        self._data: dict[str, dict] = {}

    def close(self) -> None:
        self._tmp.cleanup()

    def data(self, pair: str) -> dict:
        if pair not in self._data:
            self._data[pair] = self.v6.load_sqlite(str(self.db), pair, 1440)
        return self._data[pair]

    def code_sha256(self, *modules: str) -> str:
        parts = [f"{m}:{_sha(self.code / (m + '.py'))}" for m in modules]
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()

    def results(self, name: str) -> Any:
        return json.loads((self.root / "baseline_v09" / "results" / name).read_text())


def _align_ts(ts: np.ndarray, n: int) -> np.ndarray:
    if n == len(ts):
        return ts
    if n == len(ts) - 1:
        return ts[1:]
    raise ValueError(f"cannot align a series of length {n} to {len(ts)} bars")


# ---------------------------------------------------------------------------------------------------------------
def capture_v06(fz: Frozen, pair: str, cost: float = 25.0) -> tuple[dict, list[Series]]:
    v6 = fz.v6
    data = fz.data(pair)
    cur: dict = {"name": None}
    got: list[Series] = []

    def make_one(orig):
        def one(data, name, exposure, cost):
            cur["name"] = name
            try:
                return orig(data, name, exposure, cost)
            finally:
                cur["name"] = None
        return one

    def make_rv(orig):
        def run_vector(data, exposure, cost_bps=85.0):
            out = orig(data, exposure, cost_bps)
            if cur["name"] is not None:
                got.append(Series(cur["name"], _align_ts(data["ts"], len(out[0])), np.asarray(out[0], float),
                                  np.asarray(out[1], float)))
            return out
        return run_vector

    with wrap(v6, "one", make_one), wrap(v6, "run_vector", make_rv):
        res = v6.batch(data, cost)
    res["synthetic"] = False                                  # as trading_backtest_v06.main() sets it
    res["meta"]["pair"], res["meta"]["interval"] = pair, 1440
    names = [s.name for s in got]
    if len(names) != len(set(names)):
        raise RuntimeError("v06 capture recorded a name twice")
    return res, got


def capture_v08(fz: Frozen, pair: str, cost: float = 25.0) -> tuple[dict, list[Series]]:
    v8 = fz.v8
    data = fz.data(pair)
    got: list[np.ndarray] = []

    def make(orig):
        def stats_from_returns(r):
            got.append(np.asarray(r, float).copy())
            return orig(r)
        return stats_from_returns

    with wrap(v8, "stats_from_returns", make):
        res = v8.run_real_single(data, cost)
    if len(got) != len(res["runs"]):
        raise RuntimeError("v08 capture count mismatch")
    return res, [Series(row["name"], _align_ts(data["ts"], len(r)), r) for row, r in zip(res["runs"], got)]


def capture_v09_asset(fz: Frozen, pair: str, cost: float) -> list[Series]:
    v9 = fz.v9
    data = fz.data(pair)
    _, streams = v9.expert_streams(data, cost)
    out = [Series(f"expert:{k}", _align_ts(data["ts"], len(v)), np.asarray(v, float)) for k, v in streams.items()]
    for label, directional in (("long_only_mixture", False), ("directional_mixture", True)):
        m = v9.mixture_returns(data, cost, directional)
        out.append(Series(f"mixture:{label}", _align_ts(data["ts"], len(m["returns"])), np.asarray(m["returns"], float),
                          extra={"state": m["state"]}))
    return out


def capture_v09_kelly(fz: Frozen, cost: float = 25.0) -> tuple[dict, list[Series]]:
    v6, v9 = fz.v6, fz.v9
    btc, eth = fz.data("BTC-USD"), fz.data("ETH-USD")
    got: list[np.ndarray] = []

    def make(orig):
        def stats(net, turn=None, annual=365):
            got.append(np.asarray(net, float).copy())
            return orig(net, turn, annual)
        return stats

    with wrap(v6, "stats", make):
        res = v9.matrix_kelly_pair(btc, eth, cost)
    common = np.array(sorted(set(btc["ts"].tolist()) & set(eth["ts"].tolist())), dtype=np.int64)
    series = []
    for row, r in zip(res["rows"], got):
        series.append(Series(f"matrix_kelly:fraction={row['fraction']:g}", common[1:], r))
    return res, series


def capture_v09_states(fz: Frozen, pair: str) -> np.ndarray:
    state, _ = fz.v9.classify_states(fz.data(pair))
    return state


# ---------------------------------------------------------------------------------------------------------------
def stats_equal(a: dict, b: dict, keys: list[str] | None = None, tol: float = 0.0) -> tuple[bool, float]:
    keys = keys or sorted(set(a) & set(b))
    worst = 0.0
    for k in keys:
        x, y = a.get(k), b.get(k)
        if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool):
            d = abs(float(x) - float(y))
            if not (np.isfinite(d)):
                return False, float("inf")
            worst = max(worst, d)
        elif x != y:
            return False, float("inf")
    return worst <= tol, worst
