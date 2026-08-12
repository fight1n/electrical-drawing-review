"""Entity recognition for retrieval.

Reuses the AST parser's extracted :class:`Entity` list and turns it into the two
query streams the inverted index needs:
  * standard codes  -> exact recall
  * parameter kinds -> keyword expansion (截面积/间距/额定电流/电压 ...)
"""
from __future__ import annotations

from typing import Any

# Map a parameter entity kind to the keywords that should trigger related rules.
_PARAM_KEYWORDS = {
    "cross_section_mm2": ["截面积", "导体", "电缆"],
    "clearance_mm": ["间距", "净距", "电气安全距离"],
    "rated_current_a": ["额定电流", "断路器", "保护"],
    "voltage": ["额定电压", "电压等级"],
}

# Map a parameter entity kind to its descriptive rule category hint.
_PARAM_CATEGORY_HINT = {
    "cross_section_mm2": "parameter_threshold",
    "clearance_mm": "geometry_size",
    "rated_current_a": "parameter_threshold",
    "voltage": "parameter_threshold",
}


class EntityRecognizer:
    def recognize(self, parsed: Any) -> dict[str, Any]:
        std_codes: list[str] = []
        keywords: list[str] = []
        param_values: dict[str, list[str]] = {}

        for ent in getattr(parsed, "entities", []) or []:
            if ent.kind == "standard_code":
                std_codes.append(ent.value)
            elif ent.kind in _PARAM_KEYWORDS:
                keywords.extend(_PARAM_KEYWORDS[ent.kind])
                param_values.setdefault(ent.kind, []).append(ent.value)

        # Also expand on raw text keywords (cheap safety net).
        text = getattr(parsed, "raw_text", "") or ""
        for kw_list in _PARAM_KEYWORDS.values():
            for kw in kw_list:
                if kw in text and kw not in keywords:
                    keywords.append(kw)

        return {
            "std_codes": std_codes,
            "keywords": keywords,
            "param_values": param_values,
        }
