"""Two-stage retriever: exact recall (inverted index) -> semantic rerank."""
from __future__ import annotations

from typing import Any, Iterable, Optional

from edr.core.models import RuleCategory, RuleMatch
from edr.core.trace import TraceCollector
from edr.retrieval.entity_recognizer import EntityRecognizer
from edr.retrieval.inverted_index import InvertedIndex
from edr.retrieval.reranker import SemanticReranker


class TwoStageRetriever:
    def __init__(self, rules: Iterable[Any], llm: Any = None, enable_rerank: bool = True):
        self.recognizer = EntityRecognizer()
        self.index = InvertedIndex()
        self.index.index_rules(rules)
        self.enable_rerank = enable_rerank
        self.reranker = SemanticReranker(llm) if (enable_rerank and llm) else None

    async def retrieve(
        self, parsed: Any, trace: Optional[TraceCollector] = None, parent: Optional[str] = None
    ) -> list[RuleMatch]:
        t = trace
        if t:
            t.event(node="retrieval", action="entity_recognize", parent=parent)
        rec = self.recognizer.recognize(parsed)

        if t:
            t.event(node="retrieval", action="index_recall", parent=parent,
                    meta={"std_codes": rec["std_codes"], "keywords": rec["keywords"]})
        candidates = self.index.recall(rec["std_codes"], rec["keywords"])

        if not candidates:
            return []

        if self.reranker is not None:
            if t:
                t.event(node="retrieval", action="semantic_rerank", parent=parent,
                        meta={"candidates": len(candidates)})
            return await self.reranker.rerank(candidates, parsed.raw_text or "", trace=t, parent=parent)

        # Rerank disabled -> pass index scores through as RuleMatch.
        return [
            RuleMatch(
                rule_id=c["rule_id"], category=_cat(c["category"]),
                clause_ref=c.get("clause_ref", ""), description=c.get("description", ""),
                score=c.get("score", 0.5), source=c.get("source", "index"),
            )
            for c in candidates
        ]


def _cat(value: str) -> RuleCategory:
    try:
        return RuleCategory(value)
    except ValueError:
        return RuleCategory.PARAMETER_THRESHOLD
