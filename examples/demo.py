"""End-to-end demo (no API key required — uses the deterministic Mock adapter).

Run from the repo root:

    python examples/demo.py

It builds the full pipeline, runs the built-in sample drawing through all five
nodes, prints the violation summary, the full-chain Trace, and writes the PDF.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Make the src package and project root importable when run as a script.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from edr.core.config import load_config                      # noqa: E402
from edr.core.trace import TraceCollector                   # noqa: E402
from edr.wiring import build_pipeline                        # noqa: E402
from examples.sample_drawing import build_sample_drawing     # noqa: E402


async def main() -> None:
    config = load_config()
    drawing = build_sample_drawing()

    trace = TraceCollector(enabled=True)
    pipeline, llm, registry, cad = build_pipeline(config, drawing_elements=drawing["elements"],
                                                  trace=trace)

    print(f"Provider={llm.provider}  Rules={len(registry.all())}  "
          f"Rerank={'on' if config.runtime.enable_rerank else 'off'}")
    print("Pipeline: PARSE -> RULE_SELECT -> CONTEXT_BUILD -> PARALLEL_REVIEW -> REPORT\n")

    ctx = await pipeline.run(drawing["drawing_id"], drawing)

    rep = ctx.report.to_dict()
    print(f"Drawing {rep['drawing_id']} — violations: {rep['stats']['violations']}")
    for v in rep["violations"]:
        print(f"  [{v['severity']}] {v['rule_id']} {v['clause_ref']} @ {v['location']}")
        print(f"      {v['description']}")
        print(f"      建议: {v['suggestion']}")

    Path("outputs").mkdir(exist_ok=True)
    pdf = ctx.meta.get("pdf_bytes", b"")
    (Path("outputs") / f"{drawing['drawing_id']}.pdf").write_bytes(pdf)
    (Path("outputs") / f"{drawing['drawing_id']}.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nPDF  -> outputs/{drawing['drawing_id']}.pdf")
    print(f"JSON -> outputs/{drawing['drawing_id']}.json")
    print(f"Trace events: {len(trace.export())}  cost=${trace.total_cost_usd():.4f} "
          f"tokens={trace.total_tokens()}")


if __name__ == "__main__":
    asyncio.run(main())
