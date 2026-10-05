"""二期器件库：料号、符号、封装、语义引脚 → 焊盘号。全项目只有这里出现手册引脚号。
每条的出处与核对结论写在 ../SELECTION.md 对应小节。

一个语义名可以对应一组焊盘（tuple），例如芯片的多个 GND 脚；part() 会把网络接到组内每个焊盘。
"""
from dataclasses import dataclass

from v2.part import Part

Pads = dict[str, "str | tuple[str, ...]"]


@dataclass(frozen=True)
class Entry:
    lcsc: str
    symbol: str
    footprint: str
    pads: Pads
    value: str = ""


def pad_numbers(entry: Entry) -> set[str]:
    numbers: set[str] = set()
    for pad in entry.pads.values():
        numbers.update(pad if isinstance(pad, tuple) else (pad,))
    return numbers


DB: dict[str, Entry] = {
    # ── 主控 ──
    # SELECTION.md §WROOM：GPIO 焊盘由 gpio.WROOM_PAD_GPIO 负责，这里只列电源与不可用脚
    "WROOM": Entry("C2913202", "RF_Module:ESP32-S3-WROOM-1", "RF_Module:ESP32-S3-WROOM-1",
                   {"GND": ("1", "40", "41"), "3V3": "2", "EN": "3",
                    "IO35": "28", "IO36": "29", "IO37": "30"}, "ESP32-S3-WROOM-1-N16R8"),

    # ── 电源 ──
    # SELECTION.md §IP5306-I2C：I2C 版本把 LED1/2/3 改作 SCL/SDA/IRQ，无指示灯驱动脚
    "IP5306_I2C": Entry("C488349", "plushv2:IP5306-I2C",
                        "plushv2:ESOP-8_L4.9-W3.9-P1.27-LS6.0-BL-EP2.0",
                        {"VIN": "1", "SCL": "2", "SDA": "3", "IRQ": "4", "KEY": "5",
                         "BAT": "6", "SW": "7", "VOUT": "8", "GND": "9"}, "IP5306-I2C"),
    # SELECTION.md §TPS259531：与一期 U_EFUSE 实测接法一致（3/4 IN、5 OUT）
    "TPS259531": Entry("C2155674", "plushv2:TPS259531",
                       "Package_SON:Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm_ThermalVias",
                       {"DVDT": "1", "EN": "2", "IN": ("3", "4"), "OUT": "5", "FLT": "6",
                        "ILM": "7", "GND": ("8", "9")}, "TPS259531DSGR"),
    # SELECTION.md §SY8089：引脚同 TLV62569DBV 符号（一期已用）
    "SY8089": Entry("C78988", "Regulator_Switching:TLV62569DBV", "Package_TO_SOT_SMD:SOT-23-5",
                    {"EN": "1", "GND": "2", "SW": "3", "IN": "4", "FB": "5"}, "SY8089AAAC"),
    "INDUCTOR_BOOST": Entry("C135287", "plushv2:SMNR5030-1R0MT", "plushv2:IND-SMD_L5.0-W5.0_SMNR5030",
                            {"1": "1", "2": "2"}, "1uH"),
    "INDUCTOR_BUCK": Entry("C2926400", "Device:L", "plushv2:IND-SMD_L4.0-W4.0_YHNR4020",
                           {"1": "1", "2": "2"}, "2.2uH"),
    "PTC_USB": Entry("C883132", "Device:Fuse", "Fuse:Fuse_1206_3216Metric",
                     {"1": "1", "2": "2"}, "BSMD1206-150-6V"),
    "ESD_LINE": Entry("C172409", "Device:D_TVS", "Diode_SMD:D_SOD-882",
                      {"IO": "1", "GND": "2"}, "LESD8D3.3CAT5G"),
    "NTC_0603_10K": Entry("C13564", "Device:Thermistor_NTC", "Resistor_SMD:R_0603_1608Metric",
                          {"1": "1", "2": "2"}, "10k NTC"),

    # ── 开关管 ──
    "AO3400A": Entry("C20917", "Transistor_FET:AO3400A", "Package_TO_SOT_SMD:SOT-23",
                     {"G": "1", "S": "2", "D": "3"}, "AO3400A"),
    "AO3401A": Entry("C15127", "Transistor_FET:AO3401A", "Package_TO_SOT_SMD:SOT-23",
                     {"G": "1", "S": "2", "D": "3"}, "AO3401A"),

    # ── 音频与传感器 ──
    # SELECTION.md §功放：NS4168 输入高电平 0.7×VDD，5V 供电时 3.3V 逻辑够不着，改回一期 MAX98357A
    "MAX98357A": Entry("C910544", "Audio:MAX98357A",
                       "Package_DFN_QFN:TQFN-16-1EP_3x3mm_P0.5mm_EP1.23x1.23mm",
                       {"DIN": "1", "GAIN": "2", "GND": ("3", "11", "15", "17"), "SD_MODE": "4",
                        "NC5": "5", "NC6": "6", "VDD": ("7", "8"), "OUTP": "9", "OUTN": "10",
                        "NC12": "12", "NC13": "13", "LRCLK": "14", "BCLK": "16"}, "MAX98357AETE+T"),
    # SELECTION.md §LIS2DH12：手册 Table 2，5 脚 Res 必须接地
    "LIS2DH12": Entry("C110926", "plushv2:LIS2DH12TR", "plushv2:LGA-12_L2.0-W2.0-P0.50-BL",
                      {"SCL": "1", "CS": "2", "SDO_SA0": "3", "SDA": "4", "RES": "5",
                       "GND": ("6", "7", "8"), "VDD": "9", "VDD_IO": "10", "INT2": "11", "INT1": "12"},
                      "LIS2DH12TR"),

    # ── 连接器（固定脚 MP 不接网络）──
    "USB_C16": Entry("C165948", "Connector:USB_C_Receptacle_USB2.0_16P",
                     "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
                     {"GND": ("A1", "B1", "A12", "B12"), "VBUS": ("A4", "B4", "A9", "B9"),
                      "CC1": "A5", "CC2": "B5", "DP": ("A6", "B6"), "DN": ("A7", "B7"),
                      "SBU1": "A8", "SBU2": "B8", "SHIELD": "SH"}, "TYPE-C-31-M-12"),
    "CONN_BAT": Entry("C295747", "Connector_Generic:Conn_01x02",
                      "Connector_JST:JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal",
                      {"+": "1", "-": "2"}, "BAT PH2.0"),
    "CONN_LCD8": Entry("C160407", "Connector_Generic:Conn_01x08",
                       "Connector_JST:JST_SH_SM08B-SRSS-TB_1x08-1MP_P1.00mm_Horizontal",
                       {str(i): str(i) for i in range(1, 9)}, "LCD SH1.0-8P"),
    "CONN_MIC6": Entry("C2845365", "plushv2:HC-1.0-6PWT", "plushv2:CONN-SMD_HCTL_HC-1.0-6PWT",
                       {**{str(i): str(i) for i in range(1, 7)}, "MP1": "7", "MP2": "8"}, "MIC SH1.0-6P"),
    "CONN_HEAT2": Entry("C7429671", "plushv2:ZX-XH2.54-2PWT", "plushv2:CONN-SMD_2P-P2.54_MEGASTAR_ZX-XH2.54-2PWT",
                        {"1": "1", "2": "2", "MP1": "3", "MP2": "4"}, "HEAT XH2.54-2P"),
    "CONN_SH2": Entry("C160402", "Connector_Generic:Conn_01x02",
                      "Connector_JST:JST_SH_SM02B-SRSS-TB_1x02-1MP_P1.00mm_Horizontal",
                      {"1": "1", "2": "2"}, "SH1.0-2P"),
    "CONN_KEY3": Entry("C7430445", "plushv2:ZX-SH1.0-3PWT", "plushv2:CONN-SMD_3P-P1.00_MEGASTAR_ZX-SH1.0-3PWT",
                       {"1": "1", "2": "2", "3": "3", "MP1": "4", "MP2": "5"}, "KEY SH1.0-3P"),
    "HDR_SERVO3": Entry("C46061676", "plushv2:HXPZ2.54-1X3PWT",
                        "plushv2:HDR-SMD_3P-P2.54-H-M_KH-2.54PH-1X3P-L13.5-WT",
                        {"1": "1", "2": "2", "3": "3"}, "SERVO 2.54-1x3P"),
    "SW_TACT": Entry("C720477", "plushv2:TS-1088-AR02016", "plushv2:SW-SMD_L3.9-W3.0-P4.45",
                     {"A": "1", "B": "2"}, "TS-1088-AR02016"),
}


def part(key: str, ref: str, nets: dict[str, str]) -> Part:
    """按语义名连线；未列出的焊盘标为不连接。语义名写错立即 KeyError。"""
    entry = DB[key]
    unknown = set(nets) - set(entry.pads)
    if unknown:
        raise KeyError(f"{key} 没有语义引脚 {sorted(unknown)}")
    pins = {pad: f"NC_{ref}_{pad}" for pad in pad_numbers(entry)}
    for name, net in nets.items():
        pad = entry.pads[name]
        for number in (pad if isinstance(pad, tuple) else (pad,)):
            pins[number] = net
    return Part(ref, entry.value or key, entry.symbol, entry.footprint, entry.lcsc, True, pins)
