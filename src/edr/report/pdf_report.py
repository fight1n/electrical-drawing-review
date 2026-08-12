"""PDF report generator.

Builds a structured, review-ready PDF with:
  * a header (title / drawing id / timestamp / cost & latency)
  * a severity summary
  * a violations table: 规则ID · 违规条款 · 严重度 · 位置 · 问题描述 · 修改建议
  * an optional per-violation "位置截图" placeholder box (real screenshots may be
    injected via ``ctx.screenshots`` when a CAD renderer is wired in)

Built on ReportLab's platypus, which streams content to the canvas — for the
sizes typical of a drawing review the whole document renders well within the
3-second budget.
"""
from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path
from typing import Any, Optional

from edr.core.models import ReviewReport, Severity
from edr.core.state_machine import PipelineContext

# ReportLab is the primary rendering engine (supports CJK via STSong-Light).
# When it is unavailable we transparently fall back to a zero-dependency writer.
try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import (
        HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    _CJK_FONT = "STSong-Light"
    HAVE_REPORTLAB = True
except ImportError:  # pragma: no cover - exercised only without reportlab
    from edr.report.mini_pdf import write_simple_pdf
    _CJK_FONT = "Helvetica"
    HAVE_REPORTLAB = False

_SEV_COLOR = {
    "critical": "#c0392b",
    "major": "#e67e22",
    "minor": "#7f8c8d",
}


class PDFReportGenerator:
    def __init__(self, config: Any = None, out_dir: str = "outputs/reports"):
        self.config = config
        self.out_dir = out_dir
        self.title = getattr(getattr(config, "report", None), "title", "电气图纸自动化审核报告")
        self.include_screenshots = getattr(
            getattr(config, "report", None), "include_screenshots", True)

    # -- public ---------------------------------------------------------- #
    def generate(self, ctx: PipelineContext, trace: Any = None, parent: Any = None) -> ReviewReport:
        drawing_id = ctx.drawing_id
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        stats = {
            "rules_reviewed": len(ctx.rule_matches),
            "violations": len(ctx.violations),
            "critical": ctx.report.critical_count if ctx.report else 0,
            "major": ctx.report.major_count if ctx.report else 0,
            "minor": ctx.report.minor_count if ctx.report else 0,
            "cost_usd": round(trace.total_cost_usd(), 4) if trace else 0.0,
            "tokens": trace.total_tokens() if trace else 0,
        }

        report = ReviewReport(
            drawing_id=drawing_id, generated_at=now,
            violations=ctx.violations, stats=stats, rule_matches=ctx.rule_matches,
        )

        pdf_bytes = self._render(report, ctx)
        Path(self.out_dir).mkdir(parents=True, exist_ok=True)
        pdf_path = str(Path(self.out_dir) / f"{drawing_id}.pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)

        # Stash artifacts for the streaming API.
        ctx.meta["pdf_bytes"] = pdf_bytes
        ctx.meta["pdf_path"] = pdf_path
        if trace:
            trace.event(node="report", action="pdf_generated", parent=parent,
                        meta={"bytes": len(pdf_bytes), "path": pdf_path})
        return report

    # -- rendering ------------------------------------------------------- #
    def _render(self, report: ReviewReport, ctx: PipelineContext) -> bytes:
        # Dispatch: ReportLab (CJK-capable) when present, else zero-dep writer.
        if HAVE_REPORTLAB:
            return self._render_reportlab(report, ctx)
        return self._render_fallback(report, ctx)

    def _render_reportlab(self, report: ReviewReport, ctx: PipelineContext) -> bytes:
        from io import BytesIO
        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4, title=self.title,
            leftMargin=16 * mm, rightMargin=16 * mm,
            topMargin=16 * mm, bottomMargin=16 * mm,
        )
        styles = getSampleStyleSheet()
        h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=18, spaceAfter=6,
                            fontName=_CJK_FONT)
        body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, leading=12,
                             fontName=_CJK_FONT)
        small = ParagraphStyle("small", parent=styles["BodyText"], fontSize=8,
                              leading=10, alignment=TA_LEFT, fontName=_CJK_FONT)

        story: list[Any] = []
        story.append(Paragraph(self.title, h1))
        story.append(Paragraph(
            f"图纸编号: {report.drawing_id} &nbsp;|&nbsp; 生成时间: {report.generated_at} "
            f"&nbsp;|&nbsp; 成本: ${report.stats.get('cost_usd', 0):.4f} "
            f"&nbsp;|&nbsp; Tokens: {report.stats.get('tokens', 0)}", small))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.grey))
        story.append(Spacer(1, 6))

        # Summary line
        s = report.stats
        verdict = "不通过" if report.critical_count > 0 else ("需整改" if report.violations else "通过")
        story.append(Paragraph(
            f"审核结论: <b>{verdict}</b> &nbsp; 命中规则 {s.get('rules_reviewed',0)} 条, "
            f"违规 {s.get('violations',0)} 条 "
            f"(严重 {s.get('critical',0)} / 主要 {s.get('major',0)} / 轻微 {s.get('minor',0)})", body))
        story.append(Spacer(1, 8))

        # Violations table
        header = ["规则ID", "违规条款", "严重度", "位置", "问题描述", "修改建议"]
        rows = [header]
        for v in report.violations:
            rows.append([
                v.rule_id, v.clause_ref, v.severity.value, v.location,
                Paragraph(v.description or "", small),
                Paragraph(v.suggestion or "", small),
            ])
        if len(rows) == 1:
            rows.append(["—", "—", "—", "—", Paragraph("未发现违规项", small), Paragraph("—", small)])

        col_widths = [18 * mm, 34 * mm, 16 * mm, 22 * mm, 50 * mm, 34 * mm]
        table = Table(rows, colWidths=col_widths, repeatRows=1)
        ts = TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), _CJK_FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f7")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ])
        for i, v in enumerate(report.violations, start=1):
            ts.add("TEXTCOLOR", (2, i), (2, i),
                   colors.HexColor(_SEV_COLOR.get(v.severity.value, "#000000")))
            ts.add("FONTNAME", (2, i), (2, i), "Helvetica-Bold")
        table.setStyle(ts)
        story.append(table)

        # Optional screenshot placeholders (real images injected by a CAD renderer)
        if self.include_screenshots and report.violations:
            story.append(Spacer(1, 10))
            story.append(Paragraph("位置截图", styles["Heading3"]))
            for v in report.violations[:6]:
                label = f"[{v.rule_id}] {v.location}"
                story.append(self._placeholder(label))

        doc.build(story)
        return buf.getvalue()

    def _render_fallback(self, report: ReviewReport, ctx: PipelineContext) -> bytes:
        """Zero-dependency PDF (no CJK glyphs). Guarantees the pipeline runs."""
        from edr.report.mini_pdf import write_simple_pdf
        s = report.stats
        verdict = "不批准" if report.critical_count > 0 else ("需整改" if report.violations else "通过")
        lines = [
            f"Drawing: {report.drawing_id}",
            f"Generated: {report.generated_at}",
            f"Verdict: {verdict}  rules={s.get('rules_reviewed',0)} "
            f"violations={s.get('violations',0)} "
            f"(critical={s.get('critical',0)} major={s.get('major',0)} minor={s.get('minor',0)})",
            f"Cost=${s.get('cost_usd',0):.4f} Tokens={s.get('tokens',0)}",
            "", "Violations:",
        ]
        for v in report.violations:
            lines.append(f"[{v.severity.value}] {v.rule_id} {v.clause_ref} @ {v.location}")
            lines.append(f"   {v.description}")
            lines.append(f"   Fix: {v.suggestion}")
        if not report.violations:
            lines.append("No violations found.")
        return write_simple_pdf(lines, title=self.title)

    @staticmethod
    def _placeholder(label: str):
        from reportlab.platypus import Table as _T
        t = _T([[label], ["(位置截图占位 — 接入 CAD/渲染器后自动填充)"]],
               colWidths=[120 * mm])
        t.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#bdc3c7")),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ecf0f1")),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("TEXTCOLOR", (0, 1), (-1, 1), colors.grey),
            ("FONTNAME", (0, 0), (-1, -1), _CJK_FONT),
        ]))
        return t
