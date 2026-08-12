"""AST-structured parser.

Turns extracted text into typed :class:`DrawingElement` objects and recognizes
:class:`Entity` instances (standard references + rated parameters). This is the
"AST fusion" stage: a lightweight grammar over drawing text that complements the
vision-based layout/extraction stages and gives the downstream rule engine a
clean, queryable structure.
"""
from __future__ import annotations

import re
from typing import Any

from edr.core.models import BBox, DrawingElement, Entity

# Standard references: GB / IEC / DL / JGJ + number, optional year.
_STD_RE = re.compile(r"(GB|IEC|DL|JGJ|GB/T)\s*[\s\-]?\d{3,6}(?:[.\-]\d{1,4})?", re.IGNORECASE)
# Rated current, e.g. "额定电流 63A", "In=100A", "100 A".
_CURRENT_RE = re.compile(r"(?:额定电流|rated current|in)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*A", re.IGNORECASE)
# Voltage, e.g. "220V", "0.4kV", "额定电 压 380 V".
_VOLTAGE_RE = re.compile(r"(?:额定电压|rated voltage|u)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(kV|V)", re.IGNORECASE)
# Cable cross-section, e.g. "截面积 16mm2", "4×25".
_AREA_RE = re.compile(r"(?:截面积|cross[- ]?section|截面)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:mm2|mm²)", re.IGNORECASE)
# Clearance / distance, e.g. "间距 100mm", "净距 < 50".
_CLEAR_RE = re.compile(r"(?:间距|净距|clearance|distance)\s*[:=]?\s*(?:<|小于)?\s*(\d+(?:\.\d+)?)\s*mm", re.IGNORECASE)


def extract_entities(text: str) -> list[Entity]:
    entities: list[Entity] = []
    for m in _STD_RE.finditer(text):
        entities.append(Entity(kind="standard_code", value=m.group(0).replace(" ", ""),
                               bbox=None))
    for m in _CURRENT_RE.finditer(text):
        entities.append(Entity(kind="rated_current_a", value=m.group(1)))
    for m in _VOLTAGE_RE.finditer(text):
        entities.append(Entity(kind="voltage", value=f"{m.group(1)}{m.group(2)}"))
    for m in _AREA_RE.finditer(text):
        entities.append(Entity(kind="cross_section_mm2", value=m.group(1)))
    for m in _CLEAR_RE.finditer(text):
        entities.append(Entity(kind="clearance_mm", value=m.group(1)))
    return entities


def parse_elements(text: str, tables: list[list[str]] | None = None) -> list[DrawingElement]:
    """Build primitive elements from text lines + tables."""
    elements: list[DrawingElement] = []
    tables = tables or []
    line_no = 0

    for i, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        line_no += 1
        # Symbol/device tagging: lines like "M1 电动机" or "[QF1] 断路器".
        sym = None
        m = re.search(r"\[([A-Z]{1,3}\d+)\]", line)
        if m:
            sym = m.group(1)
        etype = "symbol" if sym else ("text" if len(line) > 6 else "annotation")
        entities_here = extract_entities(line)
        params = {e.kind: e.value for e in entities_here}
        elements.append(DrawingElement(
            id=f"E{line_no}", type=etype, layer="0",
            bbox=BBox(x=0.1, y=0.9 - i * 0.02, w=0.2, h=0.02),
            text=line, symbol=sym, params=params,
        ))

    for ti, table in enumerate(tables):
        if len(table) < 2:
            continue
        elements.append(DrawingElement(
            id=f"T{ti}", type="dimension", layer="table",
            params={"header": table[0], "rows": table[1:]},
        ))
    return elements


class ASTParser:
    def parse(self, text: str, tables: list[list[str]] | None = None) -> tuple[list, list]:
        elements = parse_elements(text, tables)
        entities = extract_entities(text)
        return elements, entities
