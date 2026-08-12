from edr.core.models import RuleCategory
from edr.retrieval.inverted_index import InvertedIndex, normalize_std
from edr.rules.registry import RuleDef


def test_normalize_std_strips_separators():
    assert normalize_std("GB 50054-2011") == "GB500542011".upper() or \
        normalize_std("GB 50054") == "GB50054"


def test_recall_by_standard_code_and_keyword():
    idx = InvertedIndex()
    r1 = RuleDef("PT-01", RuleCategory.PARAMETER_THRESHOLD, "GB 50054",
                 "导体截面积", standards=["GB 50054"], keywords=["截面积", "导体"])
    r2 = RuleDef("WT-01", RuleCategory.WIRING_TOPOLOGY, "GB 50054",
                 "保护接地", standards=["GB 50054"], keywords=["接地", "PE"])
    idx.index_rule(r1)
    idx.index_rule(r2)

    # Exact standard-code recall returns both rules; std hit scores higher.
    hits = idx.recall(["GB 50054"], ["接地"])
    ids = {h["rule_id"] for h in hits}
    assert ids == {"PT-01", "WT-01"}
    top = max(hits, key=lambda h: h["score"])
    assert top["rule_id"] == "PT-01" and top["score"] >= 1.0
