"""Lightweight 5-node state machine for the review pipeline.

Nodes (in order):
    PARSE  ->  RULE_SELECT  ->  CONTEXT_BUILD  ->  PARALLEL_REVIEW  ->  REPORT

The machine is intentionally small: a transition table, a context object that
carries data between nodes, and an orchestrator that drives the nodes while
emitting progress events (used by the streaming API) and recording every hop in
the Trace collector.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from edr.core.models import ReviewReport, Violation
from edr.core.trace import TraceCollector

ProgressCallback = Callable[[str, dict[str, Any]], None]


class PipelineState(str, Enum):
    INIT = "init"
    PARSE = "parse"
    RULE_SELECT = "rule_select"
    CONTEXT_BUILD = "context_build"
    PARALLEL_REVIEW = "parallel_review"
    REPORT = "report"
    DONE = "done"
    ERROR = "error"


# Allowed transitions — keeps the machine from wandering into invalid states.
_TRANSITIONS: dict[PipelineState, list[PipelineState]] = {
    PipelineState.INIT: [PipelineState.PARSE],
    PipelineState.PARSE: [PipelineState.RULE_SELECT, PipelineState.ERROR],
    PipelineState.RULE_SELECT: [PipelineState.CONTEXT_BUILD, PipelineState.ERROR],
    PipelineState.CONTEXT_BUILD: [PipelineState.PARALLEL_REVIEW, PipelineState.ERROR],
    PipelineState.PARALLEL_REVIEW: [PipelineState.REPORT, PipelineState.ERROR],
    PipelineState.REPORT: [PipelineState.DONE, PipelineState.ERROR],
    PipelineState.DONE: [],
    PipelineState.ERROR: [],
}


@dataclass
class ParsedDrawing:
    drawing_id: str
    elements: list = field(default_factory=list)     # List[DrawingElement]
    entities: list = field(default_factory=list)     # List[Entity]
    chunks: list = field(default_factory=list)       # semantic chunks
    layout: dict = field(default_factory=dict)
    raw_text: str = ""


@dataclass
class RuleContextBundle:
    rule_id: str
    category: str
    system_prompt: str          # stage 1
    global_context: str         # stage 2
    rule_context: str           # stage 3
    element_ids: list[str] = field(default_factory=list)


@dataclass
class PipelineContext:
    drawing_id: str
    parsed: Optional[ParsedDrawing] = None
    rule_matches: list = field(default_factory=list)
    context_bundles: dict = field(default_factory=dict)   # rule_id -> RuleContextBundle
    violations: list = field(default_factory=list)        # List[Violation]
    report: Optional[ReviewReport] = None
    screenshots: dict = field(default_factory=dict)        # element_id -> image bytes/path
    meta: dict = field(default_factory=dict)


class ReviewPipeline:
    """Generic orchestrator. Engines are injected so the machine stays decoupled
    from concrete parsing/retrieval/review/report implementations."""

    def __init__(
        self,
        parser: Any,
        retriever: Any,
        context_builder: Any,
        reviewer: Any,
        reporter: Any,
        trace: Optional[TraceCollector] = None,
        on_progress: Optional[ProgressCallback] = None,
    ):
        self.parser = parser
        self.retriever = retriever
        self.context_builder = context_builder
        self.reviewer = reviewer
        self.reporter = reporter
        self.trace = trace or TraceCollector(enabled=False)
        self.on_progress = on_progress
        self.state = PipelineState.INIT

    # -- node transition helper ------------------------------------------- #
    def _transition(self, target: PipelineState) -> None:
        allowed = _TRANSITIONS.get(self.state, [])
        if target not in allowed and target != PipelineState.ERROR:
            raise RuntimeError(f"Illegal transition {self.state} -> {target}")
        self.state = target

    def _progress(self, node: str, **payload: Any) -> None:
        if self.on_progress:
            self.on_progress(node, payload)

    # -- nodes ------------------------------------------------------------ #
    async def _node_parse(self, ctx: PipelineContext, drawing_input: Any) -> None:
        self._transition(PipelineState.PARSE)
        parent = self.trace.event(node="state", action="enter:parse")
        self._progress("parse", status="start")
        ctx.parsed = await _maybe_await(self.parser.parse(drawing_input, trace=self.trace, parent=parent))
        self._progress("parse", status="done",
                       elements=len(ctx.parsed.elements),
                       entities=len(ctx.parsed.entities))
        self.trace.event(node="state", action="exit:parse", parent=parent)

    async def _node_rule_select(self, ctx: PipelineContext) -> None:
        self._transition(PipelineState.RULE_SELECT)
        parent = self.trace.event(node="state", action="enter:rule_select")
        self._progress("rule_select", status="start")
        ctx.rule_matches = await _maybe_await(
            self.retriever.retrieve(ctx.parsed, trace=self.trace, parent=parent))
        self._progress("rule_select", status="done", rules=len(ctx.rule_matches))
        self.trace.event(node="state", action="exit:rule_select", parent=parent)

    async def _node_context_build(self, ctx: PipelineContext) -> None:
        self._transition(PipelineState.CONTEXT_BUILD)
        parent = self.trace.event(node="state", action="enter:context_build")
        self._progress("context_build", status="start")
        ctx.context_bundles = await _maybe_await(
            self.context_builder.build(ctx.parsed, ctx.rule_matches, trace=self.trace, parent=parent))
        self._progress("context_build", status="done", bundles=len(ctx.context_bundles))
        self.trace.event(node="state", action="exit:context_build", parent=parent)

    async def _node_parallel_review(self, ctx: PipelineContext) -> None:
        self._transition(PipelineState.PARALLEL_REVIEW)
        parent = self.trace.event(node="state", action="enter:parallel_review")
        self._progress("parallel_review", status="start")
        ctx.violations = await self.reviewer.review(
            ctx.parsed, ctx.rule_matches, ctx.context_bundles,
            trace=self.trace, parent=parent)
        self._progress("parallel_review", status="done", violations=len(ctx.violations))
        self.trace.event(node="state", action="exit:parallel_review", parent=parent)

    async def _node_report(self, ctx: PipelineContext) -> None:
        self._transition(PipelineState.REPORT)
        parent = self.trace.event(node="state", action="enter:report")
        self._progress("report", status="start")
        ctx.report = await _maybe_await(
            self.reporter.generate(ctx, trace=self.trace, parent=parent))
        self._progress("report", status="done", path=getattr(ctx.report, "pdf_path", None))
        self.trace.event(node="state", action="exit:report", parent=parent)

    # -- driver ----------------------------------------------------------- #
    async def run(self, drawing_id: str, drawing_input: Any) -> PipelineContext:
        ctx = PipelineContext(drawing_id=drawing_id)
        self.trace.event(node="state", action="pipeline:start", meta={"drawing_id": drawing_id})
        try:
            await self._node_parse(ctx, drawing_input)
            await self._node_rule_select(ctx)
            await self._node_context_build(ctx)
            await self._node_parallel_review(ctx)
            await self._node_report(ctx)
            self._transition(PipelineState.DONE)
            self._progress("done", status="ok",
                           violations=len(ctx.violations),
                           cost_usd=round(self.trace.total_cost_usd(), 4))
        except Exception as exc:  # noqa: BLE001
            self.state = PipelineState.ERROR
            ctx.meta["error"] = str(exc)
            self._progress("error", status="failed", error=str(exc))
            self.trace.event(node="state", action="pipeline:error", meta={"error": str(exc)})
            raise
        self.trace.event(node="state", action="pipeline:end")
        return ctx


async def _maybe_await(value: Any) -> Any:
    if isinstance(value, Awaitable):
        return await value
    return value
