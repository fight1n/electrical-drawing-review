"""MinerU multimodal extraction adapter.

MinerU turns a PDF/Office/image into structured Markdown + tables + figures.
We wrap it behind a uniform interface and provide a built-in fallback so the
system runs without a MinerU server. The fallback simply reads `.txt`/`.md`
inputs and returns an empty extraction for binary files (the AST parser and
heuristic layout then carry the load).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


class MinerU:
    def __init__(self, endpoint: str = ""):
        self.endpoint = endpoint

    @property
    def available(self) -> bool:
        return bool(self.endpoint)

    def extract(self, source: Any) -> dict[str, Any]:
        if self.endpoint:
            return self._remote(source)
        return self._fallback(source)

    def _remote(self, source: Any) -> dict[str, Any]:
        import httpx  # local import; httpx is a core dep
        resp = httpx.post(self.endpoint, json={"source": str(source)}, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _fallback(self, source: Any) -> dict[str, Any]:
        """Read text/markdown directly; for other inputs return minimal stub."""
        if isinstance(source, (dict,)) and "raw_text" in source:
            return {"text": source.get("raw_text", ""), "tables": [], "images": []}
        if isinstance(source, str) and source.strip().startswith("{") and source.strip().endswith("}"):
            try:
                return json.loads(source)
            except json.JSONDecodeError:
                pass
        path = Path(source) if isinstance(source, (str, Path)) and Path(source).exists() else None
        if path and path.suffix.lower() in {".txt", ".md", ".text"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            return {"text": text, "tables": _extract_tables(text), "images": []}
        # Binary / unknown -> no direct text; AST + layout heuristics proceed.
        return {"text": "", "tables": [], "images": []}


def _extract_tables(text: str) -> list[list[str]]:
    """Pull simple pipe-delimited tables out of markdown-style text."""
    tables: list[list[str]] = []
    for line in text.splitlines():
        if line.strip().startswith("|") and line.strip().endswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            tables.append(cells)
    return tables
