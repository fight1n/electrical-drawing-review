"""Rule category metadata.

Mirrors ``config.default.yaml -> rules.categories``. Used by the context builder
to apply *differential* trimming per category (each category needs a different
slice of the drawing data and a different token budget).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from edr.core.models import RuleCategory

CATEGORY_META: dict[RuleCategory, dict[str, Any]] = {
    RuleCategory.GEOMETRY_SIZE: {
        "description": "几何尺寸与间距",
        "context_budget": 1200,
        "requires": ["bbox", "dims"],
    },
    RuleCategory.SYMBOL_ANNOTATION: {
        "description": "符号与标注",
        "context_budget": 1000,
        "requires": ["symbols", "annotations"],
    },
    RuleCategory.PARAMETER_THRESHOLD: {
        "description": "参数阈值与选型",
        "context_budget": 1400,
        "requires": ["params", "ratings"],
    },
    RuleCategory.WIRING_TOPOLOGY: {
        "description": "拓扑与接线",
        "context_budget": 1600,
        "requires": ["nets", "connections"],
    },
}


def category_budget(cat: RuleCategory, default: int = 1200) -> int:
    return CATEGORY_META.get(cat, {}).get("context_budget", default)


def category_requires(cat: RuleCategory) -> list[str]:
    return CATEGORY_META.get(cat, {}).get("requires", [])
