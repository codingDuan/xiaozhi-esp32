"""二期器件模型。与一期 board_spec.Part 字段相同，便于复用一期导出脚本的思路。"""
from dataclasses import dataclass, field


@dataclass
class Part:
    ref: str
    value: str
    symbol: str
    footprint: str
    lcsc: str = ""
    fitted: bool = True
    pins: dict[str, str] = field(default_factory=dict)
    assembly: bool = True


R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
TESTPAD = "TestPoint:TestPoint_Pad_D1.0mm"

# 一期已在产品页核对过的阻容料号，二期沿用；新增阻值在 Task 1 Step 3 补并核对
LCSC_R = {"0": "C17168", "33": "C25105", "100": "C25076", "1k": "C11702", "4.7k": "C25900",
          "5.1k": "C25905", "10k": "C25744", "22k": "C25768", "75k": "C25798",
          "100k": "C25741", "1M": "C26083"}
LCSC_C = {"22pF": "C1555", "2.2nF": "C1531", "3.3nF": "C696855", "10nF": "C15195",
          "100nF": "C1525", "1uF": "C52923", "4.7uF": "C23733"}


def res(ref: str, value: str, a: str, b: str) -> Part:
    return Part(ref, value, "Device:R", R0402, LCSC_R[value], True, {"1": a, "2": b})


def cap(ref: str, value: str, a: str, b: str) -> Part:
    return Part(ref, value, "Device:C", C0402, LCSC_C[value], True, {"1": a, "2": b})


def cap10u(ref: str, a: str, b: str) -> Part:
    return Part(ref, "10uF", "Device:C", C0603, "C19702", True, {"1": a, "2": b})


def cap22u(ref: str, a: str, b: str) -> Part:
    return Part(ref, "22uF", "Device:C", C0805, "C45783", True, {"1": a, "2": b})


def testpoint(ref: str, net: str) -> Part:
    return Part(ref, net, "Connector:TestPoint", TESTPAD, pins={"1": net}, assembly=False)


def nc(ref: str, pin: str) -> str:
    return f"NC_{ref}_{pin}"
