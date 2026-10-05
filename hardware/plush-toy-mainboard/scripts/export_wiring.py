#!/usr/bin/env python3
"""生成《面包板 → PCB 接线对照表》。

用途：首板到手前，拿面包板上的实物模块逐针核对 PCB 插座，确认针序、器件型号和
供电域都和跑通的原型一致。自动测试只能保证 config.h ↔ 原理图 ↔ PCB 三者内部
一致，证明不了「板上的器件 = 面包板上的实物」，这张表就是补那个缺口的。

表从 board_spec 生成，不手写：手写的对照表会和板子脱节，而脱节的对照表比没有
更危险 —— 核对的人会以为自己核过了。

    python3 export_wiring.py [输出路径]
"""
from __future__ import annotations

import sys
from pathlib import Path

import board_spec

OUTPUT = Path(__file__).resolve().parents[1] / "WIRING.md"

# 网络 → GPIO。board_spec.GPIO_NET 是 {gpio: net}，这里反过来查。
NET_GPIO = {net: gpio for gpio, net in board_spec.GPIO_NET.items()}

POWER_NETS = {
    "+3V3": "3.3V 逻辑电源",
    "+2V8": "2.8V 摄像头模拟",
    "+1V5": "1.5V 摄像头数字",
    "GND": "逻辑地",
    "PGND": "功率地（只在 VMOT 端子旁与 GND 单点汇合）",
    "VMOT": "电机/加热 5V（与逻辑 5V 完全隔离）",
    "VMOT_IN": "电机/加热 5V 输入",
    "VBUS": "USB 5V",
    "VBUS_IN": "USB 5V 输入（进 eFuse 之前）",
}

# 少数网络顺着元件追出来的结果不够说明问题，这里直接写清楚。
NET_NOTES = {
    "LCD_BL": "+3V3 经 Q_LCD_BL 高边开关，由 GPIO48 低电平点亮",
}

# 插座 → (面包板上对应的东西, 核对时最容易出错的地方)。
# 这些是人的知识，board_spec 里没有，只能写在这。
CONNECTORS = {
    "J_LCD_L": ("左眼 GC9A01 1.28\" 圆屏模块",
                "模块丝印的 **SDA / SCL 是 SPI 的 MOSI / CLK，不是 I2C**。"
                "面包板上若仍是 7 针无背光的屏，插不上这个 8 针座。"),
    "J_LCD_R": ("右眼 GC9A01 1.28\" 圆屏模块",
                "除 CS 外每根线都与左眼并联；CS 走 GPIO46。"),
    "J_CAM": ("OV3660 摄像头模组（24P FPC）",
              "**⛔ 不要直接接摄像头：本板 J_CAM 引脚顺序设计反了**（摄像头第 k 脚落在本板第 25−k 脚，"
              "接上即把 +1V5 短到摄像头地，已报废一块板，见 TESTING.md 事故记录）。"
              "下表是本板焊盘的定义，**不是**摄像头排线的定义。"),
    "J_SERVO_L": ("左臂舵机", "**2 脚是 VMOT 5V，不是 3.3V**。舵机电源来自独立输入。"),
    "J_SERVO_R": ("右臂舵机", "同左臂。CH0=左 / CH1=右，丝印已标。"),
    "J_HEAT": ("加热膜", "**必须串 KSD9700 65℃ 常闭**，丝印已标。"
               "2026-09-13 事故就是加热回路误接到开发板供电。"),
    "J_NTC": ("NTC 10K 测温", "接 ADS1115 AIN0，与加热膜贴在一起。"),
    "J_TOUCH": ("头部触摸电极", "MPR121 的 E0；板上另有 12 个电极焊盘走测试点。"),
    "J_SPK": ("喇叭", "MAX98357A 桥接输出，**两根都不能接地**。"),
    "J_VMOT": ("电机/加热专用 5V 输入（螺丝端子）",
               "丝印标了 `VMOT 仅限 5V` / `电机/加热专用` 和 +/− 极性。"
               "**接反由 Q_REV 高边 P-MOS 挡住，但别指望它**。"),
    "J_MIC": ("外接 I2S 麦克风模块（INMP441 / ICS43434 / ZTS6672）",
              "针序按常见模块丝印 **VDD GND SD WS SCK L/R**。末脚是 GND，即 L/R 拉低＝左声道，"
              "与原板载 INMP441 的接法一致。板载麦克风已取消：主板本来必须放在玩偶能"
              "「听见」的位置才行，外接后才能把麦克风单独放到头部。"),
    "J_EXT": ("外接按键板 / 调试线（成品机芯上是板边那排 3V3 TX RX RST GND）",
              "**没有 RX**：GPIO44（开发板丝印 `RX`）在本板是舵机 I2C 的 SDA，给不出来。"
              "BOOT 就是固件的主功能键（单击闭麦、双击、长按），"
              "外接一个按钮同时解决「进下载模式」和「装壳后按不到键」。"),
    "J_USB": ("USB-C，烧录 + 日志 + 逻辑域供电",
              "原生 USB 走 GPIO19/20，面包板阶段已从屏 SPI 上迁走。"),
}

# 外购件：不焊在板上，但装成玩偶必须买。板上只有对应的座子，所以 board_spec
# 里没有它们，只能写在这。数量按一只玩偶算。
OFFBOARD = [
    # (件, 规格, 搜索关键词, 收货怎么验)
    # ── 板上手焊的座子：assembly=False，嘉立创不贴也不随板寄 ──
    ("2.54 单排排针", "1×40P 直针，掰成 8P ×2 + 3P ×2",
     "`2.54 单排排针 直针 1x40`",
     "J_LCD_L / J_LCD_R（8P）、J_SERVO_L / J_SERVO_R（3P）。**要直针，不要弯针**。"),
    ("PH2.0 直插针座 ×3", "JST PH 2.0mm 2P 立式（B2B-PH-K 兼容）",
     "`PH2.0 2P 直针座`",
     "J_SPK、J_NTC、J_TOUCH。**选「直针」不选「弯针」**。最好和 PH2.0 单头线同一家买，松紧最配。"),
    ("VH3.96 直插针座 ×1", "JST VH 3.96mm 2P 立式（B2P-VH 兼容）",
     "`VH3.96 2P 直针座`",
     "J_HEAT。**选「直针」**。最好和 VH3.96 单头线同一家买。"),
    ("螺丝端子 ×1", "5.08mm 2P 一体式，线从侧面进（CUI TB007-508 同尺寸）",
     "`KF301 5.08 2P 铜` 或 `DG301 5.08 2P`",
     "J_VMOT。**选铜的不选铁的**：这里过 2–3A，铁的会生锈、接触变差发热。"
     "**不要插拔式（2EDG）**，它比板上画的封装深，没核过会不会顶到别的件。"
     "焊前比一下，进线口朝板外。"),
    ("眼睛屏 ×2", "GC9A01 1.28\" 240×240 圆屏模块，**8 针带 BL**",
     "`GC9A01 1.28寸 圆屏 240x240 8针 SPI`",
     "**数排针：必须 8 针**，丝印依次 RST CS DC SDA SCL GND VCC **BL**。"
     "只有 7 针（没有 BL）的插不上，那是面包板上那种。买两块同款，避免两眼色差。"),
    ("麦克风 ×1", "I2S 数字麦克风模块",
     "`INMP441 麦克风模块` 或 `ICS43434 I2S 麦克风`",
     "6 针，丝印 VDD GND SD WS SCK L/R。ZTS6672 也可以，只要是 I2S 数字麦。"
     "**不要买模拟麦（MAX9814 那种）**，板上没有模拟输入。"),
    ("喇叭 ×1", "4Ω 或 8Ω 动圈喇叭，1–2W",
     "`4欧 3W 喇叭 20mm 带线` 或 `8欧 2W 小喇叭`",
     "阻抗必须 4Ω 或 8Ω，带引出线。直径 20–28mm 适合塞进玩偶。"
     "**低于 4Ω 不要买**，功放会过流。"),
    ("舵机 ×2", "SG90 或同级 9g 舵机",
     "`SG90 9g 舵机` 或 `MG90S 金属齿 9g 舵机`",
     "三线（棕=地 红=5V 橙=信号），工作电压 4.8–6V。"
     "**MG90S 是金属齿，比 SG90 的塑料齿耐用**，贵几块钱，推荐。"),
    ("加热膜 ×1", "5V 加热膜，约 1A",
     "`5V 硅胶加热片 加热膜`",
     "**5V 版本**，功率 5W 左右（约 1A）。买 12V 的接上去不发热。"),
    ("温控开关 ×1", "KSD9700 65℃ 常闭",
     "`KSD9700 65度 常闭 温控开关`",
     "**必须是常闭（NC）**，型号里带 65℃。这是加热回路的硬性安全件，"
     "串在加热膜的一根线上，超温自动断开。**没有它不要通电测加热**。"),
    ("NTC ×1", "10kΩ NTC 热敏电阻",
     "`10K NTC 热敏电阻 B3950 探头 带线`",
     "常温 10kΩ，B 值 3950。带线的探头款方便和加热膜贴在一起。"),
    ("触摸电极 ×1", "导电布或铜箔",
     "`导电布胶带` 或 `铜箔胶带 屏蔽`",
     "贴在头部做触摸感应，引一根线到 J_TOUCH。面积大一点灵敏度高。"),
    ("摄像头 ×1", "OV3660 模组，24P 0.5mm FPC",
     "`OV3660 摄像头模块 24P` 或 `ESP32 摄像头 OV3660 0.5mm`",
     "**排线必须是 24P、间距 0.5mm**。OV2640 引脚兼容也能用，分辨率低一些。"
     "注意排线金手指的朝向（下接触式）。"),
    ("USB-C 数据线", "能传数据的 USB-C 线",
     "（家里有就行）",
     "**必须是数据线，不能是只能充电的线**。烧不进固件时第一个换它。"),
    ("电机电源 ×1", "5V / 3A 独立电源",
     "`5V 3A 电源适配器 DC` + `DC母头 转接线`",
     "接 J_VMOT 螺丝端子供舵机和加热。**必须和 USB 分开，不可共用** —— "
     "这是 2026-09-13 事故后的硬约束。DC 转接线剪开接进螺丝端子，注意正负。"),
    ("SH 转杜邦线 ×2", "SH1.0 转 2.54 杜邦母头，5P 与 6P 各一根",
     "`SH1.0 6P 转 杜邦母头` / `SH1.0 5P 转 杜邦母头`",
     "6P 接 J_MIC，5P 接 J_EXT。**买「转杜邦母头」不是「双头线」** —— "
     "J_MIC 的针序就是按麦克风模块丝印排的，母头直接套模块排针，免焊。"
     "**收货先用万用表量一遍是不是顺序直通**，有些卖家做交叉线。"),
    ("PH2.0 单头线 ×3", "JST PH 2.0mm 2P，一端插头一端裸线",
     "`PH2.0 2P 单头线 一端端子`",
     "接 J_SPK（喇叭）、J_NTC、J_TOUCH 各一根。很便宜，建议买一包 10 根。"
     "**别买双头线**，另一端要接喇叭/探头的裸线。"
     "**选「母头」**：插头要套在板上针座的针上，带孔、看不到金属针的那头；"
     "「公头」是线对线用的，插不上板子。"),
    ("VH3.96 单头线 ×1", "JST VH 3.96mm 2P，一端插头一端裸线",
     "`VH3.96 2P 单头线`",
     "只有 J_HEAT（加热膜）用这个，它是大电流座子，**和上面的 PH2.0 不通用**。"
     "线径 **22AWG 或更粗**（1A 回路），长度 20–30cm，宁长勿短 —— 中间还要剪开串 KSD9700。"),
    ("免焊接线端子", "按压式快速接线端子，2 孔",
     "`Wago 221 2孔` 或 `快速接线端子 2孔 按压`",
     "把两根裸线免焊接在一起，按一下杆子塞进去。NTC、触摸电极可以这么接。"
     "**加热回路不建议用** —— 那里跑 1A，长期在玩偶里被挤压会接触不良发热，焊。"),
    ("热缩管", "φ1–3mm 混装",
     "`热缩管 套装 混装`",
     "所有焊点都要套。加热回路的接头尤其不能裸露。"),
    ("屏线", "2.54mm 端子线，8P 两根",
     "`2.54 端子线 8P 单头` + `30AWG 硅胶线`",
     "**建议买 30AWG 硅胶线自己压端子，别用杜邦线** —— 16 根杜邦线穿过玩偶"
     "脖子又粗又硬。线长按实际量，建议 ≤ 10cm（超过要把 SPI 降到 20MHz）。"),
    ("USB 电压电流表", "串在 USB 线上看电流",
     "`USB 电压电流表 测试仪`",
     "约 30–60 元。**首次上电必备** —— 没有限流电源时，这是唯一能在"
     "短路烧坏东西之前发现问题的手段。电流要显示到 **0.01A 或更细**；"
     "要有 USB-A 输入 + Type-C 输出（A 口充电头不看 CC 电阻，照样给 5V）。蓝牙功能用不上。"),
    ("USB-A 充电头", "5V / 1–2A 普通充电头",
     "（家里有就行）",
     "首次上电用它，**不插电脑** —— 有短路烧的是充电头。不要用快充头。"),
    ("万用表", "有电阻档、直流电压档",
     "`数字万用表`",
     "第三节不通电量电阻、第四节量 3V3。"),
    ("尖头表笔", "细针表笔",
     "`万用表表笔 尖头 细针`",
     "J_MIC / J_EXT 脚距 1mm，普通表笔会同时碰到两脚。"),
    ("恒温烙铁套装", "可调温，带尖头 / 刀头、烙铁架、镊子、0.8mm 含松香焊锡丝",
     "`恒温电烙铁 套装 可调温`",
     "焊上面那 9 个座子。**不要不能调温的烙铁**，温度过高会烫掉焊盘。焊直插件 330–350℃。"),
    ("助焊膏 / 吸锡带 / 洗板水", "焊接耗材",
     "`助焊膏 电子` / `吸锡带 2mm` / `洗板水`",
     "助焊膏让新手好焊很多；吸锡带清连锡；洗板水刷掉助焊剂残留。"),
    ("杜邦线 母对母", "2.54mm，20cm，至少 16 根",
     "`杜邦线 母对母 20cm 40P`",
     "验收阶段接眼睛屏：板上和屏上都是公针。单根线可以调顺序，屏的脚序和板子不同也能对上。"),
    ("红外测温枪", "非接触测温",
     "`红外测温枪 工业`",
     "约 50–100 元。测降压芯片、MOSFET、端子温升，替代热像仪，而且不会烫伤。"),
    ("假负载 ×1", "5Ω / 10W 水泥电阻",
     "`5欧 10W 水泥电阻`",
     "加热回路第一次通电用它代替加热膜，验证 MOSFET 受控通断。"
     "**先用假负载验过再接真加热膜**。"),
]

# 板载器件 → (面包板上对应的模块, 备注)
MODULES = {
    "U1": ("ESP32-S3 开发板", "N16R8：16MB Flash + 8MB PSRAM。"),
    "U_AMP": ("功放模块", "委托方 2026-09-15 确认可用 MAX98357A 或 HT517。"
              "板上按 MAX98357A 画；**换 HT517 前必须对数据手册核封装与针序**，"
              "不能只换 BOM 料号。"),
    "U_PWM": ("PCA9685 舵机驱动板", "I2C 从机；固件实测 PRE_SCALE=121。"),
    "U_TOUCH": ("MPR121 触摸板", "I2C 从机。"),
    "U_IMU": ("MPU-6050 六轴", "I2C 从机。"),
    "U_ADC": ("ADS1115 四路 ADC", "I2C 从机；AIN0 接 NTC，AIN1–3 悬空。"),
}


# footprint 关键字 → (座子人话型号, 配套买什么, 需不需要自己接线)。
# 从 board_spec 的 footprint 推导，不手写 —— 座子换了这张表自动跟着变。
HOUSINGS = [
    ("JST_SH_BM05B", "JST SH 1.0mm 5P 卧贴", "`SH1.0 5P 转 2.54 杜邦母头` 单头线", "插上即可"),
    ("JST_SH_BM06B", "JST SH 1.0mm 6P 卧贴", "`SH1.0 6P 转 2.54 杜邦母头` 单头线", "插上即可"),
    ("JST_PH_B2B", "JST PH 2.0mm 2P", "`PH2.0 2P 单头线`（裸线端）", "需接线"),
    ("JST_VH_B2P", "JST VH 3.96mm 2P", "`VH3.96 2P 单头线`（裸线端）", "需接线"),
    ("PinHeader_1x03", "2.54mm 排针 3P", "舵机自带三线母头", "插上即可"),
    ("PinHeader_1x08", "2.54mm 排针 8P", "`2.54 端子线 8P` 或定制 30AWG 线束", "插上即可"),
    ("TerminalBlock", "5.08mm 螺丝端子 2P", "电源线剥皮直接拧入", "拧螺丝，免焊"),
    ("FPC-SMD_24P", "24P 0.5mm FPC 翻盖座", "摄像头模组自带排线", "插上即可"),
    ("USB_C_Receptacle", "USB-C 母座", "USB-C 数据线", "插上即可"),
]


def housing(ref: str) -> tuple[str, str, str]:
    footprint = part(ref).footprint
    for key, name, cable, effort in HOUSINGS:
        if key in footprint:
            return name, cable, effort
    raise SystemExit(f"{ref} 的 footprint {footprint} 没有对应的座子型号，补进 HOUSINGS")


def part(ref: str) -> board_spec.Part:
    return next(item for item in board_spec.PARTS if item.ref == ref)


def owners(net: str) -> list[tuple[board_spec.Part, str]]:
    return [(item, number) for item in board_spec.PARTS
            for number, name in item.pins.items() if name == net]


def describe(net: str, seen: frozenset[str] = frozenset()) -> str:
    """把插座上的网络名翻译成「它到底连到哪」。

    先查 GPIO 和电源，再顺着串联电阻往回追一层（屏的 33Ω、CC 的 5.1kΩ 都靠这个），
    最后退回到驱动它的那颗芯片。全部从 board_spec 推导，不靠手写。
    """
    if net.startswith("NC_"):
        return "悬空"
    if net in NET_NOTES:
        return NET_NOTES[net]
    if net in NET_GPIO:
        return f"GPIO{NET_GPIO[net]}"
    if net in POWER_NETS:
        return POWER_NETS[net]

    # 先看有没有芯片直接驱动它：「ADS1115 第 5 脚」比「经 10kΩ 到 3V3」有用得多。
    for spec, number in owners(net):
        if spec.ref.startswith(("U", "Q")) and spec.ref != "U1":
            return f"{spec.ref} {spec.value} 第 {number} 脚"

    # 没有芯片的，顺着串联电阻往回追（屏的 33Ω、CC 的 5.1kΩ 都靠这个）。
    seen = seen | {net}
    for spec, number in owners(net):
        if spec.symbol != "Device:R" or len(spec.pins) != 2:
            continue
        other = next(name for pin, name in spec.pins.items() if pin != number)
        if other in seen:
            continue
        resolved = describe(other, seen)
        if resolved != "—":
            return f"{resolved}（经 {spec.ref} {spec.value}Ω）"
    return "—"


def pin_order(pins: dict[str, str]) -> list[tuple[str, str]]:
    def key(item):
        number = item[0]
        return (0, int(number)) if number.isdigit() else (1, number)

    return sorted(pins.items(), key=key)


def connector_table(ref: str) -> list[str]:
    spec = part(ref)
    module, caution = CONNECTORS[ref]
    name, cable, effort = housing(ref)
    lines = [f"### {ref} — {module}", "",
             f"**座子**：{name} ｜ **配套线**：{cable} ｜ {effort}", ""]
    if caution:
        lines += [f"> {caution}", ""]
    lines += ["| 针号 | 网络 | ESP32 引脚 / 电源 | 面包板那一端接的是 | 核对 |",
              "|---|---|---|---|---|"]
    for number, net in pin_order(spec.pins):
        label = "（悬空）" if net.startswith("NC_") else f"`{net}`"
        lines.append(f"| {number} | {label} | {describe(net)} |  | ☐ |")
    lines.append("")
    return lines


def render() -> str:
    lines = [
        "# 面包板 → PCB 接线对照表",
        "",
        "**本文件由 `scripts/export_wiring.py` 从 `board_spec.py` 生成，不要手工编辑。**",
        "板子改了就重跑一次，别改这里 —— 和板子脱节的对照表比没有更危险，",
        "核对的人会以为自己核过了。",
        "",
        "## 怎么用",
        "",
        "自动测试（`test_board_spec` 等）已经证明 `main/boards/plush-toy/config.h` ↔ 原理图 ↔ PCB",
        "三者内部一致，而 config.h 就是面包板上跑通的那一份，所以**ESP32 那一侧的引脚号不用你核**。",
        "",
        "测试证明不了的是另一侧：插座的针序对不对得上你手里的模块、器件型号是不是面包板上的那颗。",
        "这张表就是核这个的。拿实物对着丝印一根根数，在「核对」列打勾，",
        "「面包板那一端接的是」一列填你实际量到的信号名。",
        "",
        "## 与面包板故意不同的地方",
        "",
        "这些是按设计就该不一样，首板行为变了不要当成 bug：",
        "",
        "| 项 | 面包板 | PCB |",
        "|---|---|---|",
        "| I2C 上拉 | 多个模块的上拉并联到约 2.0kΩ | 全板只有一组 4.7kΩ，靠近 ESP32 |",
        "| 电源 | 逻辑与电机/加热共用 | 两个独立输入，**板上不存在能把二者连起来的铜** |",
        "| 地 | 共地 | PGND 与 GND 只在 VMOT 端子旁单点汇合 |",
        "| 状态灯 | 板载 WS2812（GPIO48） | 取消；GPIO48 改驱动双眼背光 |",
        "| 眼屏 | 7 针，背光内部常亮 | 8 针带 BL，两眼共用受控背光 |",
        "",
        "---",
        "",
        "## 一、插座逐针核对",
        "",
    ]
    for ref in CONNECTORS:
        lines += connector_table(ref)

    lines += ["---", "", "## 二、板载器件核对", "",
              "| 位号 | 板上型号 | LCSC | 面包板上对应 | 备注 | 核对 |",
              "|---|---|---|---|---|---|"]
    for ref, (module, note) in MODULES.items():
        spec = part(ref)
        lines.append(f"| {ref} | {spec.value} | {spec.lcsc} | {module} | {note} | ☐ |")

    lines += ["", "---", "", "## 三、外购件采购清单", "",
              "板上不贴、装玩偶时另外买的东西。**给的是搜索关键词不是链接** ——",
              "商品链接会失效、会换货，而「收货怎么验」那一列才是真正防止买错的东西。",
              "",
              "| 件 | 规格 | 搜索关键词 | 收货怎么验 | 已买 |",
              "|---|---|---|---|---|"]
    for name, spec, keyword, check in OFFBOARD:
        lines.append(f"| {name} | {spec} | {keyword} | {check} | ☐ |")

    lines += ["", "---", "", "## 四、每个座子买什么线，哪些要自己接", "",
              "板上的座子不是一种，**线材不通用**。下表从 `board_spec.py` 的 footprint 生成。",
              "",
              "| 座子 | 接什么 | 座子型号 | 配套线 | 要不要自己接 |",
              "|---|---|---|---|---|"]
    for ref in CONNECTORS:
        module, _ = CONNECTORS[ref]
        name, cable, effort = housing(ref)
        lines.append(f"| {ref} | {module.split('（')[0]} | {name} | {cable} | {effort} |")

    lines += ["",
              "**需接线的是那四处 PH2.0 / VH3.96**，因为喇叭、NTC、导电布、加热膜出来都是裸线，",
              "得和插头的裸线端接在一起。其中喇叭有些卖家发货就带 PH2.0 插头，**买之前问一句"
              "间距是不是 2.0mm**（2.54 的 XH 插不上），带插头的就省一道。",
              "",
              "**唯独加热回路没有成品**：KSD9700 温控开关必须串在加热膜的一根线上，",
              "市面上没有「加热膜自带温控开关且带 VH3.96 插头」的东西。",
              "",
              "裸线接头可以用按压式接线端子免焊，但**加热回路建议焊**：1A 电流、",
              "玩偶里长期受挤压，接触电阻变大会发热，而那正是 2026-09-13 事故的同一条回路。",
              "",
              "嫌麻烦可以搜「**端子线定制**」，把型号针数线长发给卖家做好，几块钱一根。",
              "眼睛屏那两根尤其值得定制 —— 30AWG 硅胶线自己压 2.54 端子很费劲。",
              "",
              "面包板上已有的麦克风、喇叭、摄像头、舵机、加热膜、NTC **都能直接复用**，",
              "要重买的只有眼睛屏（7 针换 8 针）和上面这些线材。",
              "",
              "---", "",
              "## 五、核完之后",
              "",
              "针序和器件都对上了，只说明板子画的是你想要的东西。",
              "USB、相机、SPI、音频、无线、电源和加热安全仍然必须由首板实测确认，",
              "清单见 [TESTING.md](../TESTING.md)。",
              ""]
    return "\n".join(lines)


def main() -> Path:
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT
    destination.write_text(render(), encoding="utf-8")
    return destination


if __name__ == "__main__":
    print(main())
