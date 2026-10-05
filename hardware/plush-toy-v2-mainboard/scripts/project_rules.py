"""把布线规则写进二期各版本的 .kicad_pro。

KiCad 10 的网络类与最小规则存在工程文件里（不在 .kicad_pcb）。本脚本只合并
net_settings 与 board.design_settings.rules 两块，工程文件里的其他键原样保留。
格式照 KiCad 10 自带 template 的 .kicad_pro（net_settings.meta.version = 4）。

取值依据：
- 默认类 0.2mm 线宽 / 0.15mm 间距 / 0.6-0.3mm 过孔：远高于嘉立创四层板工艺下限，留良率余量
- Power 类 1.0mm：VUSB、VSYS、VBAT、电池座与加热回路、升压开关节点。
  加热约 1A + 充电最多 2.1A 走 VUSB；双舵机峰值时电池侧约 2.5A
- Supply 类 0.5mm：USB 输入、+3V3、GND、降压开关节点、喇叭、背光
"""
import json
from pathlib import Path

def _netclass(name: str, track: float, clearance: float, via_d: float, via_drill: float, priority: int) -> dict:
    return {
        "bus_width": 12, "clearance": clearance, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
        "diff_pair_width": 0.2, "line_style": 0, "microvia_diameter": 0.3, "microvia_drill": 0.1,
        "name": name, "pcb_color": "rgba(0, 0, 0, 0.000)", "priority": priority,
        "schematic_color": "rgba(0, 0, 0, 0.000)", "track_width": track,
        "via_diameter": via_d, "via_drill": via_drill, "wire_width": 6,
    }


NETCLASSES = [
    _netclass("Default", 0.2, 0.15, 0.6, 0.3, 2147483647),
    _netclass("Power", 1.0, 0.2, 0.8, 0.4, 0),
    _netclass("Supply", 0.5, 0.15, 0.6, 0.3, 1),
    _netclass("CameraSupply", 0.3, 0.15, 0.6, 0.3, 2),
]

PATTERNS = (
    [{"netclass": "Power", "pattern": n}
     for n in ("VUSB", "VSYS", "VBAT", "VBAT_PACK", "HEAT_LOW", "CHG_SW")]
    + [{"netclass": "Supply", "pattern": n}
       for n in ("VBUS_IN", "VBUS_FUSED", "+3V3", "GND", "BUCK_SW", "SPK_P", "SPK_N",
                 "+2V8", "LCD_BL")]
    + [{"netclass": "CameraSupply", "pattern": "+1V5"}]
)

RULES = {
    "min_clearance": 0.127,
    "min_track_width": 0.127,
    "min_via_diameter": 0.45,
    "min_through_hole_diameter": 0.2,
    "min_via_annular_width": 0.1,
    "min_copper_edge_clearance": 0.3,
    "min_hole_clearance": 0.25,
    "min_hole_to_hole": 0.25,
    "min_text_height": 1.0,
    "min_text_thickness": 0.15,
}

# 不全局屏蔽丝印板边告警：天线伸出板边的模组会产生已知告警，由 DRC 测试精确白名单。
RULE_SEVERITIES = {"silk_edge_clearance": "warning"}


def apply(path: Path) -> Path:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() and path.read_text().strip() else {}
    ns = data.setdefault("net_settings", {})
    ns["classes"] = NETCLASSES
    ns["netclass_patterns"] = PATTERNS
    ns.setdefault("meta", {"version": 4})
    ns.setdefault("net_colors", None)
    ns.setdefault("netclass_assignments", None)
    rules = data.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rules", {})
    rules.update(RULES)
    severities = data["board"]["design_settings"].setdefault("rule_severities", {})
    severities.update(RULE_SEVERITIES)
    data.setdefault("meta", {"filename": path.name, "version": 3})
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    import context
    print(apply(context.from_argv().pro))
