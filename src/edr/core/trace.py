"""Full-chain Trace audit.

Every significant step (LLM call, retrieval hit, rule decision) is recorded with
a monotonic id, parent link, timestamps, model, token usage and latency. The
collector can be exported to JSONL for downstream cost/quality analysis and is
the backbone of the "全链路 Trace 审计" requirement.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class TraceEvent:
    id: str
    ts: float
    node: str                     # pipeline node / subsystem
    action: str
    parent: Optional[str] = None
    model: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TraceCollector:
    """Thread/async-safe collector for trace events."""

    def __init__(self, trace_id: Optional[str] = None, enabled: bool = True):
        self.trace_id = trace_id or uuid.uuid4().hex[:12]
        self.enabled = enabled
        self._events: list[TraceEvent] = []
        self._lock = threading.Lock()
        self._root: Optional[str] = None

    def event(
        self,
        node: str,
        action: str,
        parent: Optional[str] = None,
        model: Optional[str] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0.0,
        cost_usd: float = 0.0,
        meta: Optional[dict[str, Any]] = None,
    ) -> str:
        if not self.enabled:
            return ""
        ev = TraceEvent(
            id=uuid.uuid4().hex[:10],
            ts=time.time(),
            node=node,
            action=action,
            parent=parent or self._root,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            meta=meta or {},
        )
        with self._lock:
            self._events.append(ev)
        return ev.id

    def span(self, node: str, action: str, parent: Optional[str] = None):
        """Context manager that records latency & returns a child trace id."""
        return _Span(self, node, action, parent)

    def total_cost_usd(self) -> float:
        return sum(e.cost_usd for e in self._events)

    def total_tokens(self) -> int:
        return sum(e.prompt_tokens + e.completion_tokens for e in self._events)

    def export(self) -> list[dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in self._events]

    def save(self, directory: str | Path) -> Path:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"trace_{self.trace_id}.jsonl"
        with self._lock:
            lines = [json.dumps(e.to_dict(), ensure_ascii=False) for e in self._events]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


class _Span:
    def __init__(self, collector: TraceCollector, node: str, action: str, parent):
        self.c = collector
        self.node = node
        self.action = action
        self.parent = parent
        self._id: Optional[str] = None
        self._t0 = 0.0

    def __enter__(self) -> str:
        self._t0 = time.time()
        self._id = self.c.event(self.node, self.action + ":start", parent=self.parent)
        return self._id

    def __exit__(self, exc_type, exc, tb) -> None:
        lat = (time.time() - self._t0) * 1000.0
        self.c.event(
            self.node,
            self.action + ":end",
            parent=self._id,
            latency_ms=lat,
            meta={"error": str(exc) if exc else None},
        )
