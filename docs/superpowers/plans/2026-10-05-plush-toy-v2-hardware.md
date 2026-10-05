# 毛绒玩具主板二期（版本 A）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 产出二期版本 A（不带摄像头 · 单面贴片）的可下单生产文件，并把四个版本共用的「电路即代码」骨架、版本差异机制与自动检查一次建好，使 B/C/D 只需追加差异与布局。

**Architecture:** 新目录 `hardware/plush-toy-v2-mainboard`。电路描述拆成「器件库 `parts_db` → 共用核心 `core` → 版本差异 `nocam` / `cam` → 版本组合 `variants`」四层，所有生成脚本通过 `context.load(variant)` 拿到当前版本的器件、网络与文件路径，不再在模块顶层写死。流程沿用一期：原理图 → 布局 → 扇出 → Freerouting → 布线后修补 → DRC → 导出。

**Tech Stack:** Python 3（主机测试）、KiCad 10 自带 Python（`pcbnew`）、kicad-cli、Freerouting 2.4.1（Java 25+）、unittest。

**Spec:** `docs/superpowers/specs/2026-10-05-plush-toy-v2-hardware-design.md`

## Global Constraints

- 一期目录 `hardware/plush-toy-mainboard` **只读**：不改其脚本、不改其 `board_spec.py`（该板已生产）。需要的代码复制到二期目录后再改。
- 所有元件除测试点与安装孔外必须 `assembly=True` 且有立创料号（spec 1 节标准 1）。
- 加热只接 USB 5V（eFuse 之后、IP5306 之前），与系统 5V、VBAT 无任何铜连接（spec 3.2）。
- 加热栅极 100kΩ 下拉必贴（spec 3.2）。
- GPIO 分配必须与 spec 第 5 节表格逐项一致；35/36/37 不得使用；19/20 只给 USB。
- 保留自恢复保险丝 + eFuse TPS259531（C2155674）（spec 3.1）。
- 四层板 1.6mm，叠层与一期相同（JLC04161H-7628）。
- KiCad 独立 `board.Save()` 会把 `.kicad_pro` 覆盖成默认规则，保存后必须调用 `project_rules.apply()`。
- **没有重新灌铜的 DRC 结果一律不可信**（见 `.claude/skills/pcb-check/SKILL.md`）。
- 内层 In1/In2 必须设为 `LT_POWER`，否则 Freerouting 会在平面层走线。
- 生成 PCB 先写临时文件再替换，防止生成失败抹掉现有板。
- 提交信息结尾附 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。

## Review Focus

1. **插着 USB 时电池反接**：期望任何器件不损坏。→ Task 2 的评审文档必须给出该工况下每个器件两端电压；Task 4 的 `test_battery_reverse_path_blocked` 断言电池正极到 VBAT 节点之间存在 Task 2 选定的保护器件。
2. **A 转 C 线 + 2A 充电头**：期望判定为「默认电流」、不加热。→ Task 4 的 `test_cc_divider_halves_three_amp_level` 用分压比计算三档阈值并断言 3A 档与 1.5A 档的节点电压差 ≥ 0.25V（ADC 能可靠分辨）。
3. **启动瞬间 GPIO46 / GPIO3 上的舵机信号**：期望不误入下载模式、舵机不乱动。→ Task 5 的 `test_strapping_pins_have_safe_defaults` 断言 GPIO46 有下拉、GPIO0 有上拉、两者均无上拉冲突。
4. **加热座两根线被压破短路**：期望 5V 不进入 ADC。→ Task 4 的 `test_heater_and_ntc_on_separate_connectors` 断言 HEAT 座与 NTC 座不是同一器件，且 NTC 座上没有 5V 网络。
5. **KEY / TOUCH 线上的静电**：期望 ESP32 与 IP5306 引脚不被击穿。→ Task 5 的 `test_external_lines_have_esd` 断言 TOUCH、KEY 座每根信号脚所在网络上都挂有一颗 ESD 器件。

---

## 文件结构

```
hardware/plush-toy-v2-mainboard/
  README.md                  目录说明、命令、版本状态表
  SELECTION.md               Task 1/2 选型记录（料号、手册出处、核对结论）
  BATTERY_PROTECTION.md      Task 2 电池防反接方案与评审
  lib/                       二期专用符号 / 封装（easyeda2kicad 生成或手写）
  scripts/
    v2/__init__.py
    v2/part.py               Part 数据类与 res/cap/testpoint/nc 辅助函数
    v2/parts_db.py           料号、封装、语义引脚 → 焊盘号（唯一含手册引脚号的文件）
    v2/gpio.py               spec 第 5 节 GPIO 表（共用 / 不带摄像头 / 带摄像头）
    v2/core.py               四版本共用电路：电源、电池、ESP32、音频、眼睛、舵机、加热功率级、IMU、按键、测试点
    v2/nocam.py              A/B 差异：片上触摸、片上 ADC 分压、加热栅极与收音键直连 GPIO
    v2/cam.py                C/D 差异（后续计划实现，本计划只建空壳与映射断言测试的框架）
    v2/variants.py           VARIANTS 表、parts(variant)、nets(variant)
    context.py               load(variant) → 路径、器件、网络、placement 模块
    kicad_env.py             复制自一期，PROJECT_DIR 指向二期
    project_rules.py         复制自一期，按变体写 .kicad_pro
    gen_schematic.py         复制自一期，改为 --variant
    gen_pcb.py               复制自一期，改为 --variant，读 placement_<v>.py
    placement_A.py           版本 A 板框、定点与 NEAR 规则
    fanout.py / route.py     复制自一期，改为 --variant
    post_route.py            二期精简版：只做灌铜、DRC、非回退判定
    export_bom.py / fab_tools.py / export_fab.sh / export_wiring.py   复制并参数化
    test_parts_db.py test_gpio.py test_core.py test_variants.py
    test_pcb_A.py test_drc_A.py test_export.py
  variants/A/                plush-toy-v2-A.kicad_sch/.kicad_pcb/.kicad_pro、fab/、WIRING.md、TESTING.md
```

---

## 阶段 0：选型

### Task 1: 器件选型定稿与 `parts_db`

**Files:**
- Create: `hardware/plush-toy-v2-mainboard/SELECTION.md`
- Create: `hardware/plush-toy-v2-mainboard/scripts/v2/__init__.py`（空文件）
- Create: `hardware/plush-toy-v2-mainboard/scripts/v2/part.py`
- Create: `hardware/plush-toy-v2-mainboard/scripts/v2/parts_db.py`
- Create: `hardware/plush-toy-v2-mainboard/scripts/kicad_env.py`
- Test: `hardware/plush-toy-v2-mainboard/scripts/test_parts_db.py`

**Interfaces:**
- Produces: `v2.part.Part`、`res()`、`cap()`、`testpoint()`、`nc()`（签名同一期 `board_spec.py`）；`v2.parts_db.DB: dict[str, Entry]`，`Entry(lcsc: str, symbol: str, footprint: str, pads: dict[str, str])`，`pads` 为「语义名 → 焊盘号」；`v2.parts_db.part(key, ref, nets: dict[语义名, 网络]) -> Part`。

- [ ] **Step 1: 建目录并复制 Part 模型**

```bash
mkdir -p hardware/plush-toy-v2-mainboard/scripts/v2 hardware/plush-toy-v2-mainboard/lib hardware/plush-toy-v2-mainboard/variants/A
touch hardware/plush-toy-v2-mainboard/scripts/v2/__init__.py
cp hardware/plush-toy-mainboard/scripts/kicad_env.py hardware/plush-toy-v2-mainboard/scripts/kicad_env.py
```

`kicad_env.py` 里 `PROJECT_LIBS = {"plush", "lcsc"}` 改为 `PROJECT_LIBS = {"plushv2"}`，其余不动。

`v2/part.py`：

```python
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
```

- [ ] **Step 2: 写 parts_db 的失败测试**

`scripts/test_parts_db.py`：

```python
import unittest

from v2 import parts_db

REQUIRED = {
    # 键 → 必须存在的语义引脚
    "WROOM": {"GND", "3V3", "EN"},
    "IP5306_I2C": {"VIN", "VOUT", "BAT", "SW", "KEY", "SCL", "SDA", "GND"},
    "TPS259531": {"IN", "OUT", "ILM", "DVDT", "GND"},
    "SY8089": {"IN", "EN", "SW", "FB", "GND"},
    "NS4168": {"VDD", "GND", "BCLK", "LRCLK", "SDATA", "CTRL", "OUTP", "OUTN"},
    "LIS2DH12": {"VDD", "VDD_IO", "GND", "SCL", "SDA", "SDO_SA0", "CS"},
    "AO3400A": {"G", "S", "D"},
    "USB_C16": {"VBUS", "GND", "CC1", "CC2", "DP1", "DN1", "DP2", "DN2", "SHIELD"},
    "PTC_USB": {"1", "2"},
    "ESD_LINE": {"IO", "GND"},
    "CONN_BAT": {"+", "-"},
    "CONN_LCD8": {str(i) for i in range(1, 9)},
    "CONN_MIC6": {str(i) for i in range(1, 7)},
    "CONN_SPK2": {"1", "2"},
    "CONN_HEAT2": {"1", "2"},
    "CONN_SH2": {"1", "2"},
    "CONN_KEY3": {"1", "2", "3"},
    "HDR_SERVO3": {"1", "2", "3"},
    "SW_TACT": {"A", "B"},
    "LED_0603": {"A", "K"},
    "INDUCTOR_BOOST": {"1", "2"},
    "INDUCTOR_BUCK": {"1", "2"},
}


class PartsDbTests(unittest.TestCase):
    def test_every_required_key_present(self):
        self.assertEqual(set(REQUIRED) - set(parts_db.DB), set())

    def test_every_entry_has_lcsc_symbol_footprint(self):
        for key, entry in parts_db.DB.items():
            with self.subTest(key=key):
                self.assertRegex(entry.lcsc, r"^C\d+$")
                self.assertIn(":", entry.symbol)
                self.assertIn(":", entry.footprint)

    def test_required_semantic_pins_mapped(self):
        for key, names in REQUIRED.items():
            with self.subTest(key=key):
                self.assertEqual(names - set(parts_db.DB[key].pads), set())

    def test_part_helper_rejects_unknown_semantic_pin(self):
        with self.assertRaises(KeyError):
            parts_db.part("AO3400A", "Q_X", {"G": "A", "S": "B", "DRAIN": "C"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 运行，确认失败**

Run: `cd hardware/plush-toy-v2-mainboard/scripts && python3 -m unittest test_parts_db -v`
Expected: FAIL / ERROR，`ImportError: cannot import name 'parts_db'`

- [ ] **Step 4: 逐项选型并写 `SELECTION.md` 与 `parts_db.py`**

每个器件的选型流程（不得跳过任一步）：
1. 在立创商城产品页（`https://www.lcsc.com/product-detail/C<编号>.html`）确认型号、封装、库存 ≥ 50、10 片价。
2. 打开该页的数据手册 PDF，抄下引脚表，写进 `SELECTION.md`（注明手册版本与页码）。
3. 封装：优先 KiCad 官方库；没有就用 `easyeda2kicad --full --lcsc_id=C<编号> --output hardware/plush-toy-v2-mainboard/lib/plushv2` 生成，并核对焊盘数与手册一致。
4. 在 `parts_db.py` 写 `Entry`，`pads` 的焊盘号逐个对照第 2 步的引脚表。

已知料号（一期或 spec 已核对，仍需第 1 步确认库存）：WROOM C2913202、TPS259531 C2155674、SY8089 C78988、AO3400A C20917、NS4168 C910588、LIS2DH12 C110926、ME6211C28 C53099、ME6211C15 C53100、LESD8D3.3CAT5G C172409、BSMD1206-150-6V C883132、AFC01-S24FCA-00 C262669。

需要新选的，验收条件按 spec 第 10 节：

| 键 | 验收条件 |
|---|---|
| IP5306_I2C | 手册写明可经 I2C 关闭轻载关机、设置充电电流、关闭充电；关机电流 < 50µA；记录三个寄存器地址与位 |
| USB_C16 | 16P、贴片、外形小于 HRO TYPE-C-31-M-12（10.7×9.5mm 庭院）、嘉立创可贴 |
| CONN_LCD8 / CONN_MIC6 / CONN_SH2 / CONN_KEY3 | SH1.0 卧贴，与一期 J_MIC 同系列 |
| CONN_SPK2 | MX1.25 2P 卧贴 |
| CONN_HEAT2 | XH2.54 2P 卧贴，额定 ≥ 3A |
| CONN_BAT | PH2.0 2P 卧贴 |
| HDR_SERVO3 | 2.54mm 贴片排针 1×3，带定位柱 |
| SW_TACT | 3×4mm 贴片轻触开关 |
| INDUCTOR_BOOST | IP5306 手册推荐值，饱和电流 ≥ 3A |
| NS4168 CTRL | 手册中「左声道」对应的 CTRL 电压窗口；记录在 SELECTION.md。若 VSYS/2（约 2.5V）不在窗口内，Task 5 改 `R_AMP_CTRL_TOP/BOT` 阻值使其落在窗口中央 |
| IP5306_I2C 指示灯 | 记录芯片是否有充电 / 充满指示灯驱动脚。**没有**：Task 5 删除 `LED_CHG`、`LED_FULL` 及其电阻，并在 spec 第 4 节记一条修订（状态改由固件经 I2C 读取、用眼睛屏显示），提交前告知委托方 |
| ESD_LINE | 单路 ESD，工作电压 ≥ 3.3V（KEY/TOUCH 用） |

`parts_db.py` 结构（每条 `Entry` 按第 4 步填写；下面给出两条已核对的示例，其余照此格式）：

```python
"""二期器件库：料号、封装、语义引脚 → 焊盘号。全项目只有这里出现手册引脚号。
每条的出处写在 SELECTION.md 对应小节。"""
from dataclasses import dataclass

from v2.part import Part


@dataclass(frozen=True)
class Entry:
    lcsc: str
    symbol: str
    footprint: str
    pads: dict[str, str]
    value: str = ""


DB: dict[str, Entry] = {
    # SELECTION.md §AO3400A：SOT-23，1=G 2=S 3=D（一期 board_spec 已用同一映射）
    "AO3400A": Entry("C20917", "Transistor_FET:AO3400A", "Package_TO_SOT_SMD:SOT-23",
                     {"G": "1", "S": "2", "D": "3"}, "AO3400A"),
    # SELECTION.md §TPS259531：WSON-8，与一期 U_EFUSE 同映射
    "TPS259531": Entry("C2155674", "plushv2:TPS259531",
                       "Package_SON:Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm_ThermalVias",
                       {"DVDT": "1", "OUT": "2", "OUT2": "3", "OUT3": "4", "IN": "5",
                        "FLT": "6", "ILM": "7", "GND": "8", "EP": "9"}, "TPS259531DSGR"),
}


def part(key: str, ref: str, nets: dict[str, str]) -> Part:
    """按语义名连线；未列出的焊盘标为不连接。语义名写错立即 KeyError。"""
    entry = DB[key]
    unknown = set(nets) - set(entry.pads)
    if unknown:
        raise KeyError(f"{key} 没有语义引脚 {sorted(unknown)}")
    pins = {pad: f"NC_{ref}_{pad}" for pad in entry.pads.values()}
    for name, net in nets.items():
        pins[entry.pads[name]] = net
    return Part(ref, entry.value or key, entry.symbol, entry.footprint, entry.lcsc, True, pins)
```

一期 `TPS259531` 的 2/3/4 脚同为输出、8/9 脚同为地：`part()` 调用方必须把 `OUT/OUT2/OUT3` 都连到同一网络，Task 4 的测试会检查。

- [ ] **Step 5: 运行，确认通过**

Run: `cd hardware/plush-toy-v2-mainboard/scripts && python3 -m unittest test_parts_db -v`
Expected: 4 tests OK

- [ ] **Step 6: 用 KiCad 校验封装焊盘数（复用一期 test_part_pins 思路）**

在 `test_parts_db.py` 追加（KiCad Python 运行）：

```python
class FootprintPadTests(unittest.TestCase):
    def test_semantic_pads_exist_in_footprint(self):
        try:
            import pcbnew
        except ImportError:
            self.skipTest("需用 KiCad 自带 Python 运行")
        import kicad_env
        for key, entry in parts_db.DB.items():
            lib, name = entry.footprint.split(":", 1)
            fp = pcbnew.FootprintLoad(str(kicad_env.footprint_dir(lib)), name)
            with self.subTest(key=key):
                self.assertIsNotNone(fp, entry.footprint)
                pads = {p.GetNumber() for p in fp.Pads()}
                self.assertEqual(set(entry.pads.values()) - pads, set())
```

Run: `/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_parts_db -v`
Expected: 5 tests OK

- [ ] **Step 7: Commit**

```bash
git add hardware/plush-toy-v2-mainboard
git commit -m "feat(pcb-v2): 器件选型定稿与 parts_db"
```

### Task 2: 电池防反接方案（需委托方确认）

**Files:**
- Create: `hardware/plush-toy-v2-mainboard/BATTERY_PROTECTION.md`
- Modify: `hardware/plush-toy-v2-mainboard/scripts/v2/parts_db.py`（加入选定的保护器件）

**Interfaces:**
- Produces: `parts_db.DB["BAT_PROTECT"]`，语义引脚由方案决定，在文档中列出；Task 4 按文档连线。

- [ ] **Step 1: 写评审文档**

`BATTERY_PROTECTION.md` 必须包含：
1. 至少两个候选电路（例如：低边 N-MOS 栅极接 VBAT 侧、专用理想二极管 / 反接保护芯片、串联自恢复保险丝 + 反向钳位），每个画出电路。
2. 对每个候选，列四种工况下每个器件两端电压与是否导通：电池正接 / 反接 × 插 USB / 不插 USB。
3. 明确指出「简单高边 P-MOS（栅极接地）在插 USB 时会被充电器打开、给反接电池充电」，说明选定方案为何不受影响。
4. 选定方案的料号、压降、对续航的影响（按 0.9W 平均负载算）。

- [ ] **Step 2: 交委托方确认**

把文档链接发给委托方，等待明确同意后再继续。未同意不得进入 Task 4。

- [ ] **Step 3: 写入 parts_db 并运行测试**

在 `REQUIRED` 加入 `"BAT_PROTECT": {选定方案的语义引脚}`，在 `DB` 加入条目。
Run: `python3 -m unittest test_parts_db -v`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add hardware/plush-toy-v2-mainboard/BATTERY_PROTECTION.md hardware/plush-toy-v2-mainboard/scripts
git commit -m "feat(pcb-v2): 电池防反接方案"
```

---

## 阶段 1：电路即代码

### Task 3: GPIO 表

**Files:**
- Create: `hardware/plush-toy-v2-mainboard/scripts/v2/gpio.py`
- Test: `hardware/plush-toy-v2-mainboard/scripts/test_gpio.py`

**Interfaces:**
- Produces: `gpio.COMMON: dict[int, str]`、`gpio.NOCAM: dict[int, str]`、`gpio.CAM: dict[int, str]`、`gpio.for_family(camera: bool) -> dict[int, str]`（GPIO → 网络名）；`gpio.WROOM_PAD_GPIO`（模组焊盘 → GPIO，抄自一期 `_WROOM_PAD_GPIO`）。

- [ ] **Step 1: 写失败测试**

```python
import unittest

from v2 import gpio

USABLE = set(range(0, 19)) | {21} | set(range(38, 49))


class GpioTests(unittest.TestCase):
    def test_spec_table_common(self):
        expected = {0: "BOOT", 38: "LCD_CLK", 14: "LCD_MOSI", 47: "LCD_DC", 45: "LCD_CS",
                    21: "LCD_RST", 48: "LCD_BL_PWM", 1: "MIC_WS", 2: "MIC_SCK", 42: "MIC_SD",
                    39: "AMP_DIN", 40: "AMP_BCLK", 41: "AMP_LRCLK", 43: "I2C_SCL", 44: "I2C_SDA",
                    3: "SERVO_L_PWM", 46: "SERVO_R_PWM", 19: "USB_DN", 20: "USB_DP"}
        self.assertEqual(gpio.COMMON, expected)

    def test_spec_table_nocam(self):
        self.assertEqual(gpio.NOCAM, {17: "HEAT_GATE_DRV", 18: "KEY_MUTE", 8: "TOUCH_E0",
                                      4: "NTC_SENSE", 5: "VBAT_SENSE", 6: "CC_SENSE", 7: "BAT_NTC_SENSE"})

    def test_spec_table_cam(self):
        self.assertEqual(gpio.CAM, {4: "CAM_SIOD", 5: "CAM_SIOC", 6: "CAM_VSYNC", 7: "CAM_HREF",
                                    15: "CAM_XCLK", 13: "CAM_PCLK", 11: "CAM_Y2", 9: "CAM_Y3",
                                    8: "CAM_Y4", 10: "CAM_Y5", 12: "CAM_Y6", 18: "CAM_Y7",
                                    17: "CAM_Y8", 16: "CAM_Y9"})

    def test_no_conflicts_and_only_usable_pins(self):
        for camera in (False, True):
            with self.subTest(camera=camera):
                table = gpio.for_family(camera)
                extra = gpio.CAM if camera else gpio.NOCAM
                self.assertEqual(set(gpio.COMMON) & set(extra), set())
                self.assertLessEqual(set(table) - {19, 20}, USABLE)
                self.assertEqual(len(set(table.values())), len(table))

    def test_camera_family_uses_every_usable_gpio(self):
        self.assertEqual(set(gpio.for_family(True)) - {19, 20}, USABLE)

    def test_psram_pins_never_assigned(self):
        for camera in (False, True):
            self.assertEqual(set(gpio.for_family(camera)) & {35, 36, 37}, set())

    def test_wroom_pad_table_covers_all_used_gpio(self):
        for camera in (False, True):
            self.assertLessEqual(set(gpio.for_family(camera)), set(gpio.WROOM_PAD_GPIO.values()))


if __name__ == "__main__":
    unittest.main()
```

`test_strapping_pins_have_safe_defaults`（Review Focus 第 3 条）需要器件信息，在 Task 5。

- [ ] **Step 2: 运行，确认失败**

Run: `python3 -m unittest test_gpio -v`
Expected: ERROR，`ImportError: cannot import name 'gpio'`

- [ ] **Step 3: 实现**

```python
"""spec 第 5 节 GPIO 表。固件 plush-toy-v2 的 config.h 以此为准。"""

COMMON = {
    0: "BOOT",
    38: "LCD_CLK", 14: "LCD_MOSI", 47: "LCD_DC", 45: "LCD_CS", 21: "LCD_RST", 48: "LCD_BL_PWM",
    1: "MIC_WS", 2: "MIC_SCK", 42: "MIC_SD",
    39: "AMP_DIN", 40: "AMP_BCLK", 41: "AMP_LRCLK",
    # 一期 SCL 在 GPIO3；二期挪到 43：ROM 启动日志只动 SCL，SDA 保持高，不构成起始条件
    43: "I2C_SCL", 44: "I2C_SDA",
    3: "SERVO_L_PWM", 46: "SERVO_R_PWM",
    19: "USB_DN", 20: "USB_DP",
}

NOCAM = {
    17: "HEAT_GATE_DRV", 18: "KEY_MUTE", 8: "TOUCH_E0",
    4: "NTC_SENSE", 5: "VBAT_SENSE", 6: "CC_SENSE", 7: "BAT_NTC_SENSE",
}

CAM = {
    4: "CAM_SIOD", 5: "CAM_SIOC", 6: "CAM_VSYNC", 7: "CAM_HREF", 15: "CAM_XCLK", 13: "CAM_PCLK",
    11: "CAM_Y2", 9: "CAM_Y3", 8: "CAM_Y4", 10: "CAM_Y5", 12: "CAM_Y6", 18: "CAM_Y7",
    17: "CAM_Y8", 16: "CAM_Y9",
}

# ESP32-S3-WROOM-1 模组焊盘号 → GPIO，出自 esp32-s3-wroom-1_wroom-1u_datasheet_en v1.8 表 3-1
WROOM_PAD_GPIO = {
    "4": 4, "5": 5, "6": 6, "7": 7, "8": 15, "9": 16, "10": 17, "11": 18, "12": 8,
    "13": 19, "14": 20, "15": 3, "16": 46, "17": 9, "18": 10, "19": 11, "20": 12,
    "21": 13, "22": 14, "23": 21, "24": 47, "25": 48, "26": 45, "27": 0,
    "31": 38, "32": 39, "33": 40, "34": 41, "35": 42, "36": 44, "37": 43, "38": 2, "39": 1,
}


def for_family(camera: bool) -> dict[int, str]:
    table = dict(COMMON)
    table.update(CAM if camera else NOCAM)
    return table
```

注：spec 5.1 写的是 CAM_Y 按「D0–D7」列出，此处沿用一期 `config.h` 的 Y2–Y9 命名（D0=Y2 … D7=Y9），映射与 spec 表 11/9/8/10/12/18/17/16 一致。

- [ ] **Step 4: 运行，确认通过**

Run: `python3 -m unittest test_gpio -v`
Expected: 7 tests OK

- [ ] **Step 5: Commit**

```bash
git add hardware/plush-toy-v2-mainboard/scripts/v2/gpio.py hardware/plush-toy-v2-mainboard/scripts/test_gpio.py
git commit -m "feat(pcb-v2): GPIO 表与冲突检查"
```

### Task 4: 共用核心之电源

**Files:**
- Create: `hardware/plush-toy-v2-mainboard/scripts/v2/core.py`（本任务只写 `power_parts()`）
- Test: `hardware/plush-toy-v2-mainboard/scripts/test_core.py`

**Interfaces:**
- Consumes: `parts_db.part()`、`part.res/cap/cap10u/cap22u/testpoint`、`DB["BAT_PROTECT"]`（Task 2）。
- Produces: `core.power_parts() -> list[Part]`。网络名约定（后续任务依赖）：`VBUS_IN`（USB 座）、`VBUS_FUSED`（保险丝后）、`VUSB`（eFuse 后）、`VBAT_PACK`（电池座正极）、`VBAT`（保护后）、`VSYS`（IP5306 升压输出 5V）、`+3V3`、`HEAT_LOW`、`HEAT_GATE`、`HEAT_GATE_DRV`、`CC1`、`CC2`、`CC_SENSE`、`VBAT_SENSE`、`BAT_NTC_SENSE`、`KEY_PWR`、`GND`。

- [ ] **Step 1: 写失败测试**

```python
import unittest

from v2 import core


def nets_of(parts):
    result = {}
    for p in parts:
        for pin, net in p.pins.items():
            result.setdefault(net, []).append((p.ref, pin))
    return result


def refs_on(parts, net):
    return {ref for ref, _ in nets_of(parts).get(net, [])}


class PowerTests(unittest.TestCase):
    parts = core.power_parts()

    def test_heater_fed_only_from_vusb(self):
        heat = next(p for p in self.parts if p.ref == "J_HEAT")
        self.assertIn("VUSB", heat.pins.values())
        self.assertNotIn("VSYS", heat.pins.values())
        self.assertNotIn("VBAT", heat.pins.values())

    def test_no_part_bridges_vusb_and_vsys_except_charger(self):
        bridges = {p.ref for p in self.parts
                   if {"VUSB", "VSYS"} <= set(p.pins.values())}
        self.assertEqual(bridges, {"U_CHG"})

    def test_efuse_between_fuse_and_loads(self):
        self.assertEqual(refs_on(self.parts, "VBUS_FUSED") - {"F_USB", "U_EFUSE", "C_EFUSE_IN"}, set())
        efuse = next(p for p in self.parts if p.ref == "U_EFUSE")
        outs = {efuse.pins[pad] for pad in ("2", "3", "4")}
        self.assertEqual(outs, {"VUSB"})

    def test_heater_gate_pulldown(self):
        pd = next(p for p in self.parts if p.ref == "R_GATE_PD")
        self.assertEqual(set(pd.pins.values()), {"HEAT_GATE", "GND"})
        self.assertEqual(pd.value, "100k")

    def test_heater_and_ntc_on_separate_connectors(self):
        ntc = next(p for p in self.parts if p.ref == "J_NTC")
        heat = next(p for p in self.parts if p.ref == "J_HEAT")
        self.assertIsNot(ntc, heat)
        self.assertNotIn("VUSB", ntc.pins.values())
        self.assertNotIn("VSYS", ntc.pins.values())

    def test_cc_divider_halves_three_amp_level(self):
        # CC1、CC2 各经 R_CC_SUM1/2 汇到 CC_SENSE；未连接的一路被 5.1k Rd 拉到地
        r_sum = 100e3
        rd = 5.1e3
        def node(rp):
            v_cc = 5.0 * rd / (rp + rd)
            return v_cc / 2
        default, a15, a30 = node(56e3), node(22e3), node(10e3)
        self.assertGreaterEqual(a30 - a15, 0.25)
        self.assertGreaterEqual(a15 - default, 0.2)
        for ref in ("R_CC_SUM1", "R_CC_SUM2"):
            p = next(x for x in self.parts if x.ref == ref)
            self.assertEqual(p.value, "100k")
            self.assertIn("CC_SENSE", p.pins.values())
        self.assertEqual({p.value for p in self.parts if p.ref in ("R_CC1", "R_CC2")}, {"5.1k"})

    def test_battery_reverse_path_blocked(self):
        self.assertIn("U_BATPROT", refs_on(self.parts, "VBAT_PACK"))
        self.assertNotIn("U_CHG", refs_on(self.parts, "VBAT_PACK"))
        self.assertIn("U_CHG", refs_on(self.parts, "VBAT"))

    def test_charger_power_key_on_connector(self):
        self.assertIn("U_CHG", refs_on(self.parts, "KEY_PWR"))
        self.assertIn("J_KEY", refs_on(self.parts, "KEY_PWR"))

    def test_vbat_sense_divider_stays_below_adc_range(self):
        top = next(p for p in self.parts if p.ref == "R_VBAT_TOP")
        bot = next(p for p in self.parts if p.ref == "R_VBAT_BOT")
        ratio = 1e3 / (1e3 + 1e3)  # 两颗等值电阻，4.2V → 2.1V，低于 ESP32 ADC 11dB 量程 3.1V
        self.assertEqual(top.value, bot.value)
        self.assertAlmostEqual(4.2 * ratio, 2.1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行，确认失败**

Run: `python3 -m unittest test_core -v`
Expected: ERROR，`ImportError: cannot import name 'core'`

- [ ] **Step 3: 实现 `power_parts()`**

```python
"""四个版本共用的电路。只写连接，料号与焊盘号全部来自 parts_db。"""
from v2 import parts_db as db
from v2.part import cap, cap10u, cap22u, res, testpoint


def power_parts() -> list:
    return [
        # ── USB 入口：保险丝 → eFuse → VUSB（spec 3.1）──
        db.part("USB_C16", "J_USB", {"VBUS": "VBUS_IN", "GND": "GND", "SHIELD": "GND",
                                     "CC1": "CC1", "CC2": "CC2",
                                     "DP1": "USB_DP", "DP2": "USB_DP", "DN1": "USB_DN", "DN2": "USB_DN"}),
        res("R_CC1", "5.1k", "CC1", "GND"),
        res("R_CC2", "5.1k", "CC2", "GND"),
        # CC 电压汇总到一个 ADC 节点：节点 ≈ 有效 CC 的一半（spec 3.2）
        res("R_CC_SUM1", "100k", "CC1", "CC_SENSE"),
        res("R_CC_SUM2", "100k", "CC2", "CC_SENSE"),
        cap("C_CC_SENSE", "10nF", "CC_SENSE", "GND"),
        db.part("ESD_LINE", "D_USB_DP", {"IO": "USB_DP", "GND": "GND"}),
        db.part("ESD_LINE", "D_USB_DN", {"IO": "USB_DN", "GND": "GND"}),
        db.part("PTC_USB", "F_USB", {"1": "VBUS_IN", "2": "VBUS_FUSED"}),
        db.part("TPS259531", "U_EFUSE", {"IN": "VBUS_FUSED", "OUT": "VUSB", "OUT2": "VUSB",
                                         "OUT3": "VUSB", "ILM": "EFUSE_ILM",
                                         "DVDT": "EFUSE_DVDT", "GND": "GND", "EP": "GND"}),
        cap("C_EFUSE_IN", "100nF", "VBUS_FUSED", "GND"),
        cap("C_EFUSE_DVDT", "3.3nF", "EFUSE_DVDT", "GND"),
        res("R_EFUSE_ILM", "1k", "EFUSE_ILM", "GND"),
        cap10u("C_VUSB", "VUSB", "GND"),

        # ── 充放电 + 升压 IP5306-I2C（spec 3.1）──
        db.part("IP5306_I2C", "U_CHG", {"VIN": "VUSB", "VOUT": "VSYS", "BAT": "VBAT",
                                        "SW": "CHG_SW", "KEY": "KEY_PWR",
                                        "SCL": "I2C_SCL", "SDA": "I2C_SDA", "GND": "GND"}),
        db.part("INDUCTOR_BOOST", "L_CHG", {"1": "CHG_SW", "2": "VBAT"}),
        cap22u("C_CHG_VIN", "VUSB", "GND"),
        cap22u("C_CHG_BAT", "VBAT", "GND"),
        cap22u("C_VSYS1", "VSYS", "GND"),
        cap22u("C_VSYS2", "VSYS", "GND"),

        # ── 电池：座子 → 防反接 → VBAT（spec 3.3，器件见 BATTERY_PROTECTION.md）──
        db.part("CONN_BAT", "J_BAT", {"+": "VBAT_PACK", "-": "GND"}),
        # U_BATPROT 的语义引脚由 Task 2 决定；这里按文档把输入接 VBAT_PACK、输出接 VBAT
        *battery_protection(),
        res("R_VBAT_TOP", "100k", "VBAT", "VBAT_SENSE"),
        res("R_VBAT_BOT", "100k", "VBAT_SENSE", "GND"),
        cap("C_VBAT_SENSE", "100nF", "VBAT_SENSE", "GND"),
        res("R_BAT_NTC", "10k", "+3V3", "BAT_NTC_SENSE"),
        cap("C_BAT_NTC", "100nF", "BAT_NTC_SENSE", "GND"),
        db.part("NTC_0603_10K", "RT_BAT", {"1": "BAT_NTC_SENSE", "2": "GND"}),

        # ── 3V3 降压（同一期 SY8089，取 VSYS）──
        db.part("SY8089", "U_BUCK", {"IN": "VSYS", "EN": "BUCK_EN", "SW": "BUCK_SW",
                                     "FB": "BUCK_FB", "GND": "GND"}),
        res("R_BUCK_EN", "100k", "VSYS", "BUCK_EN"),
        db.part("INDUCTOR_BUCK", "L_BUCK", {"1": "BUCK_SW", "2": "+3V3"}),
        res("R_FB1", "100k", "+3V3", "BUCK_FB"),
        res("R_FB2", "22k", "BUCK_FB", "GND"),
        cap("C_FF", "22pF", "+3V3", "BUCK_FB"),
        cap10u("C_BUCK_IN", "VSYS", "GND"),
        cap22u("C_BUCK_OUT1", "+3V3", "GND"),
        cap22u("C_BUCK_OUT2", "+3V3", "GND"),

        # ── 加热功率级：只接 VUSB（spec 3.2）──
        db.part("CONN_HEAT2", "J_HEAT", {"1": "VUSB", "2": "HEAT_LOW"}),
        db.part("AO3400A", "Q_HEAT", {"G": "HEAT_GATE", "S": "GND", "D": "HEAT_LOW"}),
        res("R_GATE", "100", "HEAT_GATE_DRV", "HEAT_GATE"),
        res("R_GATE_PD", "100k", "HEAT_GATE", "GND"),
        db.part("CONN_SH2", "J_NTC", {"1": "NTC_SENSE", "2": "GND"}),
        res("R_NTC", "10k", "+3V3", "NTC_SENSE"),
        cap("C_NTC", "100nF", "NTC_SENSE", "GND"),

        # ── 测试点（背面）──
        testpoint("TP_VUSB", "VUSB"), testpoint("TP_VSYS", "VSYS"), testpoint("TP_VBAT", "VBAT"),
        testpoint("TP_3V3", "+3V3"), testpoint("TP_GND", "GND"), testpoint("TP_CC", "CC_SENSE"),
    ]


def battery_protection() -> list:
    """按 BATTERY_PROTECTION.md 选定方案连线。Task 2 完成后把方案的语义引脚填进来：
    输入端接 VBAT_PACK，输出端接 VBAT，参考端接 GND。"""
    entry = db.DB["BAT_PROTECT"]
    nets = {}
    for name in entry.pads:
        if name.startswith("IN"):
            nets[name] = "VBAT_PACK"
        elif name.startswith("OUT"):
            nets[name] = "VBAT"
        elif name.startswith("GND"):
            nets[name] = "GND"
    return [db.part("BAT_PROTECT", "U_BATPROT", nets)]
```

`test_core.py` 的 `REQUIRED` 新增两条前置：Task 1 的 `REQUIRED` 里补 `"NTC_0603_10K": {"1", "2"}`；Task 2 的 `BAT_PROTECT` 语义引脚名必须以 `IN` / `OUT` / `GND` 开头（`battery_protection()` 依此连线）——在 `BATTERY_PROTECTION.md` 写明这条命名约定。

`VBAT_SENSE` 分压：电阻值以 `test_vbat_sense_divider_stays_below_adc_range` 为准（两颗 100k）。

- [ ] **Step 4: 运行，确认通过**

Run: `python3 -m unittest test_core -v`
Expected: 9 tests OK

- [ ] **Step 5: Commit**

```bash
git add hardware/plush-toy-v2-mainboard/scripts
git commit -m "feat(pcb-v2): 共用电源电路"
```

### Task 5: 共用核心之 MCU 与外设

**Files:**
- Modify: `hardware/plush-toy-v2-mainboard/scripts/v2/core.py`（新增 `mcu_parts(camera: bool)`、`peripheral_parts()`、`core_parts(camera: bool)`）
- Modify: `hardware/plush-toy-v2-mainboard/scripts/test_core.py`

**Interfaces:**
- Consumes: `gpio.for_family()`、`gpio.WROOM_PAD_GPIO`、`power_parts()`。
- Produces: `core.core_parts(camera: bool) -> list[Part]` = 电源 + MCU + 外设。

- [ ] **Step 1: 写失败测试（追加到 test_core.py）**

```python
from v2 import gpio


class McuPeripheralTests(unittest.TestCase):
    def setUp(self):
        self.parts = core.core_parts(camera=False)

    def test_module_pads_follow_gpio_table(self):
        u1 = next(p for p in self.parts if p.ref == "U1")
        table = gpio.for_family(False)
        for pad, g in gpio.WROOM_PAD_GPIO.items():
            if g in table:
                self.assertEqual(u1.pins[pad], table[g], f"GPIO{g}")

    def test_strapping_pins_have_safe_defaults(self):
        pd46 = next(p for p in self.parts if p.ref == "R_SERVO_R_PD")
        self.assertEqual(set(pd46.pins.values()), {"SERVO_R_PWM", "GND"})
        pu0 = next(p for p in self.parts if p.ref == "R_BOOT")
        self.assertEqual(set(pu0.pins.values()), {"BOOT", "+3V3"})
        pullups_46 = [p for p in self.parts if set(p.pins.values()) == {"SERVO_R_PWM", "+3V3"}]
        self.assertEqual(pullups_46, [])

    def test_single_pullup_per_i2c_line(self):
        for net in ("I2C_SCL", "I2C_SDA"):
            ups = [p for p in self.parts if p.symbol == "Device:R" and set(p.pins.values()) == {net, "+3V3"}]
            self.assertEqual(len(ups), 1, net)

    def test_lcd_connector_shared_cs(self):
        lcd = next(p for p in self.parts if p.ref == "J_LCD")
        self.assertEqual(set(lcd.pins.values()),
                         {"LCD_RST", "LCD_CS", "LCD_DC", "LCD_MOSI_S", "LCD_CLK_S", "GND", "+3V3", "LCD_BL"})

    def test_servos_on_vsys(self):
        for ref in ("J_ARM_L", "J_ARM_R"):
            j = next(p for p in self.parts if p.ref == ref)
            self.assertIn("VSYS", j.pins.values())

    def test_external_lines_have_esd(self):
        for ref in ("J_TOUCH", "J_KEY"):
            j = next(p for p in self.parts if p.ref == ref)
            for net in set(j.pins.values()) - {"GND"}:
                esd = [p for p in self.parts if p.ref.startswith("D_ESD") and net in p.pins.values()]
                self.assertTrue(esd, f"{ref} 的 {net} 没有 ESD")

    def test_buttons_and_leds_present(self):
        refs = {p.ref for p in self.parts}
        self.assertLessEqual({"SW_RST", "SW_BOOT", "LED_CHG", "LED_FULL"}, refs)
```

- [ ] **Step 2: 运行，确认失败**

Run: `python3 -m unittest test_core -v`
Expected: ERROR，`AttributeError: module 'v2.core' has no attribute 'core_parts'`

- [ ] **Step 3: 实现（追加到 core.py）**

```python
from v2 import gpio


def mcu_parts(camera: bool) -> list:
    table = gpio.for_family(camera)
    u1_pins = {"GND": "GND", "3V3": "+3V3", "EN": "EN"}
    u1 = db.part("WROOM", "U1", u1_pins)
    for pad, g in gpio.WROOM_PAD_GPIO.items():
        u1.pins[pad] = table.get(g, f"NC_U1_IO{g}")
    return [
        u1,
        cap10u("C_U1_BULK", "+3V3", "GND"),
        cap("C_U1", "100nF", "+3V3", "GND"),
        res("R_EN", "10k", "+3V3", "EN"),
        cap("C_EN", "1uF", "EN", "GND"),
        res("R_BOOT", "10k", "+3V3", "BOOT"),
        db.part("SW_TACT", "SW_RST", {"A": "EN", "B": "GND"}),
        db.part("SW_TACT", "SW_BOOT", {"A": "BOOT", "B": "GND"}),
        res("R_SCL", "4.7k", "I2C_SCL", "+3V3"),
        res("R_SDA", "4.7k", "I2C_SDA", "+3V3"),
        res("R_SERVO_R_PD", "10k", "SERVO_R_PWM", "GND"),
        testpoint("TP_EN", "EN"), testpoint("TP_BOOT", "BOOT"),
    ]


def peripheral_parts() -> list:
    return [
        # 眼睛：共片选，背光高边开关同一期（spec 4 节：不串限流电阻）
        db.part("CONN_LCD8", "J_LCD", {"1": "LCD_RST", "2": "LCD_CS", "3": "LCD_DC",
                                       "4": "LCD_MOSI_S", "5": "LCD_CLK_S", "6": "GND",
                                       "7": "+3V3", "8": "LCD_BL"}),
        res("R_LCD_MOSI", "33", "LCD_MOSI", "LCD_MOSI_S"),
        res("R_LCD_CLK", "33", "LCD_CLK", "LCD_CLK_S"),
        db.part("AO3401A", "Q_LCD_BL", {"G": "LCD_BL_GATE", "S": "+3V3", "D": "LCD_BL"}),
        res("R_LCD_BL_GATE", "100", "LCD_BL_PWM", "LCD_BL_GATE"),
        res("R_LCD_BL_OFF", "100k", "+3V3", "LCD_BL_GATE"),
        cap("C_LCD", "100nF", "+3V3", "GND"),
        # 麦克风：针序同一期 J_MIC
        db.part("CONN_MIC6", "J_MIC", {"1": "+3V3", "2": "GND", "3": "MIC_SD", "4": "MIC_WS",
                                       "5": "MIC_SCK", "6": "GND"}),
        # 功放 NS4168，取 VSYS；CTRL 分压选左声道（阻值按 SELECTION.md §NS4168 手册表）
        db.part("NS4168", "U_AMP", {"VDD": "VSYS", "GND": "GND", "BCLK": "AMP_BCLK",
                                    "LRCLK": "AMP_LRCLK", "SDATA": "AMP_DIN", "CTRL": "AMP_CTRL",
                                    "OUTP": "SPK_P", "OUTN": "SPK_N"}),
        res("R_AMP_CTRL_TOP", "100k", "VSYS", "AMP_CTRL"),
        res("R_AMP_CTRL_BOT", "100k", "AMP_CTRL", "GND"),
        cap10u("C_AMP_BULK", "VSYS", "GND"),
        cap("C_AMP", "100nF", "VSYS", "GND"),
        db.part("CONN_SPK2", "J_SPK", {"1": "SPK_P", "2": "SPK_N"}),
        # 舵机：VSYS 直供，贴片电容储能（容值按 SELECTION.md §舵机储能）
        db.part("HDR_SERVO3", "J_ARM_L", {"1": "SERVO_L_PWM", "2": "VSYS", "3": "GND"}),
        db.part("HDR_SERVO3", "J_ARM_R", {"1": "SERVO_R_PWM", "2": "VSYS", "3": "GND"}),
        cap22u("C_SERVO1", "VSYS", "GND"),
        cap22u("C_SERVO2", "VSYS", "GND"),
        cap22u("C_SERVO3", "VSYS", "GND"),
        # 加速度计 LIS2DH12：I2C，SA0 接地（地址 0x18）
        db.part("LIS2DH12", "U_IMU", {"VDD": "+3V3", "VDD_IO": "+3V3", "GND": "GND",
                                      "SCL": "I2C_SCL", "SDA": "I2C_SDA",
                                      "SDO_SA0": "GND", "CS": "+3V3"}),
        cap("C_IMU", "100nF", "+3V3", "GND"),
        # 按键座：电源键 → IP5306 KEY，收音键 → 版本相关网络 KEY_MUTE
        db.part("CONN_KEY3", "J_KEY", {"1": "KEY_PWR", "2": "KEY_MUTE", "3": "GND"}),
        db.part("ESD_LINE", "D_ESD_PWR", {"IO": "KEY_PWR", "GND": "GND"}),
        db.part("ESD_LINE", "D_ESD_MUTE", {"IO": "KEY_MUTE", "GND": "GND"}),
        db.part("CONN_SH2", "J_TOUCH", {"1": "TOUCH_E0", "2": "GND"}),
        db.part("ESD_LINE", "D_ESD_TOUCH", {"IO": "TOUCH_E0", "GND": "GND"}),
        # 充电指示灯（接法按 SELECTION.md §IP5306_I2C 的 LED 脚说明）
        db.part("LED_0603", "LED_CHG", {"A": "VSYS", "K": "LED_CHG_K"}),
        res("R_LED_CHG", "1k", "LED_CHG_K", "CHG_LED_DRV"),
        db.part("LED_0603", "LED_FULL", {"A": "VSYS", "K": "LED_FULL_K"}),
        res("R_LED_FULL", "1k", "LED_FULL_K", "FULL_LED_DRV"),
        # 安装孔 M2 ×2
        *[Part(f"H{i}", "M2", "Mechanical:MountingHole", "MountingHole:MountingHole_2.2mm_M2",
               assembly=False) for i in (1, 2)],
    ]


def core_parts(camera: bool) -> list:
    return power_parts() + mcu_parts(camera) + peripheral_parts()
```

`core.py` 顶部补 `from v2.part import Part`。`Task 1` 的 `REQUIRED` 补 `"AO3401A": {"G", "S", "D"}`。
`CHG_LED_DRV` / `FULL_LED_DRV` 必须在 Task 4 的 `U_CHG` 连线里出现（按 IP5306-I2C 手册的指示灯脚），本任务完成时由 Task 6 的 `test_no_single_pin_nets` 兜底检查。

- [ ] **Step 4: 运行，确认通过**

Run: `python3 -m unittest test_core -v`
Expected: 16 tests OK

- [ ] **Step 5: Commit**

```bash
git add hardware/plush-toy-v2-mainboard/scripts
git commit -m "feat(pcb-v2): 共用 MCU 与外设电路"
```

### Task 6: 不带摄像头差异与版本组合

**Files:**
- Create: `hardware/plush-toy-v2-mainboard/scripts/v2/nocam.py`
- Create: `hardware/plush-toy-v2-mainboard/scripts/v2/cam.py`
- Create: `hardware/plush-toy-v2-mainboard/scripts/v2/variants.py`
- Test: `hardware/plush-toy-v2-mainboard/scripts/test_variants.py`

**Interfaces:**
- Produces: `variants.VARIANTS: dict[str, Variant]`，`Variant(name: str, camera: bool, double_sided: bool)`；`variants.parts(name) -> list[Part]`；`variants.nets(name) -> dict[str, list[tuple[str, str]]]`。`cam.camera_parts()` 本计划只返回空列表并在 C/D 上抛 `NotImplementedError`（后续计划实现）。

- [ ] **Step 1: 写失败测试**

```python
import unittest

from v2 import variants

HAND_EXEMPT_PREFIXES = ("TP_", "H")


class VariantATests(unittest.TestCase):
    parts = variants.parts("A")

    def test_variant_table(self):
        self.assertEqual({k: (v.camera, v.double_sided) for k, v in variants.VARIANTS.items()},
                         {"A": (False, False), "B": (False, True), "C": (True, False), "D": (True, True)})

    def test_refs_unique(self):
        refs = [p.ref for p in self.parts]
        self.assertEqual(len(refs), len(set(refs)))

    def test_zero_hand_solder(self):
        for p in self.parts:
            if p.ref.startswith(HAND_EXEMPT_PREFIXES):
                continue
            with self.subTest(ref=p.ref):
                self.assertTrue(p.assembly)
                self.assertRegex(p.lcsc, r"^C\d+$")

    def test_no_single_pin_nets(self):
        singles = [n for n, ends in variants.nets("A").items()
                   if len(ends) == 1 and not n.startswith("NC_")]
        self.assertEqual(singles, [])

    def test_nocam_functions_reach_gpio(self):
        nets = variants.nets("A")
        for net in ("HEAT_GATE_DRV", "KEY_MUTE", "TOUCH_E0", "NTC_SENSE",
                    "VBAT_SENSE", "CC_SENSE", "BAT_NTC_SENSE"):
            self.assertIn("U1", {r for r, _ in nets[net]}, net)

    def test_no_camera_parts_in_a(self):
        self.assertFalse(any(p.ref.startswith(("J_CAM", "U_LDO", "U_TOUCH", "U_ADC")) for p in self.parts))

    def test_camera_variants_not_built_yet(self):
        for name in ("C", "D"):
            with self.assertRaises(NotImplementedError):
                variants.parts(name)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行，确认失败**

Run: `python3 -m unittest test_variants -v`
Expected: ERROR，`ImportError: cannot import name 'variants'`

- [ ] **Step 3: 实现**

`v2/nocam.py`：

```python
"""A/B：触摸、ADC、加热栅极、收音键都直接接 ESP32（spec 5.2）。
这些网络已由 core 的 U1 按 gpio.NOCAM 接到模组，这里只补滤波。"""
from v2.part import cap


def nocam_parts() -> list:
    return [
        cap("C_TOUCH_FILT", "10nF", "TOUCH_E0", "GND"),
    ]
```

`C_TOUCH_FILT` 的容值在 A 首板上需按片上触摸灵敏度复核，`TESTING.md` 中列为验收项。

`v2/cam.py`：

```python
"""C/D：摄像头模块（spec 5.3、第 7 节）。由后续计划实现。"""


def camera_parts() -> list:
    raise NotImplementedError("带摄像头版本在后续计划实现，必须先满足 spec 第 7 节")
```

`v2/variants.py`：

```python
from dataclasses import dataclass

from v2 import cam, core, nocam


@dataclass(frozen=True)
class Variant:
    name: str
    camera: bool
    double_sided: bool


VARIANTS = {
    "A": Variant("A", camera=False, double_sided=False),
    "B": Variant("B", camera=False, double_sided=True),
    "C": Variant("C", camera=True, double_sided=False),
    "D": Variant("D", camera=True, double_sided=True),
}


def parts(name: str) -> list:
    v = VARIANTS[name]
    extra = cam.camera_parts() if v.camera else nocam.nocam_parts()
    return core.core_parts(v.camera) + extra


def nets(name: str) -> dict[str, list[tuple[str, str]]]:
    result: dict[str, list[tuple[str, str]]] = {}
    for part in parts(name):
        if not part.fitted:
            continue
        for pin, net in part.pins.items():
            result.setdefault(net, []).append((part.ref, pin))
    return result
```

- [ ] **Step 4: 运行，确认通过；修正单引脚网络**

Run: `python3 -m unittest test_variants test_core test_gpio test_parts_db -v`
Expected: 全部 OK。若 `test_no_single_pin_nets` 报出网络（例如 `CHG_LED_DRV` 未接到 `U_CHG`），回到 Task 4 的 `U_CHG` 连线补齐，再跑。

- [ ] **Step 5: Commit**

```bash
git add hardware/plush-toy-v2-mainboard/scripts
git commit -m "feat(pcb-v2): 版本组合与 A 版器件表"
```

---

## 阶段 2：版本 A 出板

### Task 7: 版本上下文、工程规则与原理图

**Files:**
- Create: `hardware/plush-toy-v2-mainboard/scripts/context.py`
- Create: `hardware/plush-toy-v2-mainboard/scripts/project_rules.py`（复制一期后修改）
- Create: `hardware/plush-toy-v2-mainboard/scripts/gen_schematic.py`（复制一期后修改）
- Test: `hardware/plush-toy-v2-mainboard/scripts/test_netlist.py`

**Interfaces:**
- Produces: `context.load(variant: str) -> Ctx`，`Ctx` 字段：`variant: Variant`、`parts: list[Part]`、`nets: dict`、`dir: Path`（`variants/<X>`）、`project: str`（`plush-toy-v2-<X>`）、`sch: Path`、`pcb: Path`、`pro: Path`、`build: Path`、`placement`（`placement_<X>` 模块）。所有后续脚本命令行形如 `python3 <script>.py --variant A`。

- [ ] **Step 1: 写 context 与失败测试**

```python
# context.py
import argparse
import importlib
from dataclasses import dataclass
from pathlib import Path

from v2 import variants

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Ctx:
    variant: variants.Variant
    parts: list
    nets: dict
    dir: Path
    project: str

    @property
    def sch(self) -> Path:
        return self.dir / f"{self.project}.kicad_sch"

    @property
    def pcb(self) -> Path:
        return self.dir / f"{self.project}.kicad_pcb"

    @property
    def pro(self) -> Path:
        return self.dir / f"{self.project}.kicad_pro"

    @property
    def build(self) -> Path:
        return self.dir / "build"

    @property
    def placement(self):
        return importlib.import_module(f"placement_{self.variant.name}")


def load(name: str) -> Ctx:
    return Ctx(variants.VARIANTS[name], variants.parts(name), variants.nets(name),
               ROOT / "variants" / name, f"plush-toy-v2-{name}")


def from_argv() -> Ctx:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True, choices=sorted(variants.VARIANTS))
    return load(parser.parse_args().variant)
```

`test_netlist.py`（复制一期 `test_netlist_roundtrip.py` 的检查逻辑，改为读 `context.load("A")`）：

```python
import subprocess
import unittest

import context
import kicad_env


class NetlistRoundtripA(unittest.TestCase):
    def test_exported_netlist_matches_spec(self):
        ctx = context.load("A")
        out = ctx.build / "netlist.xml"
        ctx.build.mkdir(parents=True, exist_ok=True)
        subprocess.run([kicad_env.KICAD_CLI, "sch", "export", "netlist", "--format", "kicadxml",
                        "-o", str(out), str(ctx.sch)], check=True)
        import xml.etree.ElementTree as ET
        exported = {}
        for net in ET.parse(out).getroot().iter("net"):
            name = net.get("name").lstrip("/")
            exported[name] = {(n.get("ref"), n.get("pin")) for n in net.iter("node")}
        for name, ends in ctx.nets.items():
            if name.startswith("NC_"):
                continue
            with self.subTest(net=name):
                self.assertEqual(exported.get(name), set(ends))

    def test_erc_clean(self):
        ctx = context.load("A")
        report = ctx.build / "erc.rpt"
        subprocess.run([kicad_env.KICAD_CLI, "sch", "erc", "--severity-error", "--exit-code-violations",
                        "-o", str(report), str(ctx.sch)], check=True)
```

- [ ] **Step 2: 运行，确认失败**

Run: `python3 -m unittest test_netlist -v`
Expected: FAIL，原理图文件不存在（kicad-cli 返回非零）

- [ ] **Step 3: 移植 project_rules 与 gen_schematic**

```bash
cp hardware/plush-toy-mainboard/scripts/project_rules.py hardware/plush-toy-mainboard/scripts/gen_schematic.py hardware/plush-toy-v2-mainboard/scripts/
```

修改点（逐条照做）：
1. `project_rules.py`：删除模块级 `PRO = ...`；`apply(path: Path = PRO)` 改为 `apply(path: Path)`；`PATTERNS` 中一期网络名换成二期电源网络：`VUSB`、`VSYS`、`VBAT`、`VBAT_PACK`、`HEAT_LOW`、`SPK_P`、`SPK_N` 归入大电流网络类，`+3V3`、`GND` 归入电源类；删除 `VMOT`、`PGND` 相关项。
2. `gen_schematic.py`：删除 `import board_spec` 与模块级 `PROJECT/SCH/PRO`；`main()` 开头 `ctx = context.from_argv()`；所有 `board_spec.PARTS` 改为 `ctx.parts`，`board_spec.nets()` 改为 `ctx.nets`；输出路径用 `ctx.sch`、`ctx.pro`；`_NAMESPACE` 改为 `uuid.uuid5(uuid.NAMESPACE_URL, f"xiaozhi-esp32/hardware/{ctx.project}")`（在 `main()` 内计算并传入生成函数）；保存后调用 `project_rules.apply(ctx.pro)`。
3. 生成 `.kicad_pro` 时 `fp-lib-table` / `sym-lib-table` 写入 `plushv2` 库，路径 `${KIPRJMOD}/../../lib/plushv2.pretty` 与 `plushv2.kicad_sym`。

Run: `mkdir -p hardware/plush-toy-v2-mainboard/variants/A && cd hardware/plush-toy-v2-mainboard/scripts && python3 gen_schematic.py --variant A`
Expected: 生成 `variants/A/plush-toy-v2-A.kicad_sch` 与 `.kicad_pro`

- [ ] **Step 4: 运行，确认通过**

Run: `python3 -m unittest test_netlist -v`
Expected: 2 tests OK。ERC 报「电源输入未驱动」时，按一期做法给该网络补 `PWR_FLAG`（一期 gen_schematic 已有此逻辑，确认它对 `VSYS`、`VBAT`、`VUSB` 生效）。

- [ ] **Step 5: Commit**

```bash
git add hardware/plush-toy-v2-mainboard
git commit -m "feat(pcb-v2): 版本上下文与 A 版原理图"
```

### Task 8: 版本 A 布局

**Files:**
- Create: `hardware/plush-toy-v2-mainboard/scripts/placement_A.py`
- Create: `hardware/plush-toy-v2-mainboard/scripts/gen_pcb.py`（复制一期后修改）
- Test: `hardware/plush-toy-v2-mainboard/scripts/test_pcb_A.py`

**Interfaces:**
- Consumes: `context.load("A")`。
- Produces: `placement_A.W: float`、`placement_A.H: float`、`placement_A.CORNER_R: float`、`placement_A.ANCHORS: dict[str, tuple[float, float, int]]`、`placement_A.NEAR: dict[str, str]`、`placement_A.EDGE_CONNECTORS: dict[str, str]`（位号 → 所在边 `"top"|"bottom"|"left"|"right"`）；`variants/A/plush-toy-v2-A.kicad_pcb`。

- [ ] **Step 1: 写失败测试（KiCad Python）**

```python
import unittest

import pcbnew

import context

ctx = context.load("A")
pl = ctx.placement
TO_MM = 1e-6


class PcbATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = pcbnew.LoadBoard(str(ctx.pcb))
        cls.fps = {f.GetReference(): f for f in cls.board.GetFootprints()}

    def test_outline_matches_placement(self):
        bb = self.board.GetBoardEdgesBoundingBox()
        self.assertAlmostEqual(bb.GetWidth() * TO_MM, pl.W, delta=0.05)
        self.assertAlmostEqual(bb.GetHeight() * TO_MM, pl.H, delta=0.05)

    def test_every_part_placed(self):
        self.assertEqual({p.ref for p in ctx.parts} - set(self.fps), set())

    def test_single_sided(self):
        back = [r for r, f in self.fps.items() if f.GetLayer() == pcbnew.B_Cu and not r.startswith("TP_")]
        self.assertEqual(back, [])

    def test_testpoints_on_back(self):
        for r, f in self.fps.items():
            if r.startswith("TP_"):
                self.assertEqual(f.GetLayer(), pcbnew.B_Cu, r)

    def test_antenna_overhangs_edge(self):
        u1 = self.fps["U1"]
        bb = u1.GetBoundingBox(False)
        edges = self.board.GetBoardEdgesBoundingBox()
        self.assertTrue(bb.GetLeft() < edges.GetLeft() or bb.GetTop() < edges.GetTop()
                        or bb.GetRight() > edges.GetRight() or bb.GetBottom() > edges.GetBottom())

    def test_edge_connectors_touch_their_edge(self):
        edges = self.board.GetBoardEdgesBoundingBox()
        for ref, side in pl.EDGE_CONNECTORS.items():
            bb = self.fps[ref].GetBoundingBox(False)
            gap = {"top": bb.GetTop() - edges.GetTop(), "bottom": edges.GetBottom() - bb.GetBottom(),
                   "left": bb.GetLeft() - edges.GetLeft(), "right": edges.GetRight() - bb.GetRight()}[side]
            self.assertLessEqual(gap * TO_MM, 1.0, ref)

    def test_heat_and_charger_away_from_battery_connector(self):
        def centre(ref):
            p = self.fps[ref].GetPosition()
            return p.x * TO_MM, p.y * TO_MM
        bx, by = centre("J_BAT")
        for ref in ("Q_HEAT", "U_CHG", "U_BUCK"):
            x, y = centre(ref)
            self.assertGreaterEqual(((x - bx) ** 2 + (y - by) ** 2) ** 0.5, 8.0, ref)

    def test_inner_layers_are_power_planes(self):
        for layer in (pcbnew.In1_Cu, pcbnew.In2_Cu):
            self.assertEqual(self.board.GetLayerType(layer), pcbnew.LT_POWER)

    def test_no_courtyard_overlap(self):
        fps = [f for f in self.fps.values() if f.GetLayer() == pcbnew.F_Cu]
        for i, a in enumerate(fps):
            ca = a.GetCourtyard(pcbnew.F_CrtYd)
            for b in fps[i + 1:]:
                cb = b.GetCourtyard(pcbnew.F_CrtYd)
                if ca.OutlineCount() and cb.OutlineCount():
                    self.assertFalse(ca.Collide(cb.Outline(0)), f"{a.GetReference()} × {b.GetReference()}")
```

- [ ] **Step 2: 运行，确认失败**

Run: `/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_pcb_A -v`
Expected: ERROR，PCB 文件不存在

- [ ] **Step 3: 写 placement_A.py（起步尺寸 52×42mm）**

```python
"""版本 A 布局。原点左上角，x 右 y 下，单位 mm，角度 KiCad 约定。
分区：天线伸出左边；USB-C 与充放电在下边；出线座集中在上边与右边；电池座在右下，
远离加热与电源芯片（spec 6 节）。起步尺寸来自 spec 2 节估算，Task 9 逐轮收缩。"""

W, H = 52.0, 42.0
CORNER_R = 3.0
# In2 内层：x < VSYS_PLANE_X 为 +3V3 平面（模组与逻辑），x ≥ 为 VSYS 平面（舵机、功放、充放电）
VSYS_PLANE_X = 30.0
EDGE_MARGIN = 0.5
GAP = 0.2

ANCHORS = {
    # 模组转 90°，天线朝左伸出板边（一期同法：中心 x=6.75）
    "U1": (6.75, 21.0, 90),
    "H1": (W - 3.5, 3.5, 0),
    "H2": (W - 3.5, H - 3.5, 0),
    # 下边：USB-C 开口朝下，eFuse、IP5306 在其上方
    "J_USB": (26.0, H - 3.8, 0),
    # 上边：出线座，开口朝上
    "J_LCD": (24.0, 2.6, 180),
    "J_MIC": (35.0, 2.6, 180),
    "J_KEY": (42.5, 2.6, 180),
    # 右边：舵机、加热、喇叭、触摸、测温
    "J_ARM_L": (W - 2.0, 11.0, 90),
    "J_ARM_R": (W - 2.0, 17.0, 90),
    "J_HEAT": (W - 3.5, 24.5, 90),
    "J_SPK": (W - 2.2, 30.0, 90),
    # 电池座在左下角，离加热与电源芯片最远
    "J_BAT": (20.0, H - 3.0, 0),
    "SW_RST": (17.5, 9.0, 0),
    "SW_BOOT": (17.5, 14.0, 0),
}

# 其余器件放在所连主器件附近（gen_pcb 按螺旋搜索找空位）
NEAR = {
    "C_U1_BULK": "U1", "C_U1": "U1", "R_EN": "U1", "C_EN": "U1", "R_BOOT": "SW_BOOT",
    "R_CC1": "J_USB", "R_CC2": "J_USB", "R_CC_SUM1": "J_USB", "R_CC_SUM2": "J_USB",
    "C_CC_SENSE": "J_USB", "D_USB_DP": "J_USB", "D_USB_DN": "J_USB", "F_USB": "J_USB",
    "U_EFUSE": "F_USB", "C_EFUSE_IN": "U_EFUSE", "C_EFUSE_DVDT": "U_EFUSE",
    "R_EFUSE_ILM": "U_EFUSE", "C_VUSB": "U_EFUSE",
    "U_CHG": "U_EFUSE", "L_CHG": "U_CHG", "C_CHG_VIN": "U_CHG", "C_CHG_BAT": "U_CHG",
    "C_VSYS1": "U_CHG", "C_VSYS2": "U_CHG", "LED_CHG": "U_CHG", "LED_FULL": "U_CHG",
    "R_LED_CHG": "LED_CHG", "R_LED_FULL": "LED_FULL",
    "U_BATPROT": "J_BAT", "R_VBAT_TOP": "J_BAT", "R_VBAT_BOT": "J_BAT", "C_VBAT_SENSE": "J_BAT",
    "RT_BAT": "J_BAT", "R_BAT_NTC": "RT_BAT", "C_BAT_NTC": "RT_BAT",
    "U_BUCK": "U_CHG", "L_BUCK": "U_BUCK", "R_BUCK_EN": "U_BUCK", "R_FB1": "U_BUCK",
    "R_FB2": "U_BUCK", "C_FF": "U_BUCK", "C_BUCK_IN": "U_BUCK", "C_BUCK_OUT1": "U_BUCK",
    "C_BUCK_OUT2": "U_BUCK",
    "Q_HEAT": "J_HEAT", "R_GATE": "Q_HEAT", "R_GATE_PD": "Q_HEAT",
    "J_NTC": "J_HEAT", "R_NTC": "J_NTC", "C_NTC": "J_NTC",
    "R_LCD_MOSI": "J_LCD", "R_LCD_CLK": "J_LCD", "Q_LCD_BL": "J_LCD", "R_LCD_BL_GATE": "Q_LCD_BL",
    "R_LCD_BL_OFF": "Q_LCD_BL", "C_LCD": "J_LCD",
    "U_AMP": "J_SPK", "R_AMP_CTRL_TOP": "U_AMP", "R_AMP_CTRL_BOT": "U_AMP",
    "C_AMP_BULK": "U_AMP", "C_AMP": "U_AMP",
    "C_SERVO1": "J_ARM_L", "C_SERVO2": "J_ARM_R", "C_SERVO3": "J_ARM_R",
    "R_SERVO_R_PD": "J_ARM_R",
    "U_IMU": "U1", "C_IMU": "U_IMU", "R_SCL": "U_IMU", "R_SDA": "U_IMU",
    "D_ESD_PWR": "J_KEY", "D_ESD_MUTE": "J_KEY",
    "J_TOUCH": "J_KEY", "D_ESD_TOUCH": "J_TOUCH", "C_TOUCH_FILT": "J_TOUCH",
}

EDGE_CONNECTORS = {
    "J_USB": "bottom", "J_BAT": "bottom", "J_LCD": "top", "J_MIC": "top", "J_KEY": "top",
    "J_ARM_L": "right", "J_ARM_R": "right", "J_HEAT": "right", "J_SPK": "right",
}

# 测试点放背面，位置由 gen_pcb 在背面螺旋搜索（不受正面庭院约束）
BACK_SIDE_PREFIXES = ("TP_",)
```

坐标是起点。Step 4 生成后若某器件放不下，gen_pcb 会报出位号；按报错调整 `ANCHORS`，不要放宽 `test_pcb_A` 的断言。

- [ ] **Step 4: 移植 gen_pcb 并生成**

```bash
cp hardware/plush-toy-mainboard/scripts/gen_pcb.py hardware/plush-toy-v2-mainboard/scripts/
```

修改点：
1. 删除 `import board_spec`、`import placement` 与模块级 `PCB`；`main()` 开头 `ctx = context.from_argv(); pl = ctx.placement`；`board_spec.PARTS` → `ctx.parts`；`board_spec.nets()` → `ctx.nets`；`placement.X` → `pl.X`。
2. `add_outline()` 改为画 `pl.W × pl.H`、圆角半径 `pl.CORNER_R` 的圆角矩形（4 段直线 + 4 段 `PCB_SHAPE` 圆弧，层 `Edge_Cuts`）。
3. 器件位号前缀在 `pl.BACK_SIDE_PREFIXES` 内的，`fp.SetLayerAndFlip(pcbnew.B_Cu)` 后在背面螺旋找位，只和背面器件比庭院重叠。
4. 内层铺铜：In1 `GND` 整板；In2 分两块——`+3V3`（x < `pl.VSYS_PLANE_X`）与 `VSYS`（x ≥ `pl.VSYS_PLANE_X`）。
5. 设置 In1/In2 层类型为 `LT_POWER`；保存到 `ctx.build / "candidate.kicad_pcb"`，成功后再 `replace` 到 `ctx.pcb`；最后 `project_rules.apply(ctx.pro)`。
6. 删除一期专有逻辑：`VMOT`/`PGND` 区、XCLK 守护过孔、星形接地丝印、一期安全丝印文本。新增丝印：每个出线座旁写功能名（`LCD`、`MIC`、`KEY`、`ARM L`、`ARM R`、`HEAT`、`SPK`、`TOUCH`、`NTC`、`BAT +/-`、`USB`），字高 1.0mm、线宽 0.15mm；`HEAT` 旁加「必须串 KSD9700」。

Run: `cd hardware/plush-toy-v2-mainboard/scripts && /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 gen_pcb.py --variant A`
Expected: 生成 `variants/A/plush-toy-v2-A.kicad_pcb`，无「放不下」报错

- [ ] **Step 5: 运行，确认通过**

Run: `.../python3 -m unittest test_pcb_A -v`
Expected: 9 tests OK

- [ ] **Step 6: Commit**

```bash
git add hardware/plush-toy-v2-mainboard
git commit -m "feat(pcb-v2): 版本 A 布局"
```

### Task 9: 版本 A 尺寸收缩

**Files:**
- Modify: `hardware/plush-toy-v2-mainboard/scripts/placement_A.py`
- Modify: `hardware/plush-toy-v2-mainboard/README.md`（记录每轮尺寸）

**Interfaces:**
- Produces: 定稿的 `placement_A.W/H`。

- [ ] **Step 1: 建 README 并记录起点**

`README.md` 新增「版本 A 尺寸迭代」表：轮次、W×H、面积 / 5400mm²、失败原因。第 0 轮写 `52×42`。

- [ ] **Step 2: 收缩一轮**

W 或 H 减 2mm（先减放置余量更大的方向），按比例平移 `ANCHORS` 中贴边器件，重新运行 `gen_pcb.py --variant A` 与 `test_pcb_A`。

- [ ] **Step 3: 判定**

- 全部通过：记录本轮尺寸，回到 Step 2。
- `gen_pcb` 报放不下或测试失败：尝试调整 `ANCHORS` 一次；仍失败则退回上一轮尺寸，记录失败原因，结束收缩。

- [ ] **Step 4: 留布线余量**

收缩停止后，在最后成功尺寸基础上 W、H 各加 1mm 作为布线余量（Task 10 若布线完全收敛可再试收回）。重新生成并跑 `test_pcb_A`。

- [ ] **Step 5: Commit**

```bash
git add hardware/plush-toy-v2-mainboard
git commit -m "feat(pcb-v2): 版本 A 尺寸收缩至 <W>x<H>mm"
```

提交信息中的 `<W>x<H>` 写实际数值。

### Task 10: 版本 A 扇出、布线与 DRC

**Files:**
- Create: `hardware/plush-toy-v2-mainboard/scripts/fanout.py`、`route.py`（复制一期后修改）
- Create: `hardware/plush-toy-v2-mainboard/scripts/post_route.py`（二期精简版，新写）
- Test: `hardware/plush-toy-v2-mainboard/scripts/test_drc_A.py`

**Interfaces:**
- Consumes: `ctx.pcb`、`project_rules.apply(path)`。
- Produces: `post_route.drc(pcb: Path) -> dict`（kicad-cli DRC JSON）、`post_route.refill_and_save(pcb: Path) -> None`；布线完成的 `ctx.pcb`。

- [ ] **Step 1: 写失败测试**

```python
import unittest

import context
import post_route

ctx = context.load("A")


class DrcA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        post_route.refill_and_save(ctx.pcb)   # 没有重新灌铜的 DRC 不可信
        cls.report = post_route.drc(ctx.pcb)

    def test_no_unconnected_items(self):
        self.assertEqual(self.report.get("unconnected_items", []), [])

    def test_no_drc_errors(self):
        errors = [v for v in self.report.get("violations", []) if v.get("severity") == "error"]
        self.assertEqual(errors, [])

    def test_schematic_parity(self):
        self.assertEqual(self.report.get("schematic_parity", []), [])
```

- [ ] **Step 2: 运行，确认失败**

Run: `.../python3 -m unittest test_drc_A -v`
Expected: FAIL，大量 unconnected_items（尚未布线）

- [ ] **Step 3: 写 post_route.py**

```python
"""二期布线后处理：只做重新灌铜、DRC 与非回退判定。一期那套针对具体位号的修补不搬过来；
二期遇到自动布线解决不了的开路，在 placement 或专门的 ECO 脚本里处理，并在此文件末尾登记。"""
import json
import subprocess
from pathlib import Path

import pcbnew

import kicad_env
import project_rules


def refill_and_save(pcb: Path) -> None:
    board = pcbnew.LoadBoard(str(pcb))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    tmp = pcb.with_suffix(".refill.kicad_pcb")
    board.Save(str(tmp))
    tmp.replace(pcb)
    project_rules.apply(pcb.with_suffix(".kicad_pro"))


def drc(pcb: Path) -> dict:
    out = pcb.parent / "build" / "drc.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([kicad_env.KICAD_CLI, "pcb", "drc", "--format", "json", "--schematic-parity",
                    "--refill-zones", "-o", str(out), str(pcb)], check=False)
    return json.loads(out.read_text(encoding="utf-8"))
```

- [ ] **Step 4: 移植 fanout 与 route**

```bash
cp hardware/plush-toy-mainboard/scripts/fanout.py hardware/plush-toy-mainboard/scripts/route.py hardware/plush-toy-v2-mainboard/scripts/
ln -s ../../plush-toy-mainboard/tools hardware/plush-toy-v2-mainboard/tools
```

修改点：
1. 两个文件删除模块级 `ROOT/PCB/BUILD`，改由 `ctx = context.from_argv()` 提供 `ctx.pcb`、`ctx.build`。
2. `fanout.py`：`import placement as pl` 改为 `pl = ctx.placement`；`PLANES` 改为 `{"GND": (0.0, pl.W), "+3V3": (0.0, pl.VSYS_PLANE_X), "VSYS": (pl.VSYS_PLANE_X, pl.W)}`。
3. `route.py`：`import post_route` 后用二期的 `drc()`、`refill_and_save()`；JAR 路径 `ROOT / "tools" / "freerouting-2.4.1.jar"`（经上面的软链接指向一期 tools，不复制 64MB 的 jar）。

Run:
```bash
cd hardware/plush-toy-v2-mainboard/scripts
KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
$KP fanout.py --variant A
$KP route.py --variant A
```
Expected: `route.py` 打印每轮开路数，最终晋升一个非回退结果

- [ ] **Step 5: 处理剩余开路**

Run: `$KP -m unittest test_drc_A -v`
- 通过：进入 Step 6。
- 有开路：先调整 `placement_A.py` 让相关器件更靠近、重跑 Task 8 Step 4 → fanout → route（最多三轮）；仍有开路时，为每个开路写一个小 ECO 函数追加到 `post_route.py`（在文件末尾登记位号与原因），由 `route.py` 在晋升后调用。每加一个 ECO 都要重跑 `test_drc_A`。
- 布线三轮后仍无法收敛：退回 Task 9 Step 4，再加 1mm 布线余量。

- [ ] **Step 6: 用 pcb-check 复核并提交**

按 `.claude/skills/pcb-check/SKILL.md` 的流程对 `variants/A` 跑一遍（重新灌铜后的 DRC、未连接项、原理图一致性）。

```bash
git add hardware/plush-toy-v2-mainboard
git commit -m "feat(pcb-v2): 版本 A 布线完成，DRC 0 错误 0 开路"
```

### Task 11: 版本 A 生产文件、接线表与验收清单

**Files:**
- Create: `hardware/plush-toy-v2-mainboard/scripts/export_bom.py`、`fab_tools.py`、`export_fab.sh`、`export_wiring.py`（复制一期后参数化）
- Create: `hardware/plush-toy-v2-mainboard/variants/A/TESTING.md`
- Test: `hardware/plush-toy-v2-mainboard/scripts/test_export.py`

**Interfaces:**
- Consumes: `ctx`。
- Produces: `variants/A/fab/{gerber.zip,bom.csv,positions.csv}`、`variants/A/WIRING.md`、`variants/A/TESTING.md`、`variants/A/fab/parts_report.txt`（扩展库种类数、库存检查结果）。

- [ ] **Step 1: 写失败测试**

```python
import csv
import unittest

import context
import export_bom

ctx = context.load("A")


class ExportA(unittest.TestCase):
    def test_bom_covers_every_assembly_part_once(self):
        rows = export_bom.rows(ctx)
        refs = [r for row in rows for r in row["Designator"].split(",")]
        expected = {p.ref for p in ctx.parts if p.assembly and p.fitted}
        self.assertEqual(sorted(refs), sorted(expected))

    def test_bom_has_no_missing_lcsc(self):
        for row in export_bom.rows(ctx):
            self.assertRegex(row["LCSC Part #"], r"^C\d+$", row["Designator"])

    def test_positions_match_bom(self):
        pos = ctx.dir / "fab" / "positions.csv"
        if not pos.exists():
            self.skipTest("先运行 export_fab.sh A")
        with pos.open(encoding="utf-8-sig") as f:
            pos_refs = {r["Designator"] for r in csv.DictReader(f)}
        self.assertEqual(pos_refs, {p.ref for p in ctx.parts if p.assembly and p.fitted})

    def test_wiring_lists_every_connector(self):
        text = (ctx.dir / "WIRING.md").read_text(encoding="utf-8")
        for ref in ("J_LCD", "J_MIC", "J_SPK", "J_ARM_L", "J_ARM_R", "J_HEAT", "J_NTC",
                    "J_TOUCH", "J_KEY", "J_BAT", "J_USB"):
            self.assertIn(ref, text)
```

- [ ] **Step 2: 运行，确认失败**

Run: `python3 -m unittest test_export -v`
Expected: ERROR，`export_bom` 不存在

- [ ] **Step 3: 移植导出脚本**

```bash
cd hardware/plush-toy-mainboard/scripts
cp export_bom.py fab_tools.py export_fab.sh export_wiring.py ../../plush-toy-v2-mainboard/scripts/
```

修改点：
1. `export_bom.py`：`rows()` 改为 `rows(ctx)`，读 `ctx.parts`；删除 `HAND_INSTALLED_REFS`（二期没有手焊件）；`main()` 用 `context.from_argv()`，输出 `ctx.dir / "fab" / "bom.csv"`。
2. `fab_tools.py`：`expected_assembly_refs()` 改为接收 `ctx`；`validate(fab)` 不变。
3. `export_fab.sh`：第一个参数为版本名，`ROOT` 下 `PCB="$ROOT/variants/$1/plush-toy-v2-$1.kicad_pcb"`、`FAB="$ROOT/variants/$1/fab"`；测试命令换成二期的 `test_parts_db test_gpio test_core test_variants test_netlist` 与 `test_pcb_$1 test_drc_$1`；单面版本 Gerber 层与一期相同，坐标只导正面。
4. `export_wiring.py`：`CONNECTORS`、`NOTES`、`HOUSINGS`、`OFFBOARD` 按 spec 第 4 节重写（SH1.0、MX1.25、XH2.54、PH2.0 电池、2.54 贴片排针、Y 型眼睛线、1500mAh 电池、IP5306 外接按键）；`OFFBOARD` 去掉一期独有项（KF301、VH3.96、5V/3A 舵机电源）。
5. 新增 `parts_report`：在 `export_fab.sh` 末尾调用 `python3 export_bom.py --report --variant $1`，对 BOM 每个料号打开 `https://www.lcsc.com/product-detail/<C编号>.html` 读取库存与「基础库 / 扩展库」标识，写入 `fab/parts_report.txt`；库存 < 20 的料号让脚本以非零退出。

- [ ] **Step 4: 写版本 A 验收清单**

`variants/A/TESTING.md`：复制一期 `hardware/plush-toy-mainboard/TESTING.md` 的结构（仪器与降级、不通电检查、首次上电、外设逐个加、加热最后、卡住时先查什么），按二期改写：
- 测试点换成 `TP_VUSB / TP_VSYS / TP_VBAT / TP_3V3 / TP_GND / TP_CC / TP_EN / TP_BOOT`。
- 删去 VMOT 一节；新增「电池」一节（先不接电池上电，再接电池；反接一次只做纸面确认，不做实测）。
- 加入 spec 第 9 节全部新增项：待机 5 分钟不断电、CC 判断三种电源、边加热边充电 10 分钟、续航 ≥ 4 小时、电池测温、共片选双眼 40MHz。
- 加入片上触摸灵敏度复核（`C_TOUCH_FILT` 取值）。
- 开头保留「万用表先做对照再读数」与「通电时只点测试点」两条一期教训。

- [ ] **Step 5: 导出并运行测试**

Run:
```bash
cd hardware/plush-toy-v2-mainboard/scripts
bash export_fab.sh A
python3 export_wiring.py --variant A
python3 -m unittest test_export -v
```
Expected: `fab/` 下 gerber.zip、bom.csv、positions.csv、parts_report.txt 生成；4 tests OK

- [ ] **Step 6: Commit**

```bash
git add hardware/plush-toy-v2-mainboard
git commit -m "feat(pcb-v2): 版本 A 生产文件、接线表与验收清单"
```

### Task 12: 检查点 A —— 尺寸与报价交委托方

**Files:**
- Modify: `hardware/plush-toy-v2-mainboard/README.md`
- Modify: `docs/superpowers/plans/STATUS.md`

- [ ] **Step 1: 汇总**

README 新增「版本 A 结果」：最终尺寸与面积占一期比例、BOM 行数、扩展库种类数、主要芯片实际单价合计、DRC 结论、3D 渲染图（`kicad-cli pcb render` 正反两面，存 `variants/A/renders/`）。

- [ ] **Step 2: 嘉立创报价**

把 `variants/A/fab/gerber.zip`、`bom.csv`、`positions.csv` 交委托方在嘉立创下单页试算（不付款），记录：5 片 PCB 价、贴 2 片的 SMT 总价、单板器件费。

- [ ] **Step 3: 委托方决定**

向委托方展示尺寸、报价、渲染图，请其决定：A 是否下单打样；B/C/D 是否继续。把决定写进 STATUS.md。

- [ ] **Step 4: Commit**

```bash
git add hardware/plush-toy-v2-mainboard/README.md docs/superpowers/plans/STATUS.md
git commit -m "docs(pcb-v2): 版本 A 检查点结果"
```

---

## 阶段 3：后续版本（各自另写计划）

以下在检查点 A 委托方同意后，各写一份独立实施计划，复用本计划建立的 `v2/` 骨架与脚本：

- **B（不带摄像头 · 双面）**：新增 `placement_B.py`，`Variant.double_sided=True` 时 gen_pcb 按 spec 6 节把电源 / 功放 / 传感器芯片与阻容放背面；`export_fab.sh` 导出双面钢网与双面坐标；新增 `test_pcb_B.py`（正面只有模组、连接器、按键、指示灯）。
- **C / D（带摄像头）**：实现 `cam.camera_parts()`：J_CAM 用「焊盘号 → 摄像头脚号 → 信号」两级映射（焊盘 n 接摄像头第 25−n 脚，依据一期实测），MPR121（触摸 + 加热栅极 + 收音键 GPIO）、ADS1115（4 路 ADC）、LDO 2.8V/1.5V；`gpio.CAM` 已就绪。必须先写 spec 第 7 节第 2 条的映射断言测试，并完成第 3 条实物核对，才能出 C/D 生产文件。
- **固件 `plush-toy-v2`**：独立设计与计划；以 spec 第 5 节与本计划 `v2/gpio.py` 为接口。
