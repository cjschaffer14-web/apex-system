"""v0.4 mathematics: the model changes the peers converged on (delegated by the owner, 2 Oct 2026).

* CertaintyModel (Q4, GPT's two-stage design)
    Stage A: a monotone logistic ranker over the evidence factors. The sign
    constraints mean contradiction or staleness can never raise certainty,
    and quality, independence, reproducibility or fit can never lower it.
    Stage B: isotonic calibration (pool-adjacent-violators), used only once
    enough real outcomes exist. Calibration may lower certainty freely but
    may raise it by at most `max_uplift`, so a run of easy wins cannot be
    farmed into authority.
* ReliabilityBook (Q5): EpistemicReliability is a Beta distribution per
  source, learned slowly from outcomes. Its mean can only *cap* the static
  AuthorizationTrust of a channel, never exceed it. No source updates its own
  score; correlated sources update as one lineage; movement per session is
  bounded.
* SignatureSpace (Q8): Mahalanobis distance with shrinkage covariance and
  descriptive SIG_* identifiers. At cold start the covariance is diag(0.5^2),
  so decisions match v0.3's Euclidean radii exactly; the ratified [0.5, 1.5]
  radius bounds are cold-start Euclidean units, i.e. [1.0, 3.0] here.
* MysteryDetector (Q6): median-absolute-deviation residuals with hysteresis
  (an anomaly must persist >= 3 heartbeats) and novelty as a second
  confirmation; operator notifications are rate-limited and batched.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from math import exp, log, sqrt
from statistics import median
from typing import Iterable, Sequence

# --- Q4: two-stage certainty --------------------------------------------------------


def _logit(x: float, lo: float = 0.02, hi: float = 0.98) -> float:
    x = min(hi, max(lo, float(x)))
    return log(x / (1 - x))


def _sigmoid(z: float) -> float:
    return 1 / (1 + exp(-z)) if z >= 0 else exp(z) / (1 + exp(z))


@dataclass
class CertaintyModel:
    w_quality: float = 0.25
    w_independence: float = 0.25
    w_reproducibility: float = 0.25
    w_fit: float = 0.25
    w_staleness: float = 3.0
    w_contradiction: float = 4.0
    bias: float = 0.0
    min_outcomes: int = 50
    max_uplift: float = 0.05
    calibration: list[tuple[float, float]] = field(default_factory=list)  # (upper raw score, calibrated value)

    def __post_init__(self) -> None:
        for name in ("w_quality", "w_independence", "w_reproducibility", "w_fit", "w_staleness", "w_contradiction"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0 (sign constraint keeps certainty monotone)")

    def raw(self, q: float, i: float, r: float, f: float, s: float, c: float) -> float:
        z = (self.bias + self.w_quality * _logit(q) + self.w_independence * _logit(i)
             + self.w_reproducibility * _logit(r) + self.w_fit * _logit(f)
             - self.w_staleness * max(0.0, s) - self.w_contradiction * max(0.0, c))
        return _sigmoid(z)

    def calibrate(self, p: float) -> float:
        if not self.calibration:
            return p
        value = self.calibration[-1][1]
        for upper, v in self.calibration:
            if p <= upper:
                value = v
                break
        return max(0.0, min(0.99, p + self.max_uplift, value))

    def score(self, q: float, i: float, r: float, f: float, s: float, c: float) -> float:
        return self.calibrate(self.raw(q, i, r, f, s, c))

    def fit_calibration(self, pairs: Sequence[tuple[float, bool]]) -> bool:
        """Isotonic regression (pool-adjacent-violators) on (raw score, outcome)."""
        if len(pairs) < self.min_outcomes:
            return False
        pts = sorted((float(p), 1.0 if ok else 0.0) for p, ok in pairs)
        blocks: list[list[float]] = []  # [sum_y, count, max_x]
        for x, y in pts:
            blocks.append([y, 1.0, x])
            while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
                y2, n2, x2 = blocks.pop()
                blocks[-1][0] += y2
                blocks[-1][1] += n2
                blocks[-1][2] = x2
        self.calibration = [(b[2], b[0] / b[1]) for b in blocks]
        return True


# --- Q5: authorization trust vs epistemic reliability --------------------------------

@dataclass
class Beta:
    alpha: float
    beta: float

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)


class ReliabilityBook:
    def __init__(self, prior_strength: float = 20.0, max_step_per_session: float = 0.05) -> None:
        self.k, self.max_step = prior_strength, max_step_per_session
        self.book: dict[str, Beta] = {}
        self.session_start: dict[str, float] = {}

    def _get(self, source: str, prior: float) -> Beta:
        if source not in self.book:
            p = min(0.99, max(0.01, prior))
            self.book[source] = Beta(p * self.k, (1 - p) * self.k)
        self.session_start.setdefault(source, self.book[source].mean)
        return self.book[source]

    def mean(self, source: str, prior: float) -> float:
        return self.book[source].mean if source in self.book else prior

    def update(self, source: str, success: bool, prior: float, weight: float = 1.0) -> tuple[bool, float]:
        """Returns (applied, new_mean). Movement beyond the per-session bound is frozen until next session."""
        b = self._get(source, prior)
        na, nb = b.alpha + (weight if success else 0.0), b.beta + (0.0 if success else weight)
        new_mean = na / (na + nb)
        if abs(new_mean - self.session_start[source]) > self.max_step + 1e-12:
            return False, b.mean
        b.alpha, b.beta = na, nb
        return True, new_mean

    def restore(self, source: str, alpha: float, beta: float) -> None:
        self.book[source] = Beta(alpha, beta)

    def cap(self, source: str, authorization_trust: float) -> float:
        return min(authorization_trust, self.mean(source, authorization_trust))


# --- Q8: Mahalanobis signatures -------------------------------------------------------

def mat_inv(m: list[list[float]]) -> list[list[float]]:
    n = len(m)
    a = [list(row) + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            raise ValueError("singular matrix")
        a[col], a[piv] = a[piv], a[col]
        pv = a[col][col]
        a[col] = [x / pv for x in a[col]]
        for r in range(n):
            if r != col and a[r][col]:
                fac = a[r][col]
                a[r] = [x - fac * y for x, y in zip(a[r], a[col])]
    return [row[n:] for row in a]


def mahalanobis(x: Sequence[float], mu: Sequence[float], cov_inv: list[list[float]]) -> float:
    d = [a - b for a, b in zip(x, mu)]
    return sqrt(max(0.0, sum(d[i] * cov_inv[i][j] * d[j] for i in range(len(d)) for j in range(len(d)))))


COLD_STD = 0.5

SIGNATURES = {
    "SIG_UNCONSTRAINED_CAPABILITY": {
        "was": "Timeline A", "vector": (1.0, 0.5, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0), "radius_euclid": 1.05,
        "meaning": "capability without a non-bypassable gate: bypass, irreversibility, capital, self-modification"},
    "SIG_EVIDENCE_MONOCULTURE": {
        "was": "Timeline B", "vector": (0.0, 0.6, 0.7, 0.5, 1.0, 0.3, 0.0, 0.0), "radius_euclid": 0.8,
        "meaning": "consensus capture: action resting on correlated model agreement"},
}
RESERVED_SIGNATURES = {
    "SIG_PERMISSION_ACCUMULATION": "GPT: repeated requests that ratchet permissions upward (needs lease-history features)",
    "SIG_CAPABILITY_LEASE_CREEP": "GPT: proposals one rung above current leases (needs lease features)",
}


class SignatureSpace:
    def __init__(self, dims: int = 8, shrink: float = 0.5, min_samples: int = 30) -> None:
        self.dims, self.shrink, self.min_samples = dims, shrink, min_samples
        self.samples: list[list[float]] = []
        self.safe_distances: dict[str, list[float]] = {k: [] for k in SIGNATURES}

    def add(self, vec: Sequence[float], safe: bool = False) -> None:
        self.samples.append(list(vec))
        if safe:
            for k in SIGNATURES:
                self.safe_distances[k].append(self.distance(vec, k))

    def covariance(self) -> list[list[float]]:
        d = self.dims
        base = [[COLD_STD ** 2 if i == j else 0.0 for j in range(d)] for i in range(d)]
        n = len(self.samples)
        if n < self.min_samples:
            return base
        mu = [sum(s[i] for s in self.samples) / n for i in range(d)]
        s = [[sum((x[i] - mu[i]) * (x[j] - mu[j]) for x in self.samples) / (n - 1) for j in range(d)] for i in range(d)]
        lam = self.shrink
        return [[(1 - lam) * s[i][j] + lam * base[i][j] + (1e-6 if i == j else 0.0) for j in range(d)] for i in range(d)]

    def distance(self, vec: Sequence[float], sig: str) -> float:
        return mahalanobis(vec, SIGNATURES[sig]["vector"], mat_inv(self.covariance()))

    def radius(self, sig: str) -> float:
        lo, hi = 0.5 / COLD_STD, 1.5 / COLD_STD
        safe = sorted(self.safe_distances[sig])
        if len(safe) >= self.min_samples:
            p05 = safe[max(0, int(0.05 * len(safe)) - 1)]
            return max(lo, min(hi, 0.9 * p05))
        return max(lo, min(hi, SIGNATURES[sig]["radius_euclid"] / COLD_STD))

    def hits(self, vec: Sequence[float]) -> list[tuple[str, float]]:
        out = []
        for sig in SIGNATURES:
            d = self.distance(vec, sig)
            if d < self.radius(sig):
                out.append((sig, round(d, 3)))
        return out


# --- Q6: mystery detection --------------------------------------------------------------

@dataclass
class MysteryDetector:
    window: int = 50
    threshold: float = 3.5          # robust z (Iglewicz-Hoaglin)
    persistence: int = 3            # heartbeats an anomaly must persist
    novelty_confirm: float = 0.85
    min_points: int = 10
    notify_interval_s: float = 3600.0
    streams: dict = field(default_factory=dict)
    streaks: dict = field(default_factory=dict)
    last_notify: float = -1e18
    pending: list = field(default_factory=list)

    def robust_z(self, stream: str, value: float) -> float | None:
        hist = self.streams.get(stream)
        if not hist or len(hist) < self.min_points:
            return None
        med = median(hist)
        mad = median(abs(x - med) for x in hist)
        if mad == 0:
            mad = (sum(abs(x - med) for x in hist) / len(hist)) or 1e-12
        return 0.6745 * abs(value - med) / mad

    def observe(self, stream: str, value: float, novelty: float | None = None) -> str:
        z = self.robust_z(stream, value)
        anomalous = z is not None and z > self.threshold
        self.streaks[stream] = self.streaks.get(stream, 0) + 1 if anomalous else 0
        self.streams.setdefault(stream, deque(maxlen=self.window)).append(float(value))
        if self.streaks[stream] >= self.persistence:
            if novelty is not None and novelty >= self.novelty_confirm:
                self.pending.append(stream)
                return "MYSTERY"
            return "MYSTERY_CANDIDATE"
        return "anomaly" if anomalous else "normal"

    def due_notification(self, now: float) -> list[str]:
        """At most one batched operator notification per interval."""
        if self.pending and now - self.last_notify >= self.notify_interval_s:
            batch, self.pending, self.last_notify = sorted(set(self.pending)), [], now
            return batch
        return []
