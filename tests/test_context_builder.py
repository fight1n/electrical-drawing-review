from edr.core.models import RuleCategory, RuleMatch
from edr.core.state_machine import ParsedDrawing
from edr.parsing.ast_parser import extract_entities
from edr.rules.context_builder import ContextBuilder
from edr.rules.registry import default_registry


def _mini_parsed():
    raw = "QF1 断路器 额定电流 63A\n电缆 导体截面积 4mm2\n[M1] 电动机 未标注"
    ents = extract_entities(raw)
    return ParsedDrawing(
        drawing_id="T1", raw_text=raw, entities=ents,
        elements=[], chunks=[raw],
    )


def test_builds_three_stage_bundles():
    reg = default_registry()
    cb = ContextBuilder(reg, category_budgets={c.value: 1000 for c in RuleCategory})
    parsed = _mini_parsed()
    matches = [
        RuleMatch("PT-01", RuleCategory.PARAMETER_THRESHOLD, "GB 50054", "截面积"),
        RuleMatch("SA-02", RuleCategory.SYMBOL_ANNOTATION, "GB/T 5094", "标注"),
    ]
    bundles = cb.build(parsed, matches)
    assert set(bundles) == {"PT-01", "SA-02"}
    b = bundles["PT-01"]
    assert b["system_prompt"] and b["global_context"] and b["rule_context"]
    assert "条款正文" in b["rule_context"]


def test_rule_context_includes_clause_text():
    reg = default_registry()
    cb = ContextBuilder(reg)
    parsed = _mini_parsed()
    matches = [RuleMatch("WT-01", RuleCategory.WIRING_TOPOLOGY, "GB 50054", "保护接地")]
    bundles = cb.build(parsed, matches)
    assert "GB 50054" in bundles["WT-01"]["rule_context"]
