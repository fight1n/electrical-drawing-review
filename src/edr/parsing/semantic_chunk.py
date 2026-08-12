"""Semantic chunking with regex table protection.

Three-layer strategy used by the parser:
  1. *Protect* table blocks (pipe tables / indented CSV) with placeholders so
     they are never split mid-row.
  2. *Split* the remaining text on semantic boundaries (blank lines, headings)
     honoring a soft token budget per chunk.
  3. *Restore* the protected tables into the chunks they belong to.
"""
from __future__ import annotations

import re
from typing import List

_TABLE_BLOCK_RE = re.compile(r"(^\|.*\|$\n?)+", re.MULTILINE)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def chunk(text: str, max_tokens: int = 400) -> List[str]:
    """Return a list of semantic chunks, tables kept intact."""
    store: dict[str, str] = {}
    counter = [0]

    def _protect(match: re.Match) -> str:
        key = f"\u0000TABLE{counter[0]}\u0000"
        counter[0] += 1
        store[key] = match.group(0)
        return key

    protected = _TABLE_BLOCK_RE.sub(_protect, text)

    # Split on blank lines and markdown headings, then pack into budgeted chunks.
    raw_parts = re.split(r"\n\s*\n|(?=^#{1,6}\s)", protected, flags=re.MULTILINE)
    chunks: List[str] = []
    current = ""

    def _flush(buf: str) -> None:
        buf = _restore(buf, store)
        if buf.strip():
            chunks.append(buf.strip())

    for part in raw_parts:
        if _estimate_tokens(current) + _estimate_tokens(part) > max_tokens and current:
            _flush(current)
            current = part
        else:
            current = (current + "\n" + part).strip() + "\n"
    _flush(current)
    return chunks


def _restore(buf: str, store: dict[str, str]) -> str:
    for key, val in store.items():
        buf = buf.replace(key, "\n" + val.strip() + "\n")
    return buf
