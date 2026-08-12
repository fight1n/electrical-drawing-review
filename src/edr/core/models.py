"""Domain models shared across all modules.

These are plain dataclasses (cheap to construct, easy to serialize) plus a
couple of small helpers. Keeping them dependency-free makes the whole pipeline
easy to test and to stream over the wire.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    CRITICAL = "critical"   # 严重 — blocks approval
    MAJOR = "major"         # 主要 — should fix
    MINOR = "minor"         # 轻微 — advisory


class RuleCategory(str, Enum):
    GEOMETRY_SIZE = "geometry_size"
    SYMBOL_ANNOTATION = "symbol_annotation"
    PARAMETER_THRESHOLD = "parameter_threshold"
    WIRING_TOPOLOGY = "wiring_topology"


@dataclass
class BBox:
    x: float
    y: float
    w: float
    h: float

    @property
    def area(self) -> float:
        return self.w * self.h


@dataclass
class DrawingElement:
    """A primitive extracted from the drawing (line, text, symbol, net, ...)."""
    id: str
    type: str                      # line | text | symbol | net | dimension | ...
    layer: str = "0"
    bbox: BBox | None = None
    params: dict[str, Any] = field(default_factory=dict)
    text: str | None = None
    symbol: str | None = None      # symbol id / standard reference
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Entity:
    """A recognized standard reference or rated parameter on the drawing."""
    kind: str                      # standard_code | rated_current | voltage | ...
    value: str
    element_id: str | None = None
    bbox: BBox | None = None


@dataclass
class Annotation:
    """A label/annotation attached to an element (e.g. device tag)."""
    element_id: str
    label: str
    text: str


@dataclass
class RuleMatch:
    """A rule selected as relevant for a given drawing."""
    rule_id: str
    category: RuleCategory
    clause_ref: str                # e.g. "GB 50054-2011 第4.3.2条"
    description: str
    score: float = 0.0
    source: str = "index"          # index | rerank


@dataclass
class Violation:
    rule_id: str
    category: RuleCategory
    clause_ref: str
    severity: Severity
    location: str                  # human-readable location / element id
    bbox: BBox | None = None
    description: str = ""
    suggestion: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReviewReport:
    drawing_id: str
    generated_at: str
    violations: list[Violation] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    rule_matches: list[RuleMatch] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.CRITICAL)

    @property
    def major_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.MAJOR)

    @property
    def minor_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.MINOR)

    def to_dict(self) -> dict[str, Any]:
        return {
            "drawing_id": self.drawing_id,
            "generated_at": self.generated_at,
            "stats": self.stats,
            "rule_matches": [r.__dict__ for r in self.rule_matches],
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "category": v.category.value,
                    "clause_ref": v.clause_ref,
                    "severity": v.severity.value,
                    "location": v.location,
                    "bbox": v.bbox.__dict__ if v.bbox else None,
                    "description": v.description,
                    "suggestion": v.suggestion,
                }
                for v in self.violations
            ],
        }
