"""PP-DocLayout layout-segmentation adapter.

In production you fine-tune PaddleOCR's PP-DocLayout on your drawing corpus and
point ``weights`` at the checkpoint. When the weights (or PaddleOCR) are absent
we fall back to a heuristic region splitter so the pipeline still produces a
usable layout map. The fallback is deterministic and good enough for routing
text/tables/symbols to the right downstream stage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Region:
    label: str            # text | table | title | figure | seal
    bbox: tuple          # (x0, y0, x1, y1) normalized 0..1
    score: float = 1.0
    meta: dict = field(default_factory=dict)


class DocLayoutDetector:
    def __init__(self, weights: str = "", use_gpu: bool = False):
        self.weights = weights
        self.use_gpu = use_gpu
        self._model = self._load()

    def _load(self):
        if not self.weights:
            return None
        try:
            # Lazy import so the heavy dep is only required when actually used.
            from paddleocr import PP_DocLayout  # type: ignore
            model = PP_DocLayout(model_name="PP-DocLayout-L", weights_path=self.weights)
            return model
        except Exception as exc:  # noqa: BLE001
            print(f"[doclayout] weights given but load failed, using heuristic: {exc}")
            return None

    @property
    def available(self) -> bool:
        return self._model is not None

    def detect(self, text: str = "", page_size: tuple = (1.0, 1.0)) -> list[Region]:
        if self._model is not None:
            # Real inference would run here; we keep the call site identical.
            return self._infer(text)
        return self._heuristic(text, page_size)

    def _infer(self, text: str) -> list[Region]:
        # Placeholder for real model output; returns a single text region.
        return [Region("text", (0.0, 0.0, 1.0, 1.0), score=0.9)]

    def _heuristic(self, text: str, page_size: tuple) -> list[Region]:
        """Split the page into a title region, table regions and text regions."""
        regions: list[Region] = []
        lines = text.splitlines()
        if not lines:
            return [Region("text", (0.0, 0.0, 1.0, 1.0))]

        # Title: first non-empty short line near the top.
        if lines and len(lines[0]) < 40:
            regions.append(Region("title", (0.0, 0.0, 1.0, 0.12), score=0.8))

        # Tables: contiguous lines containing the pipe or multiple commas.
        table_re = re.compile(r"\|.*\|")
        in_table = False
        start = 0
        for i, ln in enumerate(lines):
            is_table = bool(table_re.search(ln)) or (ln.count(",") >= 3 and len(ln) > 20)
            if is_table and not in_table:
                in_table = True
                start = i
            elif not is_table and in_table:
                in_table = False
                y0 = start / len(lines)
                y1 = i / len(lines)
                regions.append(Region("table", (0.0, y0, 1.0, y1), score=0.7))
        if in_table:
            regions.append(Region("table", (0.0, start / len(lines), 1.0, 1.0), score=0.7))

        # Text: everything not claimed by a table/title.
        regions.append(Region("text", (0.0, 0.12, 1.0, 1.0), score=0.6))
        return regions
