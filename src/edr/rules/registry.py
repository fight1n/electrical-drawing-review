"""Rule definitions and registry.

Each :class:`RuleDef` carries the standard references and keywords used for
exact-match recall, plus the clause text injected into the rule-specific context
during the three-stage build. The default registry bundles representative rules
across all four categories; users can extend it via :meth:`RuleRegistry.add`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from edr.core.models import RuleCategory


@dataclass
class RuleDef:
    rule_id: str
    category: RuleCategory
    clause_ref: str
    description: str
    standards: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    clause_text: str = ""


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, RuleDef] = {}

    def add(self, rule: RuleDef) -> None:
        self._rules[rule.rule_id] = rule

    def all(self) -> list[RuleDef]:
        return list(self._rules.values())

    def by_category(self, cat: RuleCategory) -> list[RuleDef]:
        return [r for r in self._rules.values() if r.category == cat]

    def get(self, rule_id: str) -> RuleDef | None:
        return self._rules.get(rule_id)


def default_registry() -> RuleRegistry:
    reg = RuleRegistry()

    # ---- 几何尺寸与间距 --------------------------------------------------
    reg.add(RuleDef(
        "GS-01", RuleCategory.GEOMETRY_SIZE,
        "GB 50054-2011 第4.2.1条",
        "裸露带电体之间及带电体至接地部分的最小电气净距应满足规范要求。",
        standards=["GB 50054", "IEC 61439"],
        keywords=["间距", "净距", "电气安全距离", "带电体"],
        clause_text=("配电装置中裸露带电导体之间、以及带电导体至接地金属之间的"
                     "净距，在标称电压≤1kV时应不小于12.5mm(电气间隙)与20mm(爬电距离)。"),
    ))
    reg.add(RuleDef(
        "GS-02", RuleCategory.GEOMETRY_SIZE,
        "GB 7251.1-2013 第7.1.3条",
        "成套开关设备内电气间隙与爬电距离符合额定绝缘电压要求。",
        standards=["GB 7251.1", "IEC 61439-1"],
        keywords=["电气间隙", "爬电距离", "柜体"],
        clause_text="成套设备内部不同极性裸露带电部分间电气间隙应≥10mm，爬电距离应≥14mm。",
    ))

    # ---- 符号与标注 ------------------------------------------------------
    reg.add(RuleDef(
        "SA-01", RuleCategory.SYMBOL_ANNOTATION,
        "GB/T 4728 / IEC 60617",
        "电气图形符号应符合国家标准，禁止自创或歧义符号。",
        standards=["GB/T 4728", "IEC 60617"],
        keywords=["符号", "图形符号", "标注"],
        clause_text="电气简图用图形符号应采用GB/T 4728系列，符号含义唯一且无歧义。",
    ))
    reg.add(RuleDef(
        "SA-02", RuleCategory.SYMBOL_ANNOTATION,
        "GB/T 5094.1-2002",
        "设备与端子应有完整、可追溯的文字标注(设备位号/代号)。",
        standards=["GB/T 5094", "IEC 81346"],
        keywords=["标注", "编号", "位号", "代号"],
        clause_text="图中所有设备、元件应标注唯一位号，并与材料表一一对应。",
    ))

    # ---- 参数阈值与选型 --------------------------------------------------
    reg.add(RuleDef(
        "PT-01", RuleCategory.PARAMETER_THRESHOLD,
        "GB 50054-2011 第3.2.1条",
        "导体截面积不得低于规范规定的最小值，并满足载流量与热稳定。",
        standards=["GB 50054", "GB 50217"],
        keywords=["截面积", "导体", "电缆", "载流量"],
        clause_text=("固定敷设的铜芯导体截面积：照明回路≥1.5mm²，动力回路≥2.5mm²；"
                     "移动设备≥1.0mm²。选型须校验载流量与短路热稳定。"),
    ))
    reg.add(RuleDef(
        "PT-02", RuleCategory.PARAMETER_THRESHOLD,
        "GB 50054-2011 第6.3.3条",
        "断路器额定分断能力与额定电流应匹配回路预期短路电流与负荷。",
        standards=["GB 50054", "IEC 60898"],
        keywords=["断路器", "额定电流", "分断能力", "保护"],
        clause_text="短路保护电器的分断能力不应小于安装处预期短路电流最大值。",
    ))
    reg.add(RuleDef(
        "PT-03", RuleCategory.PARAMETER_THRESHOLD,
        "GB/T 50065-2011 第6章",
        "接地电阻值应满足系统接地型式要求(如TN系统≤4Ω)。",
        standards=["GB/T 50065", "IEC 60364"],
        keywords=["接地", "接地电阻", "等电位"],
        clause_text="低压系统中性点直接接地系统的接地电阻不宜大于4Ω。",
    ))

    # ---- 拓扑与接线 ------------------------------------------------------
    reg.add(RuleDef(
        "WT-01", RuleCategory.WIRING_TOPOLOGY,
        "GB 50054-2011 第3.1.4条",
        "保护接地导体(PE)必须独立、连续，严禁用中性线(N)兼作PE。",
        standards=["GB 50054", "IEC 60364-4-41"],
        keywords=["保护接地", "PE", "等电位", "接地"],
        clause_text="TN系统中保护接地导体应独立设置，不得利用中性导体兼作保护导体。",
    ))
    reg.add(RuleDef(
        "WT-02", RuleCategory.WIRING_TOPOLOGY,
        "GB 50303-2015 第5.1.1条",
        "同一照明回路不得串联连接(插座/灯具之间须并联)。",
        standards=["GB 50303"],
        keywords=["接线", "串联", "并联", "回路"],
        clause_text="灯具、插座回路应采用并联接线，严禁利用器具端子串联供电。",
    ))
    reg.add(RuleDef(
        "WT-03", RuleCategory.WIRING_TOPOLOGY,
        "GB 50054-2011 第3.1.5条",
        "TN-S系统中N线与PE线严禁混接，PE线全程不得断开。",
        standards=["GB 50054", "IEC 60364"],
        keywords=["TN-S", "N线", "PE线", "混接"],
        clause_text="TN-S系统的中性导体与保护导体应严格分开，保护导体不得接入开关电器。",
    ))

    return reg
