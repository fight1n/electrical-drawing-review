"""Electrical Drawing Review (EDR) — automated schematic audit system.

A modular, deployable pipeline:

    PARSE -> RULE_SELECT -> CONTEXT_BUILD -> PARALLEL_REVIEW -> REPORT

Public entry points live here so callers can `from edr import ReviewPipeline`.
"""

__version__ = "0.1.0"

from edr.core.config import Config, load_config
from edr.core.models import (
    Annotation,
    DrawingElement,
    Entity,
    ReviewReport,
    RuleMatch,
    Violation,
)
from edr.core.state_machine import PipelineState, ReviewPipeline

__all__ = [
    "Config",
    "load_config",
    "DrawingElement",
    "Entity",
    "Annotation",
    "RuleMatch",
    "Violation",
    "ReviewReport",
    "PipelineState",
    "ReviewPipeline",
    "__version__",
]
