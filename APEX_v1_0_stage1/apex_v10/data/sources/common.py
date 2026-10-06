"""Row types shared by all source adapters (plain tuples in table-column order; inserted with executemany)."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..archive import Payload

# funding_events columns
FUNDING_COLUMNS = ("venue", "symbol", "funding_ts", "rate", "interval_s", "interval_source", "rate_semantics",
                   "mark_price", "index_price", "published_ts", "availability_quality", "provenance_id")
# macro_observations columns
MACRO_COLUMNS = ("source", "series_id", "observation_ts", "published_ts", "retrieved_ts", "value", "unit",
                 "vintage_or_release_id", "raw_payload_sha256", "availability_quality", "provenance_id")
RELEASE_COLUMNS = ("source", "release_id", "release_ts", "calendar_source", "availability_quality")
PROVENANCE_COLUMNS = ("provenance_id", "source", "endpoint", "retrieved_ts", "raw_payload_sha256", "raw_path",
                      "third_party", "notes")


def provenance_row(p: Payload, archive_root_rel: str, third_party: bool = False, notes: str = "") -> tuple:
    return (provenance_id(p), p.source, p.url, p.retrieved_ts, p.sha256, f"{archive_root_rel}/{p.source}/{p.sha256}.gz",
            int(third_party), notes)


def provenance_id(p: Payload) -> str:
    return f"{p.source}:{p.sha256[:16]}"


@dataclass
class SourceResult:
    name: str
    funding: list[tuple] = field(default_factory=list)
    macro: list[tuple] = field(default_factory=list)
    releases: list[tuple] = field(default_factory=list)
    provenance: list[tuple] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add_payload(self, p: Payload, archive_root_rel: str, third_party: bool = False, notes: str = "") -> str:
        row = provenance_row(p, archive_root_rel, third_party, notes)
        if row[0] not in {r[0] for r in self.provenance}:
            self.provenance.append(row)
        return row[0]
