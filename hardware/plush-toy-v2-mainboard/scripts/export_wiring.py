#!/usr/bin/env python3
"""生成二期《接线表与外购清单》variants/<版本>/WIRING.md。

表从 ctx.parts 生成，不手写：手写的接线表会和板子脱节，而脱节的接线表比没有
更危险 —— 接线的人会以为自己核过了。

    python3 export_wiring.py --variant A
"""
from __future__ import annotations

import context
from v2 import cam, gpio

POWER_NETS = {
    "+3V3": "3.3V（降压 SY8089 输出）",
    "GND": "地",
    "VSYS": "系统 5V（IP5306 升压输出，电池或 USB 都有）",
    "VUSB": "USB 5V（eFuse 之后；**拔掉 USB 就没电**）",
    "VBUS_IN": "USB 5V 输入（保险丝之前）",
    "VBAT_PACK": "电池 +（经板上防反接再进 IP5306）",
}

NET_NOTES = {
    "LCD_BL": "+3V3 经 Q_LCD_BL 高边开关，GPIO48 低电平点亮",
    "KEY_PWR": "IP5306 KEY 脚（短按开机，1 秒内连按两下关机）",
}

# 出线座 → (接什么, 接线时最容易出错的地方)
CONNECTORS = {
    "J_LCD": ("双眼 GC9A01 1.28\" 圆屏模块 ×2（共用一根片选）",
              "头部用 **Y 型线** 把 8 根线一分为二，两只眼完全并联（包括 CS）。"
              "模块丝印的 **SDA / SCL 是 SPI 的 MOSI / CLK，不是 I2C**。屏必须是 8 针带 BL 的版本。"),
    "J_MIC": ("I2S 麦克风模块（INMP441 / ICS43434）",
              "针序与一期 J_MIC 相同（3V3 GND SD WS SCK GND），**一期那根 SH1.0 6P 线直接复用**。"),
    "J_SPK": ("喇叭 4Ω / 8Ω", "MAX98357A 桥接输出，**两根都不能接地**，也不能和别的喇叭并联。"),
    "J_ARM_L": ("左臂舵机", "1 脚信号、2 脚 5V、3 脚地。舵机线**橙/黄（信号）对 S**、棕/黑（地）对 G。"
                "**不要插反**：插反时舵机的地线落在 GPIO3 上，舵机电流会灌进 IO 脚，可能烧坏这个脚。"),
    "J_ARM_R": ("右臂舵机", "同左臂。"),
    "J_HEAT": ("加热膜（板外串 KSD9700 65℃ 常闭）",
               "**必须串 KSD9700**，丝印已标。1 脚是 USB 5V：**只有插着 3A 充电头、固件判定允许时才会加热**，"
               "电池供电时加热回路物理上无电。"),
    "J_NTC": ("加热测温 NTC 10K", "贴在加热膜上。与电池测温（板载 RT_BAT）是两颗。"),
    "J_TOUCH": ("头部触摸电极（导电布 / 铜箔）", "只接 1 脚（E0）。2 脚 GND 不用接。"),
    "J_KEY": ("外接按键 ×2：电源键、收音键", "两颗常开轻触按键，各一端接 PW / MU，另一端都接 G。"),
    "J_BAT": ("1S 锂电池 1500mAh（带保护板）",
              "**1 脚是 +**（丝印 +）。PH2.0 电池线各家极性不一，**插之前用万用表确认红线对 +**。"
              "板上有防反接，插反不会坏，但不会工作。"),
    "J_USB": ("USB-C：充电、烧录、日志", "要加热必须用 **5V/3A 的 C-C 充电头**；电脑口、A 转 C 线只充电不加热。"),
    "J_CAM": ("AFC01-S24FCA-00 摄像头",
              "**触点朝下**插入，镜头朝 PCB 外侧。PCB 焊盘号与摄像头脚号反序；"
              "必须先完成 CAMERA_VERIFICATION.md 中的实物门禁。"),
}

# footprint 关键字 → (座子型号, 配套线, 要不要自己接)
HOUSINGS = [
    ("JST_SH_SM08B", "SH1.0 8P 卧贴", "定制 Y 型线：SH1.0 8P → 2 个 2.54 8P 杜邦母头", "定制"),
    ("HC-1.0-6PWT", "SH1.0 6P 卧贴", "一期 `SH1.0 6P 转杜邦母头` 线", "插上即可"),
    ("JST_SH_SM02B", "SH1.0 2P 卧贴", "`SH1.0 2P 单头线`", "需接线"),
    ("ZX-SH1.0-3PWT", "SH1.0 3P 卧贴", "`SH1.0 3P 单头线`", "需接线"),
    ("ZX-XH2.54", "XH2.54 2P 卧贴（3A）", "`XH2.54 2P 单头线 22AWG`", "需接线"),
    ("PH2.0-2PWT", "PH2.0 2P 卧贴", "电池自带 PH2.0 插头", "插上即可"),
    ("HDR-SMD_3P", "2.54mm 贴片排针 1×3 卧式", "舵机自带三线母头", "插上即可"),
    ("USB_C_Receptacle", "USB-C 16P", "USB-C 数据线", "插上即可"),
    ("FPC-SMD_24P", "AFC01-S24FCA-00 24P 0.5mm 下接 FPC", "OV3660 摄像头自带排线", "门禁通过后插入"),
]

# 外购件：(件, 规格, 搜索关键词, 收货怎么验)。数量按一只玩偶算。
OFFBOARD = [
    ("锂电池 ×1", "1S 3.7V 1500mAh 锂聚合物，带保护板，PH2.0 2P 插头",
     "`3.7V 1500mAh 锂电池 PH2.0`",
     "**必须带保护板**。插头间距 2.0mm（PH），不是 1.25 也不是 2.54。收货先对着板上丝印比一下：红线要落在「+」那一侧，不对就别插，找卖家换。"
     "尺寸按玩偶肚子里的空间挑，常见 103450（10×34×50mm）。"),
    ("眼睛屏 ×2", "GC9A01 1.28\" 240×240 圆屏，**8 针带 BL**",
     "`GC9A01 1.28寸 圆屏 240x240 8针 SPI`",
     "一期两块可直接复用。新买时数排针必须 8 针，丝印 RST CS DC SDA SCL GND VCC BL。"),
    ("眼睛 Y 型线 ×1", "SH1.0 8P → 两个 2.54 8P 杜邦母头，8 根全部一分二",
     "`端子线定制`（把这一行发给卖家）",
     "**收货逐针量通**：板端第 k 针要同时通到两个母头的第 k 针，且相邻针不通。线长按眼睛位置量，≤ 10cm。"),
    ("麦克风 ×1", "I2S 数字麦克风模块", "（一期已有）", "一期 INMP441 与 SH1.0 6P 线一起复用。"),
    ("喇叭 ×1", "4Ω 或 8Ω，1–2W，带引线", "（一期已有）或 `4欧 2W 喇叭 带线`",
     "接下面的 SH1.0 2P 单头线（剪掉喇叭自带的插头）。低于 4Ω 不要买。"),
    ("舵机 ×2", "SG90 / MG90S 9g", "（一期已有）", "三线插头直插 ARM L / ARM R。"),
    ("加热膜 ×1", "5V 约 1A 硅胶加热片", "（一期已有）", "**5V 版本**。"),
    ("温控开关 ×1", "KSD9700 65℃ 常闭", "（一期已有）", "**常闭**，串在加热膜一根线上。没有它不要通电测加热。"),
    ("NTC ×1", "10kΩ B3950 带线探头", "（一期已有）", "常温约 10kΩ。"),
    ("触摸电极 ×1", "导电布或铜箔", "（一期已有）", "面积大一点灵敏度高。"),
    ("轻触按键 ×2", "常开，6×6mm 带线或面板按键",
     "`6x6 轻触开关 带线` 或 `12mm 自复位按钮`",
     "**要自复位（按下弹回）的**，不要自锁。一颗当电源键、一颗当收音键。"),
    ("SH1.0 单头线 2P ×3、3P ×1", "JST SH 1.0mm，一端插头一端裸线",
     "`SH1.0 2P 单头线` / `SH1.0 3P 单头线`",
     "2P 接 SPK、NTC、TOUCH，3P 接 KEY。**买「单头」不买「双头」**。很便宜，各买一包。"),
    ("XH2.54 单头线 2P ×1", "JST XH 2.54mm，一端插头一端裸线，**22AWG 或更粗**",
     "`XH2.54 2P 单头线 22AWG`",
     "只给加热膜用（1A）。长度 20–30cm，中间要剪开串 KSD9700。**一期的 VH3.96 线插不上**。"),
    ("C-C 充电头 ×1", "5V/3A（PD 充电头都支持）",
     "（手机快充头一般就行）",
     "**要加热就必须用它 + C-C 线**。头上写 5V⎓3A 才行。A 口充电头、电脑口固件会拒绝加热。"),
    ("USB-C 数据线", "C-C 能传数据", "（家里有就行）", "烧录用电脑；必须是数据线。"),
    ("热缩管", "φ1–3mm 混装", "（一期已有）", "所有线对线焊点都要套，加热回路尤其不能裸露。"),
]


def describe(ctx, net: str, seen: frozenset[str] = frozenset()) -> str:
    """把出线座上的网络名翻译成「它到底连到哪」：GPIO、电源，或经串联电阻追到的那一头。"""
    net_gpio = {name: number for number, name in gpio.for_family(ctx.variant.camera).items()}
    if net.startswith("NC_") or net.startswith("unconnected"):
        return "悬空"
    if net in NET_NOTES:
        return NET_NOTES[net]
    if net == "HEAT_LOW":
        control = "MPR121 GPIO 功能" if ctx.variant.camera else "GPIO17"
        return f"Q_HEAT 漏极（低边开关，{control} 控制）"
    if net in net_gpio:
        return f"GPIO{net_gpio[net]}"
    if net in POWER_NETS:
        return POWER_NETS[net]
    owners = [(p, n) for p in ctx.parts for n, name in p.pins.items() if name == net]
    for p, number in owners:
        if p.ref.startswith(("U", "Q")) and p.ref != "U1":
            return f"{p.ref} {p.value} 第 {number} 脚"
    seen = seen | {net}
    for p, number in owners:
        if p.symbol != "Device:R" or len(p.pins) != 2:
            continue
        other = next(name for pin, name in p.pins.items() if pin != number)
        if other in seen:
            continue
        resolved = describe(ctx, other, seen)
        if resolved != "—":
            return f"{resolved}（经 {p.ref} {p.value}Ω）"
    return "—"


def housing(ctx, ref: str) -> tuple[str, str, str]:
    footprint = part(ctx, ref).footprint
    for key, name, cable, effort in HOUSINGS:
        if key in footprint:
            return name, cable, effort
    raise SystemExit(f"{ref} 的 footprint {footprint} 没有对应的座子型号，补进 HOUSINGS")


def part(ctx, ref: str):
    return next(p for p in ctx.parts if p.ref == ref)


def connector_table(ctx, ref: str) -> list[str]:
    spec = part(ctx, ref)
    what, caution = CONNECTORS[ref]
    name, cable, effort = housing(ctx, ref)
    legend = ctx.placement.PIN_LEGEND.get(ref, [])
    lines = [f"### {ref} — {what}", "", f"**座子**：{name} ｜ **配套线**：{cable} ｜ {effort}", ""]
    if caution:
        lines += [f"> {caution}", ""]
    if ref == "J_USB":
        return lines
    if ref == "J_CAM":
        lines += ["| PCB 焊盘 | 摄像头脚 | 网络 | 连到 |", "|---|---|---|---|"]
        for pad in range(1, 25):
            camera_pin = cam.CAMERA_PAD_TO_PIN[str(pad)]
            net = spec.pins[str(pad)]
            lines.append(f"| PCB 焊盘 {pad} | 摄像头第 {camera_pin} 脚 | `{net}` | {describe(ctx, net)} |")
        lines.append("")
        return lines
    lines += ["| 针号 | 丝印 | 网络 | 连到 |", "|---|---|---|---|"]
    numbered = sorted((int(n), net) for n, net in spec.pins.items() if n.isdigit())
    for number, net in numbered:
        if net.startswith("NC_"):
            continue      # 固定焊盘
        mark = legend[number - 1] if number <= len(legend) else ""
        lines.append(f"| {number} | {mark} | `{net}` | {describe(ctx, net)} |")
    lines.append("")
    return lines


def render(ctx) -> str:
    v = ctx.variant.name
    lines = [
        f"# 二期版本 {v} 接线表与外购清单",
        "",
        "**本文件由 `scripts/export_wiring.py` 从 `scripts/v2/` 生成，不要手工编辑。**",
        "板子改了就重跑 `python3 export_wiring.py --variant " + v + "`。",
        "",
        "板上全部是贴片插座，**不需要在板上焊任何东西**。需要动烙铁的只有板外：",
        "裸线器件（加热膜 + KSD9700、NTC、触摸电极、按键、不带插头的喇叭）接到单头线的裸线端。",
        "",
    ]
    if ctx.variant.camera:
        lines += ["> **当前禁止下单：** 必须先完成 [CAMERA_VERIFICATION.md](CAMERA_VERIFICATION.md) 的 spec §7.3 实物方向核验。",
                  "> 首板到货后，spec §7.4 断电测量通过前仍 **禁止接摄像头上电**。", ""]
    lines += ["## 一、出线座逐针表", ""]
    connector_refs = [ref for ref in CONNECTORS if any(p.ref == ref for p in ctx.parts)]
    for ref in connector_refs:
        lines += connector_table(ctx, ref)
    lines += ["---", "", "## 二、每个座子配什么线", "",
              "| 座子 | 接什么 | 座子型号 | 配套线 | 要不要自己接 |", "|---|---|---|---|---|"]
    for ref in connector_refs:
        what, _ = CONNECTORS[ref]
        name, cable, effort = housing(ctx, ref)
        lines.append(f"| {ref} | {what.split('（')[0]} | {name} | {cable} | {effort} |")
    lines += ["", "**线材不通用**：SH1.0、XH2.54、PH2.0 间距都不同，插不进去时先看间距，别硬插。",
              "", "---", "", "## 三、外购清单", "",
              "板上不贴、装玩偶时另外准备的东西。标「一期已有」的直接复用。**给的是搜索关键词不是链接**，",
              "「收货怎么验」那一列才是防止买错的东西。", "",
              "| 件 | 规格 | 搜索关键词 | 收货怎么验 | 已备 |", "|---|---|---|---|---|"]
    for name, spec, keyword, check in OFFBOARD:
        lines.append(f"| {name} | {spec} | {keyword} | {check} | ☐ |")
    if ctx.variant.camera:
        lines.append("| 摄像头 ×1 | AFC01-S24FCA-00 / OV3660，24P 0.5mm 排线 | `AFC01-S24FCA-00 OV3660` | "
                     "排线触点朝下；先按 CAMERA_VERIFICATION.md 留存实物照片并核对 1/24 脚，门禁未通过不得下单。 | ☐ |")
    lines += ["", "---", "", "## 四、接完之后", "",
              "针序对上了只说明线接的是你想接的东西。上电顺序与每一步的通过标准见 [TESTING.md](TESTING.md)。", ""]
    return "\n".join(lines)


def main() -> None:
    ctx = context.from_argv()
    destination = ctx.dir / "WIRING.md"
    destination.write_text(render(ctx), encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
