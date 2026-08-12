"""Three-stage dynamic input trimming (成本优化核心).

For every selected rule we assemble a prompt in three layers and *trim* each
layer to a token budget so we never blow up the context window:

  Stage 1  system_prompt     — fixed auditor persona + JSON output schema
  Stage 2  global_context    — drawing-level summary shared by ALL rules
  Stage 3  rule_context      — rule-specific clause + ONLY the elements whose
                               attributes match that rule's category.

The per-category differentiation lives in ``rule_categories.CATEGORY_META``:
each of the four categories pulls a different slice of element data and gets a
different budget, which is what keeps large drawings cheap to review.
"""
from __future__ import annotations

from typing import Any, Optional

from edr.core.models import RuleCategory, RuleMatch
from edr.core.models import DrawingElement
from edr.core.trace import TraceCollector
from edr.rules.registry import RuleRegistry
from edr.rules.rule_categories import category_budget, category_requires


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _trim(text: str, budget: int) -> str:
    if _tokens(text) <= budget:
        return text
    # Trim by characters but keep whole lines where possible.
    limit = budget * 4
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [truncated]"


SYSTEM_PROMPT = (
    "你是一名资深注册电气工程师，负责依据国家与行业标准对电气图纸进行合规审核。"
    "你需要判断给定规则是否在该图纸上被违反。只依据提供的图纸上下文与条款文本进行判断，"
    "不要臆测。输出严格为 JSON："
    '{"compliant": bool, "severity": "critical|major|minor", '
    '"reason": str, "suggestion": str, "confidence": 0..1}。'
    "severity 仅在 compliant=false 时有意义。"
)


class ContextBuilder:
    def __init__(self, registry: RuleRegistry, category_budgets: Optional[dict] = None):
        self.registry = registry
        self.category_budgets = category_budgets or {}

    def _budget(self, cat: RuleCategory) -> int:
        return int(self.category_budgets.get(cat.value, category_budget(cat)))

    def build(
        self, parsed: Any, rule_matches: list[RuleMatch],
        trace: Optional[TraceCollector] = None, parent: Optional[str] = None,
    ) -> dict[str, Any]:
        # ---- Stage 2: global shared context (one per drawing) -----------
        global_ctx = self._build_global_context(parsed)
        global_budget = 800
        global_ctx = _trim(global_ctx, global_budget)

        bundles: dict[str, Any] = {}
        for rm in rule_matches:
            rule = self.registry.get(rm.rule_id)
            if rule is None:
                continue
            rule_ctx = self._build_rule_context(parsed, rule)
            budget = self._budget(rule.category)
            rule_ctx = _trim(rule_ctx, budget)
            bundles[rm.rule_id] = {
                "rule_id": rm.rule_id,
                "category": rule.category.value,
                "system_prompt": SYSTEM_PROMPT,
                "global_context": global_ctx,
                "rule_context": rule_ctx,
                "element_ids": _select_element_ids(parsed, rule.category),
            }
        if trace:
            trace.event(node="context", action="build_bundles", parent=parent,
                        meta={"bundles": len(bundles)})
        return bundles

    # -- stage 2 --------------------------------------------------------- #
    def _build_global_context(self, parsed: Any) -> str:
        elements = getattr(parsed, "elements", []) or []
        entities = getattr(parsed, "entities", []) or []
        by_type: dict[str, int] = {}
        for e in elements:
            by_type[e.type] = by_type.get(e.type, 0) + 1
        std_codes = [e.value for e in entities if e.kind == "standard_code"]
        params = {e.kind: e.value for e in entities if e.kind != "standard_code"}
        lines = [
            f"图纸元素统计: {by_type}",
            f"识别到的标准编号: {std_codes or '无'}",
            f"识别到的参数: {params or '无'}",
            f"元素总数: {len(elements)}",
        ]
        return "\n".join(lines)

    # -- stage 3 --------------------------------------------------------- #
    def _build_rule_context(self, parsed: Any, rule: Any) -> str:
        elements = getattr(parsed, "elements", []) or []
        sel = [e for e in elements if _element_matches_category(e, rule.category)]
        parts = [
            f"【规则类别】{rule.category.value}",
            f"【适用条款】{rule.clause_ref}",
            f"【条款正文】{rule.clause_text}",
            f"【审核要点】{rule.description}",
            "【相关图元】",
        ]
        for e in sel[:40]:
            parts.append(_describe_element(e))
        if not sel:
            parts.append("(本类图元未在图纸中检出，按无违反处理或结合全局上下文判断)")
        return "\n".join(parts)


def _select_element_ids(parsed: Any, cat: RuleCategory) -> list[str]:
    return [e.id for e in getattr(parsed, "elements", []) or []
            if _element_matches_category(e, cat)]


def _element_matches_category(e: DrawingElement, cat: RuleCategory) -> bool:
    """Differential element selection per category (drives cost trimming)."""
    requires = category_requires(cat)
    if "bbox" in requires or "dims" in requires:
        if e.bbox is not None or e.type == "dimension":
            return True
    if "symbols" in requires or "annotations" in requires:
        if e.symbol or e.type in ("symbol", "annotation"):
            return True
    if "params" in requires or "ratings" in requires:
        if e.params:
            return True
    if "nets" in requires or "connections" in requires:
        if e.type in ("net",) or "connection" in (e.text or "").lower():
            return True
    return False


def _describe_element(e: DrawingElement) -> str:
    bits = [f"#{e.id} [{e.type}]"]
    if e.symbol:
        bits.append(f"符号={e.symbol}")
    if e.text:
        bits.append(f"文本={e.text}")
    if e.params:
        bits.append(f"参数={e.params}")
    if e.bbox:
        bits.append(f"位置=({e.bbox.x:.2f},{e.bbox.y:.2f})")
    return "  " + " | ".join(bits)
