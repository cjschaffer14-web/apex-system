"""APEX v1.0 Stage 1A interface extensions (add-only).

`apex_v10/interfaces.py` stays byte-identical to the accepted Stage 1 snapshot (its hash is part of the Stage 1
database's schema_version row), so everything Stage 1A adds lives here and extends, never edits, those contracts.

Stage 1 review amendments implemented here:
  1. Timing and value vintage are two separate properties of every stored value.
       availability_time_quality  WHEN the value could first have been known   (interfaces.AvailabilityQuality)
       value_vintage_quality      WHETHER the stored number is the number that was known then  (ValueVintageQuality)
     A value is evidence-grade only if its timing is not approximate AND its vintage is in EVIDENCE_VINTAGES.
     Exact release timing does not make a latest-vintage number evidence-grade.
  2. TrialRecord1A adds `selection_family_id`, `objective_metric` and `comparable_set_id`, plus the outcome of the
     Stage 1A forensic reproduction. The global conservative trial count is unchanged; DSR inputs are prepared for
     both the global count and the trial's selection family.
  3. Only investable, aligned return series in a named comparable set may become CSCV/PBO columns. Event
     statistics (geometry cells), conditional cells, state-forward statistics and hypothesis tests stay in the
     global ledger with `comparable_set_id = None`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from .interfaces import (AvailabilityQuality, Feature, Observation, ReturnsStatus, TrialKind, TrialRecord, _freeze,
                         _ts)

INTERFACE_VERSION_1A = "1.0.1-stage1a"


class ValueVintageQuality(str, Enum):
    """Is the stored number the number that was available at the value's availability time?"""
    FIRST_RELEASE = "first_release"                    # proven: read from the archived first publication
    UNREVISED_SINCE_RELEASE = "unrevised_since_release"  # the source's own last-modified stamp is on the release day
    MARKET_RECORD = "market_record"                    # exchange/index/market fixing; not revised by source practice
    LATEST_VINTAGE = "latest_vintage"                  # dataset shows the latest revision; first print not proven
    EDITED_AFTER_RELEASE = "edited_after_release"      # the source says the record changed after its release day
    UNVERIFIED = "unverified"                          # no evidence either way


EVIDENCE_VINTAGES = frozenset({ValueVintageQuality.FIRST_RELEASE, ValueVintageQuality.UNREVISED_SINCE_RELEASE,
                               ValueVintageQuality.MARKET_RECORD})
EVIDENCE_TIMING = frozenset({AvailabilityQuality.EXACT_RELEASE, AvailabilityQuality.SOURCE_TIMESTAMP,
                             AvailabilityQuality.CONSERVATIVE_LAG})


class DataGrade(str, Enum):
    EVIDENCE = "evidence"          # both timing and vintage qualify; the default for any trial that can be selected
    EXPLORATORY = "exploratory"    # Stage 1 semantics (timing only); never enough for a candidate verdict


def is_evidence_grade(time_quality: AvailabilityQuality | str, vintage_quality: ValueVintageQuality | str) -> bool:
    return AvailabilityQuality(time_quality) in EVIDENCE_TIMING and ValueVintageQuality(vintage_quality) in EVIDENCE_VINTAGES


@dataclass(frozen=True, kw_only=True)
class Observation1A(Observation):
    """An Observation whose value vintage is stated separately from its availability time."""
    value_vintage_quality: ValueVintageQuality

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.value_vintage_quality, ValueVintageQuality):
            raise ValueError("value_vintage_quality is mandatory and must be a ValueVintageQuality")

    @property
    def availability_time_quality(self) -> AvailabilityQuality:
        return self.availability_quality

    @property
    def evidence_grade(self) -> bool:
        return is_evidence_grade(self.availability_quality, self.value_vintage_quality)


@dataclass(frozen=True, kw_only=True)
class Feature1A(Feature):
    value_vintage_quality: ValueVintageQuality

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.value_vintage_quality, ValueVintageQuality):
            raise ValueError("value_vintage_quality is mandatory and must be a ValueVintageQuality")

    @property
    def evidence_grade(self) -> bool:
        return is_evidence_grade(self.availability_quality, self.value_vintage_quality)


# ---------------------------------------------------------------------------------------------------------------
# trial ledger extension
# ---------------------------------------------------------------------------------------------------------------
REPRODUCTION_STATUSES = (
    "stage1_reconciled",           # frozen v0.6-v0.9 trial; series stored/derived and reconciled in Stage 1
    "reproduced_series",           # Stage 1A forensic reproduction: return path recovered, summary reconciles
    "reproduced_statistic_only",   # the archived statistic reproduces, but the definition has no return path
    "mismatch",                    # reran with the frozen definition; the archived metric did not reconcile
    "not_reproducible",            # code or inputs of the original run are not available
)
RETURN_FREQUENCIES_FOR_CSCV = ("daily", "weekly", "hourly")


@dataclass(frozen=True, kw_only=True)
class TrialRecord1A(TrialRecord):
    """A Stage 1 TrialRecord plus selection metadata. `identity_sha256()` is inherited unchanged, so every Stage 1A
    record maps to exactly one Stage 1 record."""
    selection_family_id: str
    objective_metric: str
    comparable_set_id: Optional[str] = None       # None: not a CSCV strategy column (statistic, event, test, ...)
    investable: bool = False                      # a tradable policy's return path (not an event statistic)
    reproduction: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.selection_family_id or not self.objective_metric:
            raise ValueError("selection_family_id and objective_metric are mandatory")
        if self.comparable_set_id is not None:
            if not self.investable:
                raise ValueError("only an investable return path can be a CSCV column")
            if self.kind == TrialKind.HYPOTHESIS_TEST:
                raise ValueError("a hypothesis test cannot be a CSCV strategy column")
            if self.returns_status != ReturnsStatus.STORED or self.returns_frequency not in RETURN_FREQUENCIES_FOR_CSCV:
                raise ValueError("a CSCV column needs a stored, per-period (daily/weekly/hourly) return series")
        st = (self.reproduction or {}).get("status")
        if st is not None and st not in REPRODUCTION_STATUSES:
            raise ValueError(f"unknown reproduction status {st!r}")
        if st == "reproduced_series" and self.returns_status != ReturnsStatus.STORED:
            raise ValueError("a reproduced series must be stored")
        object.__setattr__(self, "reproduction", _freeze(self.reproduction))


@dataclass(frozen=True)
class SelectionFamily:
    """The set of alternatives evaluated together in one research decision, under one objective."""
    family_id: str
    objective_metric: str
    description: str
    members_in_ledger: int                 # ledger records carrying this family id
    alternatives_evaluated: int            # >= members_in_ledger when one record summarises several evaluations
    sharpe_objective: bool                 # DSR applies only to Sharpe-type objectives
    note: str = ""

    def __post_init__(self) -> None:
        if self.members_in_ledger < 1 or self.alternatives_evaluated < self.members_in_ledger:
            raise ValueError("alternatives_evaluated must be >= members_in_ledger >= 1")

    @property
    def n_family(self) -> int:
        """Conservative family size for DSR: every alternative evaluated, never fewer than the ledger shows."""
        return self.alternatives_evaluated


@dataclass(frozen=True)
class ComparableSet:
    """Aligned, competing, investable return series that may form one CSCV/PBO matrix."""
    set_id: str
    selection_family_id: str
    asset: str
    frequency: str
    cost_model_id: str
    trial_ids: tuple[str, ...]
    first_ts: int
    last_ts: int
    rows: int
    distinct_columns: int                  # after collapsing identical return paths (equivalence classes)

    def __post_init__(self) -> None:
        _ts("first_ts", self.first_ts)
        _ts("last_ts", self.last_ts)
        if self.frequency not in RETURN_FREQUENCIES_FOR_CSCV:
            raise ValueError("CSCV needs per-period returns")
        if len(self.trial_ids) < 2 or self.distinct_columns < 1 or self.rows < 1:
            raise ValueError("a comparable set needs at least two trials and one aligned row")
