from edr.core.models import BBox, DrawingElement, Entity
from edr.core.state_machine import ParsedDrawing
from edr.parsing.ast_parser import extract_entities, parse_elements
from edr.parsing.semantic_chunk import chunk


def test_extract_entities_finds_standard_and_params():
    text = "依据 GB 50054-2011，断路器额定电流 63A，电缆截面积 16mm2，间距 50mm"
    ents = extract_entities(text)
    kinds = {e.kind for e in ents}
    assert "standard_code" in kinds
    assert "rated_current_a" in kinds
    assert "cross_section_mm2" in kinds


def test_table_protection_in_chunking():
    text = (
        "说明文字一行\n\n"
        "| 项目 | 值 |\n| 截面积 | 16 |\n| 电流 | 63 |\n\n"
        "后续文字说明"
    )
    chunks = chunk(text)
    joined = "\n".join(chunks)
    # The pipe table must survive intact (not split across chunks).
    assert "| 项目 | 值 |" in joined
    assert "| 截面积 | 16 |" in joined


def test_parse_elements_creates_drawing_elements():
    text = "[QF1] 断路器\n电缆 导体截面积 4mm2"
    els = parse_elements(text)
    assert any(e.symbol == "QF1" for e in els)
    assert any("截面积" in (e.text or "") for e in els)
