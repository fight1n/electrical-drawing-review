"""Atomic CAD tools.

Wraps FreeCAD (optional) behind three atomic operations the LLM can call during
the Tool-Use review loop:
  * parse_primitives  — list line/circle/text primitives of the document
  * annotate_entities — return the annotation/label attached to an element
  * extract_params    — return the rated parameters of an element (current, area...)

A uniform :func:`execute` dispatcher + :data:`CAD_TOOL_SPECS` make these directly
usable as Claude/OpenAI tool definitions.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from edr.core.models import DrawingElement

# Tool definitions (Claude/OpenAI compatible) exposed to the LLM.
CAD_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "parse_primitives",
        "description": "列出图纸中的基础图元(线/圆/文本/符号)及其数量统计。",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "annotate_entities",
        "description": "返回指定图元的标注/设备位号文本。",
        "input_schema": {
            "type": "object",
            "properties": {"element_id": {"type": "string", "description": "图元ID"}},
            "required": ["element_id"],
        },
    },
    {
        "name": "extract_params",
        "description": "返回指定图元的额定参数(电流/电压/截面积等)。",
        "input_schema": {
            "type": "object",
            "properties": {"element_id": {"type": "string", "description": "图元ID"}},
            "required": ["element_id"],
        },
    },
]


class FreeCADTools:
    def __init__(self, elements: Optional[list[DrawingElement]] = None):
        self.elements: list[DrawingElement] = elements or []
        self._freecad = self._try_import_freecad()

    # -- optional FreeCAD loader ---------------------------------------- #
    @staticmethod
    def _try_import_freecad():
        try:
            import FreeCAD  # type: ignore  # noqa: F401
            return FreeCAD
        except Exception:
            return None

    @property
    def freecad_available(self) -> bool:
        return self._freecad is not None

    def load_via_freecad(self, path: str) -> list[DrawingElement]:
        """Load a real CAD document through FreeCAD and convert to elements.

        Falls back to the in-memory element list when FreeCAD is unavailable so
        callers never have to special-case the absence.
        """
        if self._freecad is None:
            return self.elements
        doc = self._freecad.open(path)
        out: list[DrawingElement] = []
        for i, obj in enumerate(doc.Objects):
            bbox = obj.Shape.BoundBox if hasattr(obj, "Shape") else None
            out.append(DrawingElement(
                id=f"FC{i}", type=obj.TypeId, layer="0",
                bbox=None, text=getattr(obj, "Label", None),
                raw={"type_id": obj.TypeId},
            ))
        self.elements = out
        return out

    # -- atomic tools ---------------------------------------------------- #
    def parse_primitives(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for e in self.elements:
            by_type[e.type] = by_type.get(e.type, 0) + 1
        return {"count": len(self.elements), "by_type": by_type,
                "freecad": self.freecad_available}

    def annotate_entities(self, element_id: str) -> dict[str, Any]:
        for e in self.elements:
            if e.id == element_id:
                return {"element_id": element_id, "symbol": e.symbol,
                        "text": e.text, "label": e.text or e.symbol}
        return {"element_id": element_id, "error": "not found"}

    def extract_params(self, element_id: str) -> dict[str, Any]:
        for e in self.elements:
            if e.id == element_id:
                return {"element_id": element_id, "params": e.params or {}}
        return {"element_id": element_id, "error": "not found"}

    # -- dispatch -------------------------------------------------------- #
    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "parse_primitives":
            return json.dumps(self.parse_primitives(), ensure_ascii=False)
        if name == "annotate_entities":
            return json.dumps(self.annotate_entities(arguments.get("element_id", "")),
                              ensure_ascii=False)
        if name == "extract_params":
            return json.dumps(self.extract_params(arguments.get("element_id", "")),
                              ensure_ascii=False)
        return json.dumps({"error": f"unknown tool {name}"})


def build_cad_tools(elements: Optional[list[DrawingElement]] = None) -> FreeCADTools:
    return FreeCADTools(elements or [])
