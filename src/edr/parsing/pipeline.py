"""Fusion parsing pipeline.

Combines:
  * PP-DocLayout layout detection (or heuristic fallback)
  * MinerU multimodal extraction (or built-in fallback)
  * AST-structured parse (elements + entities)
  * Table-protected semantic chunking

into a single :class:`ParsedDrawing` consumed by the rest of the pipeline.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from edr.core.models import DrawingElement, Entity
from edr.core.state_machine import ParsedDrawing
from edr.core.trace import TraceCollector
from edr.parsing.ast_parser import ASTParser, extract_entities
from edr.parsing.doclayout import DocLayoutDetector
from edr.parsing.mineru_adapter import MinerU
from edr.parsing.semantic_chunk import chunk


class ParsingPipeline:
    def __init__(self, doclayout_weights: str = "", mineru_endpoint: str = ""):
        self.doclayout = DocLayoutDetector(weights=doclayout_weights)
        self.mineru = MinerU(endpoint=mineru_endpoint)
        self.ast = ASTParser()

    def parse(self, drawing_input: Any, trace: Optional[TraceCollector] = None,
              parent: Optional[str] = None) -> ParsedDrawing:
        drawing_id = _resolve_id(drawing_input)

        # Already-structured input (demo / tests / CAD tool output).
        if isinstance(drawing_input, dict) and "elements" in drawing_input:
            elements = drawing_input["elements"]
            raw_text = drawing_input.get("raw_text", "")
            entities = drawing_input.get("entities") or extract_entities(raw_text)
            layout = drawing_input.get("layout", {})
            chunks = chunk(raw_text) if raw_text else []
            return ParsedDrawing(drawing_id=drawing_id, elements=elements,
                                 entities=entities or extract_entities(raw_text),
                                 chunks=chunks, layout=layout, raw_text=raw_text)

        # Resolve source text via MinerU (remote or fallback).
        extracted = self.mineru.extract(drawing_input)
        text = extracted.get("text", "")
        tables = extracted.get("tables", []) or []

        # Layout detection routes text/tables to regions.
        layout = {"regions": [r.__dict__ for r in self.doclayout.detect(text)]}

        elements, entities = self.ast.parse(text, tables)
        chunks = chunk(text)

        return ParsedDrawing(
            drawing_id=drawing_id, elements=elements, entities=entities,
            chunks=chunks, layout=layout, raw_text=text,
        )


def _resolve_id(drawing_input: Any) -> str:
    if isinstance(drawing_input, dict):
        return drawing_input.get("drawing_id", "drawing")
    if isinstance(drawing_input, (str, Path)):
        p = Path(drawing_input)
        if p.exists():
            return p.stem
        return "drawing"
    return "drawing"
