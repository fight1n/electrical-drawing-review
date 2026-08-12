"""Stage-2 semantic rerank (Agent 语义重排).

After exact recall, the LLM acts as a relevance judge: it reads the drawing
context plus each candidate rule and returns a 0..1 relevance score. This prunes
false-positive keyword hits and reorders rules by true applicability — the
"二次筛选排序" step. Falls back gracefully to index scores if the LLM call or
JSON parse fails.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from edr.core.models import RuleMatch
from edr.core.trace import TraceCollector


class SemanticReranker:
    def __init__(self, llm: Any):
        self.llm = llm

    async def rerank(
        self,
        candidates: list[dict],
        drawing_context: str,
        trace: Optional[TraceCollector] = None,
        parent: Optional[str] = None,
    ) -> list[RuleMatch]:
        if not candidates:
            return []

        prompt = self._build_prompt(candidates, drawing_context)
        try:
            resp = await self.llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system="你是电气标准审核的相关性判别器。只输出 JSON。",
                trace_parent=parent,
            )
            scores = self._parse_scores(resp.json_content())
        except Exception:  # noqa: BLE001
            scores = {}
        # Fallback: if the LLM didn't return usable scores (e.g. the deterministic
        # mock adapter), rank by lexical overlap of the candidate against the
        # drawing context so the rerank stage is still meaningful offline.
        if not scores:
            scores = self._heuristic_scores(candidates, drawing_context)

        matches: list[RuleMatch] = []
        for c in candidates:
            s = scores.get(c["rule_id"])
            if s is None:
                s = c.get("score", 0.5)
            else:
                s = float(s)
            matches.append(RuleMatch(
                rule_id=c["rule_id"],
                category=_cat(c["category"]),
                clause_ref=c.get("clause_ref", ""),
                description=c.get("description", ""),
                score=round(s, 3),
                source="rerank" if s != c.get("score") else c.get("source", "index"),
            ))
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches

    # -- helpers --------------------------------------------------------- #
    def _build_prompt(self, candidates: list[dict], context: str) -> str:
        lines = []
        for c in candidates:
            lines.append(f"- id={c['rule_id']} | 类别={c['category']} | "
                         f"条款={c.get('clause_ref','')} | {c.get('description','')}")
        cand_block = "\n".join(lines)
        return (
            "图纸上下文:\n" + context[:1500] + "\n\n"
            "候选规则:\n" + cand_block + "\n\n"
            "请判断每条候选规则对该图纸的相关度(0~1)，返回 JSON:\n"
            '{"scores": {"<rule_id>": <float>, ...}}'
        )

    @staticmethod
    def _heuristic_scores(candidates: list[dict], context: str) -> dict[str, float]:
        ctx_tokens = set(context.lower().split())
        out: dict[str, float] = {}
        for c in candidates:
            text = (c.get("description", "") + " " + c.get("clause_ref", "")).lower()
            overlap = sum(1 for t in ctx_tokens if t and t in text)
            # Blend index score (if present) with lexical overlap.
            base = float(c.get("score", 0.5))
            out[c["rule_id"]] = round(min(1.0, base * 0.5 + min(overlap, 5) * 0.1), 3)
        return out

    @staticmethod
    def _parse_scores(obj: Any) -> dict[str, float]:
        if isinstance(obj, dict) and "scores" in obj and isinstance(obj["scores"], dict):
            out = {}
            for k, v in obj["scores"].items():
                try:
                    out[str(k)] = float(v)
                except (TypeError, ValueError):
                    continue
            return out
        return {}


def _cat(value: str):
    from edr.core.models import RuleCategory
    try:
        return RuleCategory(value)
    except ValueError:
        return RuleCategory.PARAMETER_THRESHOLD
