from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class DomainPack:
    name: str
    schemas: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    evaluators: list[str] = field(default_factory=list)
    risk_policy: dict = field(default_factory=dict)
    memory_rules: dict = field(default_factory=dict)
    benchmarks: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.name:
            raise ValueError("pack name required")
