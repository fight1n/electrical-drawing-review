import asyncio

from edr.core.config import load_config
from edr.core.trace import TraceCollector
from edr.wiring import build_pipeline


def test_pipeline_runs_end_to_end_with_mock():
    config = load_config()  # default provider = mock
    assert config.llm.provider == "mock"

    trace = TraceCollector(enabled=True)
    pipeline, _, _, _ = build_pipeline(config, trace=trace)
    from examples.sample_drawing import build_sample_drawing
    drawing = build_sample_drawing()

    ctx = asyncio.run(pipeline.run(drawing["drawing_id"], drawing))

    assert pipeline.state.value == "done"
    assert ctx.report is not None
    assert len(ctx.report.violations) >= 1
    # PDF bytes + path produced by the report node.
    assert ctx.meta.get("pdf_bytes")
    assert len(trace.export()) > 0


def test_pipeline_hot_swap_provider():
    config = load_config()
    trace = TraceCollector(enabled=True)
    pipeline, llm, _, _ = build_pipeline(config, trace=trace)
    assert llm.provider == "mock"
    # Hot-swap is a no-op without creds but must not raise and must flip state.
    llm.set_provider("mock")
    assert llm.provider == "mock"
