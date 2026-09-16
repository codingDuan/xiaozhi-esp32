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
              "排线从板子下边插入，金手指朝向按 FPC 座下接触式。"),
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
    lines = [f"### {ref} — {module}", ""]
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

    lines += ["", "---", "",
              "## 三、核完之后",
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
