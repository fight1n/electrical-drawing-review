"""Inverted index for exact-match recall.

Maps (a) standard references (GB/IEC/DL/...) and (b) keyword tokens to rules.
Stage-1 retrieval is a pure in-memory lookup — O(1) per term, no model needed —
which keeps the hot path fast and cheap before the LLM rerank stage.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterable

_STD_NORM = re.compile(r"[^A-Za-z0-9]")


def normalize_std(code: str) -> str:
    return _STD_NORM.sub("", code).upper()


def tokenize(text: str) -> set[str]:
    # Keep CJK runs as single tokens (they carry meaning as a whole) plus ascii words.
    tokens: set[str] = set()
    for m in re.finditer(r"[A-Za-z0-9]+|[一-鿿]{2,}", text):
        tokens.add(m.group(0).lower())
    return tokens


class InvertedIndex:
    def __init__(self) -> None:
        self._std_index: dict[str, list[dict]] = defaultdict(list)
        self._kw_index: dict[str, list[dict]] = defaultdict(list)
        self._rules: dict[str, dict] = {}

    # -- build ----------------------------------------------------------- #
    def index_rule(self, rule: Any) -> None:
        rec = {
            "rule_id": rule.rule_id,
            "category": rule.category.value if hasattr(rule.category, "value") else str(rule.category),
            "clause_ref": getattr(rule, "clause_ref", ""),
            "description": getattr(rule, "description", ""),
            "standards": getattr(rule, "standards", []) or [],
            "keywords": getattr(rule, "keywords", []) or [],
        }
        self._rules[rec["rule_id"]] = rec
        for std in rec["standards"]:
            self._std_index[normalize_std(std)].append(rec)
        for kw in rec["keywords"]:
            for tok in tokenize(kw):
                self._kw_index[tok].append(rec)

    def index_rules(self, rules: Iterable[Any]) -> None:
        for r in rules:
            self.index_rule(r)

    # -- query ----------------------------------------------------------- #
    def recall(self, std_codes: Iterable[str], keywords: Iterable[str]) -> list[dict]:
        """Exact recall. Returns de-duplicated rules with a 0..1 score."""
        scored: dict[str, float] = {}
        sources: dict[str, str] = {}
        for code in std_codes:
            for rec in self._std_index.get(normalize_std(code), []):
                rid = rec["rule_id"]
                scored[rid] = max(scored.get(rid, 0.0), 1.0)
                sources[rid] = "index:std"
        for kw in keywords:
            for tok in tokenize(kw):
                for rec in self._kw_index.get(tok, []):
                    rid = rec["rule_id"]
                    scored[rid] = max(scored.get(rid, 0.0), 0.6)
                    sources.setdefault(rid, "index:kw")
        out = []
        for rid, score in scored.items():
            rec = dict(self._rules[rid])
            rec["score"] = round(score, 3)
            rec["source"] = sources[rid]
            out.append(rec)
        out.sort(key=lambda r: r["score"], reverse=True)
        return out
