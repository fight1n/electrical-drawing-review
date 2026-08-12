"""Zero-dependency fallback PDF writer.

Used only when ReportLab is not installed. It emits a valid, dependency-free PDF
with the report text (header, summary, violation lines). It intentionally uses
the standard Helvetica font, so non-ASCII (e.g. Chinese glyphs) will be blank —
for full CJK rendering, install ReportLab (which uses its built-in STSong-Light
CID font). The fallback guarantees the pipeline always produces *a* PDF so the
system remains runnable in constrained environments.
"""
from __future__ import annotations

A4 = (595.28, 841.89)
MARGIN = 40.0


def _esc(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _wrap(text: str, max_chars: int = 90) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if len(cur) + len(w) + 1 <= max_chars:
            cur = (cur + " " + w).strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def write_simple_pdf(lines: list[str], title: str = "Report") -> bytes:
    pages: list[list[str]] = []
    cur: list[str] = []
    y = A4[1] - MARGIN
    line_h = 14.0

    def add_page(content_lines: list[str]) -> None:
        pages.append(content_lines)

    wrapped: list[str] = [_esc(title)]
    for ln in lines:
        wrapped.extend(_esc(s) for s in _wrap(ln))
    # paginate
    page_lines: list[str] = []
    for i, ln in enumerate(wrapped):
        if i == 0:
            page_lines.append(("title", ln))
            continue
        page_lines.append(("body", ln))
    # split into pages by height
    pages_content: list[list[tuple[str, str]]] = []
    cur_page: list[tuple[str, str]] = []
    used = MARGIN
    for kind, txt in page_lines:
        used += 20.0 if kind == "title" else line_h
        if used > A4[1] - MARGIN:
            pages_content.append(cur_page)
            cur_page = []
            used = MARGIN + (20.0 if kind == "title" else line_h)
        cur_page.append((kind, txt))
    if cur_page:
        pages_content.append(cur_page)

    # Build PDF objects
    objects: list[bytes] = []
    # 1 Catalog, 2 Pages, then per page: Page + Content; plus Font
    font_obj_num = 3 + 2 * len(pages_content)  # after catalog, pages, page objs+content
    # We'll assign numbers sequentially.
    n_pages = len(pages_content)
    page_obj_nums: list[int] = []
    content_obj_nums: list[int] = []
    num = 3
    for _ in range(n_pages):
        page_obj_nums.append(num); num += 1
        content_obj_nums.append(num); num += 1
    font_num = num; num += 1

    # Catalog
    catalog = b"<< /Type /Catalog /Pages 2 0 R >>"
    # Pages
    kids = " ".join(f"{p} 0 R" for p in page_obj_nums)
    pages_obj = f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode()

    objs: list[bytes] = [catalog, pages_obj]
    for idx in range(n_pages):
        page = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {A4[0]:.2f} {A4[1]:.2f}] "
            f"/Resources << /Font << /F1 {font_num} 0 R >> >> /Contents {content_obj_nums[idx]} 0 R >>"
        ).encode()
        objs.append(page)
        # content stream
        stream_parts = ["BT"]
        y = A4[1] - MARGIN
        for kind, txt in pages_content[idx]:
            if kind == "title":
                stream_parts.append("/F1 16 Tf")
                stream_parts.append(f"1 0 0 1 {MARGIN:.2f} {y:.2f} Tm")
                stream_parts.append(f"({txt}) Tj")
                y -= 24
            else:
                stream_parts.append("/F1 10 Tf")
                stream_parts.append(f"1 0 0 1 {MARGIN:.2f} {y:.2f} Tm")
                stream_parts.append(f"({txt}) Tj")
                y -= 14
        stream_parts.append("ET")
        content = "\n".join(stream_parts).encode("latin-1", "replace")
        content_obj = b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"
        objs.append(content_obj)
    # Font
    font_obj = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objs.append(font_obj)

    # Serialize with xref
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, ob in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + ob + b"\nendobj\n"
    xref_pos = len(out)
    n = len(objs) + 1
    out += f"xref\n0 {n}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += b"trailer\n"
    out += f"<< /Size {n} /Root 1 0 R >>\n".encode()
    out += b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    return bytes(out)
