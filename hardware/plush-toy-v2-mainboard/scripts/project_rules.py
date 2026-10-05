"""把布线规则写进二期各版本的 .kicad_pro。

KiCad 10 的网络类与最小规则存在工程文件里（不在 .kicad_pcb）。本脚本只合并
net_settings 与 board.design_settings.rules 两块，工程文件里的其他键原样保留。
格式照 KiCad 10 自带 template 的 .kicad_pro（net_settings.meta.version = 4）。

取值依据：
- 默认类 0.2mm 线宽 / 0.15mm 间距 / 0.6-0.3mm 过孔：远高于嘉立创四层板工艺下限，留良率余量
- Power 类 0.6mm：VUSB、VSYS、VBAT、电池座与加热回路、升压开关节点。
  与 IP5306 引脚同宽（0.6mm）：1.0mm 时 Freerouting 无法在细脚处收窄，电源线接不进引脚。
  IPC-2152 估算 0.6mm / 1oz 外层短线 2A 温升约 20℃，VSYS 还有内层平面分担
- Supply 类 0.4mm：USB 输入、+3V3、GND、降压开关节点、背光
- Audio 类 0.3mm：喇叭两根线。MAX98357A 输出脚 0.25mm 宽、0.5mm 间距，峰值电流约 1A
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
    _netclass("Power", 0.6, 0.2, 0.8, 0.4, 0),
    _netclass("Supply", 0.4, 0.15, 0.6, 0.3, 1),
    _netclass("Audio", 0.3, 0.15, 0.6, 0.3, 3),
    _netclass("CameraSupply", 0.3, 0.15, 0.6, 0.3, 2),
]

PATTERNS = (
    [{"netclass": "Power", "pattern": n}
     for n in ("VUSB", "VSYS", "VBAT", "VBAT_PACK", "HEAT_LOW", "CHG_SW")]
    + [{"netclass": "Supply", "pattern": n}
       for n in ("VBUS_IN", "VBUS_FUSED", "+3V3", "GND", "BUCK_SW", "+2V8", "LCD_BL")]
    + [{"netclass": "Audio", "pattern": n} for n in ("SPK_P", "SPK_N")]
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
    "min_text_height": 0.8,          # 委托方 2026-10-05：丝印字号小一点，取嘉立创下限
    "min_text_thickness": 0.15,
}

# 不全局屏蔽丝印板边告警：天线伸出板边的模组会产生已知告警，由 DRC 测试精确白名单。
# 孔距按错误处理：KiCad 默认只报警告，同网络两个过孔孔壁相距 0.02mm 也能过 DRC（2026-10-05 复查发现）
RULE_SEVERITIES = {"silk_edge_clearance": "warning", "hole_to_hole": "error", "drill_out_of_range": "error"}


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
