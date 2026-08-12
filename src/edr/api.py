"""FastAPI service exposing the review pipeline.

Endpoints
---------
* ``GET  /health``              — liveness + active provider
* ``POST /review``              — run pipeline, return JSON report + base64 PDF + trace
* ``POST /review/pdf``          — run pipeline, stream the PDF via StreamingResponse
* ``POST /review/stream``       — NDJSON stream of node progress events, ending with
                                  a ``pdf`` event carrying the report + base64 PDF

The streaming endpoints satisfy the "经 StreamingResponse 流式输出" requirement;
report rendering is fast enough (ReportLab) to stay within the 3-second budget
for typical drawings.
"""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from edr.core.config import load_config
from edr.core.trace import TraceCollector
from edr.wiring import build_pipeline

app = FastAPI(title="Electrical Drawing Review API", version="0.1.0")
CONFIG = load_config()


class ReviewRequest(BaseModel):
    drawing_id: str
    drawing: Any  # structured dict | file path string


@app.get("/health")
def health():
    return {"status": "ok", "provider": CONFIG.llm.provider,
            "enable_rerank": CONFIG.runtime.enable_rerank}


@app.post("/review")
async def review(req: ReviewRequest):
    trace = TraceCollector(enabled=True)
    pipeline, _, _, _ = build_pipeline(CONFIG, trace=trace)
    ctx = await pipeline.run(req.drawing_id, req.drawing)
    pdf = ctx.meta.get("pdf_bytes", b"")
    return {
        "report": ctx.report.to_dict(),
        "pdf_base64": base64.b64encode(pdf).decode("ascii"),
        "trace": trace.export(),
    }


@app.post("/review/pdf")
async def review_pdf(req: ReviewRequest):
    trace = TraceCollector(enabled=True)
    pipeline, _, _, _ = build_pipeline(CONFIG, trace=trace)
    ctx = await pipeline.run(req.drawing_id, req.drawing)
    pdf = ctx.meta.get("pdf_bytes", b"")
    return StreamingResponse(
        iter([pdf]), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{req.drawing_id}.pdf"'},
    )


@app.post("/review/stream")
async def review_stream(req: ReviewRequest):
    queue: asyncio.Queue = asyncio.Queue()
    trace = TraceCollector(enabled=True)
    pipeline, _, _, _ = build_pipeline(CONFIG, trace=trace)

    def on_progress(node: str, **payload: Any) -> None:
        queue.put_nowait({"node": node, **payload})

    pipeline.on_progress = on_progress

    async def runner():
        ctx = await pipeline.run(req.drawing_id, req.drawing)
        pdf = ctx.meta.get("pdf_bytes", b"")
        await queue.put({
            "node": "pdf",
            "report": ctx.report.to_dict(),
            "pdf_base64": base64.b64encode(pdf).decode("ascii"),
        })
        await queue.put(None)  # sentinel

    task = asyncio.create_task(runner())

    async def gen():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield (json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8")
        await task

    return StreamingResponse(gen(), media_type="application/x-ndjson")
