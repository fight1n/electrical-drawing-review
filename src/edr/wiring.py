"""Dependency wiring: assemble the full pipeline from configuration.

Keeps construction in one place so the API, CLI and tests all share the same
object graph. Swapping a backend (e.g. a real MinerU endpoint or a fine-tuned
DocLayout checkpoint) is a one-line config change here.
"""
from __future__ import annotations

from typing import Any, Optional

from edr.cad.freecad_tools import CAD_TOOL_SPECS, build_cad_tools
from edr.core.config import Config
from edr.core.llm_adapter import LLMAdapterRouter
from edr.core.state_machine import ReviewPipeline
from edr.core.trace import TraceCollector
from edr.parsing.pipeline import ParsingPipeline
from edr.report.pdf_report import PDFReportGenerator
from edr.retrieval.engine import TwoStageRetriever
from edr.review.reviewer import ParallelReviewer
from edr.rules.context_builder import ContextBuilder
from edr.rules.registry import default_registry


def build_pipeline(
    config: Config,
    drawing_elements: Optional[list] = None,
    trace: Optional[TraceCollector] = None,
    use_tools: bool = False,
):
    trace = trace or TraceCollector(enabled=True)

    llm = LLMAdapterRouter(
        provider=config.llm.provider, trace=trace,
        claude_model=config.llm.claude_model, openai_model=config.llm.openai_model,
        temperature=config.llm.temperature, max_tokens=config.llm.max_tokens,
        timeout=config.llm.timeout_seconds,
    )

    registry = default_registry()
    parser = ParsingPipeline(
        doclayout_weights=config.runtime.doclayout_weights,
        mineru_endpoint=config.runtime.mineru_endpoint,
    )
    retriever = TwoStageRetriever(
        rules=registry.all(), llm=llm.adapter, enable_rerank=config.runtime.enable_rerank,
    )

    budgets = {cat: meta.context_budget for cat, meta in config.rules.categories.items()}
    context_builder = ContextBuilder(registry, category_budgets=budgets)

    cad = build_cad_tools(drawing_elements)
    reviewer = ParallelReviewer(
        llm.adapter, max_concurrency=config.runtime.max_concurrency,
        use_tools=use_tools, tools=CAD_TOOL_SPECS, tool_executor=cad.execute,
    )

    reporter = PDFReportGenerator(config)
    pipeline = ReviewPipeline(
        parser=parser, retriever=retriever, context_builder=context_builder,
        reviewer=reviewer, reporter=reporter, trace=trace,
    )
    return pipeline, llm, registry, cad
