"""Parallel, category-filtered reviewer.

* Runs each selected rule concurrently with ``asyncio.gather`` under a
  semaphore (``max_concurrency``) — the parallelism requirement.
* Applies *category-conditional filtering*: a rule is only actually reviewed if
  the drawing contains elements of the kind its category needs (e.g. skip
  symbol-annotation rules when the drawing has no symbols). This avoids wasted
  LLM calls on inapplicable rules.
* Optionally drives a Claude-style Tool-Use loop against the FreeCAD atomic
  tools so the model can pull precise geometry/parameters before deciding.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from edr.core.models import RuleCategory, RuleMatch, Severity, Violation
from edr.core.trace import TraceCollector
from edr.rules.rule_categories import category_requires

# Map category -> the element signals that must exist for the rule to apply.
_CATEGORY_SIGNAL = {
    RuleCategory.GEOMETRY_SIZE: ["bbox", "dims"],
    RuleCategory.SYMBOL_ANNOTATION: ["symbols", "annotations"],
    RuleCategory.PARAMETER_THRESHOLD: ["params", "ratings"],
    RuleCategory.WIRING_TOPOLOGY: ["nets", "connections"],
}


class ParallelReviewer:
    def __init__(
        self,
        llm: Any,
        max_concurrency: int = 8,
        use_tools: bool = False,
        tools: Optional[list[dict]] = None,
        tool_executor: Optional[Callable[[str, dict], str]] = None,
    ):
        self.llm = llm
        self.semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self.use_tools = use_tools
        self.tools = tools or []
        self.tool_executor = tool_executor

    def _should_review(self, rm: RuleMatch, parsed: Any) -> bool:
        """Category-conditional filter: skip rules whose category has no signal."""
        signals = _CATEGORY_SIGNAL.get(rm.category, [])
        requires = category_requires(rm.category)
        keys = set(signals) | set(requires)
        if "bbox" in keys or "dims" in keys:
            if any(e.bbox is not None or e.type == "dimension"
                   for e in getattr(parsed, "elements", []) or []):
                return True
        if "symbols" in keys or "annotations" in keys:
            if any(e.symbol or e.type in ("symbol", "annotation")
                   for e in getattr(parsed, "elements", []) or []):
                return True
        if "params" in keys or "ratings" in keys:
            if any(e.params for e in getattr(parsed, "elements", []) or []):
                return True
        if "nets" in keys or "connections" in keys:
            if any(e.type == "net" or "connection" in (e.text or "").lower()
                   for e in getattr(parsed, "elements", []) or []):
                return True
        # If no specific signal filter matched, allow (generic/parametric rules).
        return not keys

    async def review(
        self, parsed: Any, rule_matches: list[RuleMatch], context_bundles: dict,
        trace: Optional[TraceCollector] = None, parent: Optional[str] = None,
    ) -> list[Violation]:
        applicable = [rm for rm in rule_matches if self._should_review(rm, parsed)]
        if trace:
            trace.event(node="review", action="filter", parent=parent,
                        meta={"total": len(rule_matches), "applicable": len(applicable)})

        async def _run(rm: RuleMatch) -> Optional[Violation]:
            async with self.semaphore:
                bundle = context_bundles.get(rm.rule_id, {})
                return await self._review_one(rm, bundle, parsed, trace, parent)

        results = await asyncio.gather(*[_run(rm) for rm in applicable])
        violations = [v for v in results if v is not None]
        # Deterministic order: critical first, then by severity/rule id.
        violations.sort(key=lambda v: (v.severity != Severity.CRITICAL,
                                       v.severity != Severity.MAJOR, v.rule_id))
        return violations

    async def _review_one(
        self, rm: RuleMatch, bundle: dict, parsed: Any,
        trace: Optional[TraceCollector], parent: Optional[str],
    ) -> Optional[Violation]:
        system = bundle.get("system_prompt", "")
        user = (
            bundle.get("global_context", "")
            + "\n\n"
            + bundle.get("rule_context", "")
            + "\n\n请依据以上条款与图元判断该规则是否被违反，并输出 JSON。"
        )
        messages = [{"role": "user", "content": user}]

        if self.use_tools and self.tools and self.tool_executor:
            decision = await self._tool_loop(messages, system, trace, parent)
        else:
            resp = await self.llm.complete(
                messages=messages, system=system, trace_parent=parent)
            decision = resp.json_content()

        if not isinstance(decision, dict):
            return None
        if decision.get("compliant", True):
            return None

        element_ids = bundle.get("element_ids", []) or []
        loc = element_ids[0] if element_ids else "全局"
        bbox = _first_bbox(parsed, element_ids)
        return Violation(
            rule_id=rm.rule_id,
            category=rm.category,
            clause_ref=rm.clause_ref,
            severity=Severity(decision.get("severity", "minor")),
            location=loc,
            bbox=bbox,
            description=decision.get("reason", ""),
            suggestion=decision.get("suggestion", ""),
            evidence={"confidence": decision.get("confidence")},
        )

    async def _tool_loop(self, messages, system, trace, parent) -> Any:
        """Claude-style Tool Use loop: model may call CAD tools, then decide."""
        # Turn 1: model may request tool calls.
        resp = await self.llm.complete(
            messages=messages, system=system, tools=self.tools,
            tool_choice="auto", trace_parent=parent)
        if resp.tool_calls:
            for tc in resp.tool_calls:
                result = self.tool_executor(tc.name, tc.arguments) if self.tool_executor else ""
                messages.append({"role": "assistant", "content": "", "tool_calls": [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}]})
                messages.append({"role": "tool", "content": str(result), "tool_call_id": tc.id})
            # Turn 2: model decides with tool results in context.
            resp = await self.llm.complete(
                messages=messages, system=system, trace_parent=parent)
        return resp.json_content()


def _first_bbox(parsed: Any, element_ids: list[str]):
    for e in getattr(parsed, "elements", []) or []:
        if e.id in element_ids and e.bbox is not None:
            return e.bbox
    return None
