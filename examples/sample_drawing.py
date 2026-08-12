"""A self-contained sample drawing for demos and tests.

Returns a *structured* drawing (the same shape the parsing pipeline would
produce from a real file) so the end-to-end flow can be exercised without any
external parser, model weights or API keys.
"""
from edr.core.models import BBox, DrawingElement, Entity


def build_sample_drawing() -> dict:
    raw_text = (
        "某车间低压配电系统图\n"
        "QF1 断路器 额定电流 63A 分断能力 10kA\n"
        "电缆 YJV 导体截面积 4mm2 额定电压 0.4kV\n"
        "电动机 M1 [M1] 功率 15kW\n"
        "配电柜 电气间隙 8mm 爬电距离 12mm\n"
        "端子排 未标注回路编号 缺少设备位号\n"
        "保护接地 PE 线被中间开关断开 不连续\n"
        "回路 N 与 PE 在末端混接\n"
    )

    elements = [
        DrawingElement(id="E1", type="text", layer="0", text="某车间低压配电系统图"),
        DrawingElement(id="E2", type="symbol", symbol="QF1", text="断路器",
                       params={"rated_current_a": "63", "分断能力": "10kA"},
                       bbox=BBox(0.2, 0.8, 0.1, 0.05)),
        DrawingElement(id="E3", type="text", text="电缆 YJV 导体截面积 4mm2 额定电压 0.4kV",
                       params={"cross_section_mm2": "4", "voltage": "0.4kV"}),
        DrawingElement(id="E4", type="symbol", symbol="M1", text="电动机 功率 15kW",
                       params={"rated_current_a": "30"}, bbox=BBox(0.5, 0.5, 0.1, 0.05)),
        DrawingElement(id="E5", type="dimension",
                       text="配电柜 电气间隙 8mm 爬电距离 12mm",
                       params={"电气间隙": "8mm"}, bbox=BBox(0.1, 0.3, 0.3, 0.2)),
        DrawingElement(id="E6", type="annotation", text="端子排 未标注回路编号 缺少设备位号"),
        DrawingElement(id="E7", type="text",
                       text="保护接地 PE 线被中间开关断开 不连续"),
        DrawingElement(id="E8", type="net", text="回路 N 与 PE 在末端混接"),
    ]

    entities = [
        Entity(kind="standard_code", value="GB50054"),
        Entity(kind="standard_code", value="GB/T4728"),
        Entity(kind="rated_current_a", value="63"),
        Entity(kind="cross_section_mm2", value="4"),
        Entity(kind="voltage", value="0.4kV"),
        Entity(kind="clearance_mm", value="8"),
    ]

    return {
        "drawing_id": "SAMPLE-001",
        "raw_text": raw_text,
        "elements": elements,
        "entities": entities,
        "layout": {"regions": [{"label": "text", "bbox": [0, 0, 1, 1]}]},
    }
