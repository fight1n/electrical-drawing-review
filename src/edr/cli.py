"""Command-line entry point.

Usage
-----
    # Run the built-in sample end-to-end (no API key needed):
    edr demo

    # Review a structured JSON drawing:
    edr review --drawing path/to/drawing.json --id DRAW-001

    # Start the HTTP service:
    edr serve --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path

from edr.core.config import load_config
from edr.core.models import BBox, DrawingElement, Entity
from edr.core.trace import TraceCollector
from edr.wiring import build_pipeline


def _coerce_drawing(data: dict) -> dict:
    """Turn a plain JSON drawing into typed objects the pipeline expects."""
    elements = []
    for e in data.get("elements", []):
        bbox = e.get("bbox")
        if isinstance(bbox, dict):
            bbox = BBox(**bbox)
        elements.append(DrawingElement(
            id=e["id"], type=e.get("type", "text"), layer=e.get("layer", "0"),
            bbox=bbox, params=e.get("params", {}), text=e.get("text"),
            symbol=e.get("symbol"), raw=e.get("raw", {}),
        ))
    entities = [Entity(kind=x.get("kind", ""), value=str(x.get("value", "")),
                       element_id=x.get("element_id"),
                       bbox=(BBox(**x["bbox"]) if isinstance(x.get("bbox"), dict) else None))
               for x in data.get("entities", [])]
    return {
        "drawing_id": data.get("drawing_id", "drawing"),
        "raw_text": data.get("raw_text", ""),
        "elements": elements,
        "entities": entities or None,
        "layout": data.get("layout", {}),
    }


def _load_drawing(spec: str) -> dict:
    if spec == "sample":
        from examples.sample_drawing import build_sample_drawing
        return build_sample_drawing()
    path = Path(spec)
    if path.exists():
        return _coerce_drawing(json.loads(path.read_text(encoding="utf-8")))
    # Treat as inline JSON.
    return _coerce_drawing(json.loads(spec))


async def _run(drawing_id: str, drawing: dict, out_dir: str) -> dict:
    config = load_config()
    trace = TraceCollector(enabled=True)
    pipeline, llm, _, _ = build_pipeline(config, trace=trace)
    ctx = await pipeline.run(drawing_id, drawing)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    pdf = ctx.meta.get("pdf_bytes", b"")
    pdf_path = Path(out_dir) / f"{drawing_id}.pdf"
    pdf_path.write_bytes(pdf)
    json_path = Path(out_dir) / f"{drawing_id}.json"
    json_path.write_text(json.dumps(ctx.report.to_dict(), ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return {
        "report": ctx.report.to_dict(),
        "pdf_path": str(pdf_path),
        "json_path": str(json_path),
        "cost_usd": trace.total_cost_usd(),
        "tokens": trace.total_tokens(),
    }


def cmd_demo(args: argparse.Namespace) -> int:
    drawing = _load_drawing("sample")
    result = asyncio.run(_run(drawing["drawing_id"], drawing, args.out))
    _print_summary(result)
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    drawing = _load_drawing(args.drawing)
    result = asyncio.run(_run(args.id or drawing.get("drawing_id", "drawing"),
                              drawing, args.out))
    _print_summary(result)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn
    uvicorn.run("edr.api:app", host=args.host, port=args.port, reload=False)
    return 0


def _print_summary(result: dict) -> None:
    rep = result["report"]
    print("=" * 60)
    print(f"图纸: {rep['drawing_id']}  结论(违规数): {rep['stats']['violations']}")
    print(f"PDF : {result['pdf_path']}")
    print(f"JSON: {result['json_path']}")
    print(f"成本: ${result['cost_usd']:.4f}  Tokens: {result['tokens']}")
    print("-" * 60)
    for v in rep["violations"]:
        print(f" [{v['severity']}] {v['rule_id']} {v['clause_ref']} @ {v['location']}")
        print(f"     {v['description']}")
        print(f"     建议: {v['suggestion']}")
    print("=" * 60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="edr", description="电气图纸自动化审核系统")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_demo = sub.add_parser("demo", help="运行内置示例")
    p_demo.add_argument("--out", default="outputs")
    p_demo.set_defaults(func=cmd_demo)

    p_review = sub.add_parser("review", help="审核指定图纸(JSON或'sample')")
    p_review.add_argument("--drawing", required=True, help="JSON路径 / 内联JSON / 'sample'")
    p_review.add_argument("--id", default=None)
    p_review.add_argument("--out", default="outputs")
    p_review.set_defaults(func=cmd_review)

    p_serve = sub.add_parser("serve", help="启动HTTP服务")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
