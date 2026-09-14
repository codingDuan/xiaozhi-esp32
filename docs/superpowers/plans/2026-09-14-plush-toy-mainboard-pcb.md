# plush-toy 4 层主板 PCB 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 产出一块 70×50mm、4 层、可在嘉立创打样贴片的 plush-toy 主板：KiCad 工程、ERC/DRC 零错误报告、Gerber/钻孔/BOM/坐标文件。

**Architecture:** 全板连接关系只写在一份 Python 数据文件 `board_spec.py` 里，它是唯一事实来源。单元测试对它机械地核对 `config.h` 引脚与六条硬约束。原理图（`.kicad_sch`，按网络标签连接）和 PCB（pcbnew SWIG 脚本放置 + Freerouting 自动布线 + 手工关键线）都从它生成。任何连接改动只改数据文件，重新生成，测试先行。

**Tech Stack:** KiCad 10.0.6（`kicad-cli`、自带 Python 3.9 的 `pcbnew` SWIG 绑定，KiCad 11 才移除）、Freerouting 2.4.1（class file 69，**需要 Java 25 及以上**，本机用 Homebrew `openjdk` 26）、Python 3 `unittest`。

> **实施修正（2026-09-14）**：原稿写 Java 21，实测 Freerouting 2.4.1 在 21 上报 `UnsupportedClassVersionError`，已改用 `$(brew --prefix openjdk)/bin/java`。KiCad 通过复制 dmg 安装（Homebrew cask 需要 sudo 建 `/Library/Application Support/kicad`，无法无人值守），`demos` 未随包安装，原理图格式版本改从 app 包内 `template` 读取。

**Spec:** `docs/superpowers/specs/2026-09-14-plush-toy-pcb-4layer-design.md`。第 12 节「器件定稿」优先于前文的选型要求。

## Global Constraints

- GPIO 分配与 `main/boards/plush-toy/config.h` 完全一致，不得改动任何一个。
- 板子外形 70×50mm 矩形，4 个 M3 安装孔。
- 叠层：L1 信号、L2 整层 GND、L3 电源、L4 信号加功率铺铜；板厚 1.6mm，按嘉立创 JLC04161H-7628。
- HC-1：`VBUS` 与 `VMOT` 正极之间无任何铜连接。
- HC-2：`PGND` 与 `GND` 只经一颗 0Ω 电阻（位号 `R_STAR`）在 `VMOT` 输入旁汇合。
- HC-3：加热 MOSFET 栅极 100kΩ 下拉到 `PGND`。
- HC-4：`GPIO45`、`GPIO46` 网络上不连接任何电阻到电源网络。
- HC-5：`I2C_SDA`、`I2C_SCL` 各有且仅有一颗 4.7kΩ 上拉到 `+3V3`。
- HC-6：加热插座旁丝印「必须串 KSD9700 65℃ 常闭」。
- 器件与外围取值以设计方案第 12 节为准。
- 工程目录：`hardware/plush-toy-mainboard/`；制造文件只放 `fab/`。
- 风险已由委托方接受：DRC 通过不等于电气性能达标，第一版预计需要改版。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `hardware/plush-toy-mainboard/scripts/board_spec.py` | 全部器件（位号、器件名、KiCad 符号、封装、LCSC 编号、是否贴）与连接（位号.引脚 → 网络名）。纯数据加少量辅助函数，不 import KiCad |
| `hardware/plush-toy-mainboard/scripts/config_pins.py` | 解析 `config.h` 的 GPIO 宏，返回 `{宏名: GPIO 号}` |
| `hardware/plush-toy-mainboard/scripts/test_board_spec.py` | 核对引脚、硬约束、网络完整性 |
| `hardware/plush-toy-mainboard/scripts/kicad_env.py` | 定位 KiCad 应用、`kicad-cli`、库目录；读取符号与封装定义 |
| `hardware/plush-toy-mainboard/scripts/gen_schematic.py` | 由 `board_spec` 生成 `plush-toy-mainboard.kicad_sch` |
| `hardware/plush-toy-mainboard/scripts/test_netlist_roundtrip.py` | 用 `kicad-cli` 从生成的原理图导出网表，与 `board_spec` 逐网络比对 |
| `hardware/plush-toy-mainboard/scripts/gen_pcb.py` | 用 KiCad 自带 Python 生成 `.kicad_pcb`：外框、叠层、器件、网络、放置、分区铺铜 |
| `hardware/plush-toy-mainboard/scripts/placement.py` | 每个位号的坐标、角度、所在面，按设计方案第 7 节分区 |
| `hardware/plush-toy-mainboard/scripts/route.sh` | 导出 DSN、调用 Freerouting、导回 SES |
| `hardware/plush-toy-mainboard/scripts/export_fab.sh` | ERC、DRC、Gerber、钻孔、BOM、坐标文件、渲染图 |

---

### Task 1: 工具链就位与库名核对

**Files:**
- Create: `hardware/plush-toy-mainboard/scripts/kicad_env.py`
- Create: `hardware/plush-toy-mainboard/scripts/test_kicad_env.py`

**Interfaces:**
- Produces: `kicad_env.KICAD_CLI: str`、`kicad_env.KICAD_PYTHON: str`、`kicad_env.SYMBOL_DIR: Path`、`kicad_env.FOOTPRINT_DIR: Path`、`kicad_env.symbol_exists(lib: str, name: str) -> bool`、`kicad_env.footprint_exists(lib: str, name: str) -> bool`、`kicad_env.SCH_FILE_VERSION: int`

- [ ] **Step 1: 安装 KiCad**

Run: `HOMEBREW_NO_AUTO_UPDATE=1 brew install --cask kicad`
Expected: 使用已缓存的 dmg，结尾出现 `kicad was successfully installed!`

- [ ] **Step 2: 确认命令行与自带 Python**

Run:
```bash
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli version
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -c "import pcbnew; print(pcbnew.Version())"
$(brew --prefix openjdk@21)/bin/java -version
```
Expected: 前两条都输出 `10.0.6`；Java 输出 `openjdk version "21`

- [ ] **Step 3: 写失败的测试**

```python
# hardware/plush-toy-mainboard/scripts/test_kicad_env.py
import unittest
import kicad_env

# 本工程要用到的官方库符号与封装。任何一项不存在，都要在 board_spec 里改用工程自带库。
REQUIRED_SYMBOLS = [
    ("RF_Module", "ESP32-S3-WROOM-1"),
    ("Driver_LED", "PCA9685PW"),
    ("Analog_ADC", "ADS1115IDGS"),
    ("Sensor_Motion", "MPU-6050"),
]
REQUIRED_FOOTPRINTS = [
    ("RF_Module", "ESP32-S3-WROOM-1"),
    ("Connector_USB", "USB_C_Receptacle_HRO_TYPE-C-31-M-12"),
    ("Package_TO_SOT_SMD", "SOT-23-5"),
    ("Package_TO_SOT_SMD", "SOT-23"),
    ("Package_DFN_QFN", "QFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.7mm"),
]


class KicadEnvTest(unittest.TestCase):
    def test_cli_and_python_exist(self):
        self.assertTrue(kicad_env.Path(kicad_env.KICAD_CLI).exists())
        self.assertTrue(kicad_env.Path(kicad_env.KICAD_PYTHON).exists())

    def test_required_symbols(self):
        for lib, name in REQUIRED_SYMBOLS:
            with self.subTest(lib=lib, name=name):
                self.assertTrue(kicad_env.symbol_exists(lib, name))

    def test_required_footprints(self):
        for lib, name in REQUIRED_FOOTPRINTS:
            with self.subTest(lib=lib, name=name):
                self.assertTrue(kicad_env.footprint_exists(lib, name))

    def test_schematic_version_read_from_bundled_demo(self):
        self.assertGreaterEqual(kicad_env.SCH_FILE_VERSION, 20250000)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: 运行，确认失败**

Run: `cd hardware/plush-toy-mainboard/scripts && python3 -m unittest test_kicad_env -v`
Expected: `ModuleNotFoundError: No module named 'kicad_env'`

- [ ] **Step 5: 实现**

```python
# hardware/plush-toy-mainboard/scripts/kicad_env.py
"""定位本机 KiCad 10 安装，并提供库查询。只读，不修改 KiCad 任何文件。"""
import re
from pathlib import Path

APP = Path("/Applications/KiCad/KiCad.app")
KICAD_CLI = str(APP / "Contents/MacOS/kicad-cli")
KICAD_PYTHON = str(APP / "Contents/Frameworks/Python.framework/Versions/Current/bin/python3")
SHARED = APP / "Contents/SharedSupport"
SYMBOL_DIR = SHARED / "symbols"
FOOTPRINT_DIR = SHARED / "footprints"


def symbol_exists(lib: str, name: str) -> bool:
    path = SYMBOL_DIR / f"{lib}.kicad_sym"
    if not path.exists():
        return False
    return f'(symbol "{name}"' in path.read_text(encoding="utf-8")


def footprint_exists(lib: str, name: str) -> bool:
    return (FOOTPRINT_DIR / f"{lib}.pretty" / f"{name}.kicad_mod").exists()


def _read_sch_version() -> int:
    # 不猜文件格式版本号：取 KiCad 自带示例工程里的实际值，保证生成的原理图能被这个版本打开。
    for sch in sorted((SHARED / "demos").rglob("*.kicad_sch")):
        m = re.search(r"\(version (\d+)\)", sch.read_text(encoding="utf-8", errors="ignore"))
        if m:
            return int(m.group(1))
    raise RuntimeError("KiCad 自带 demos 中找不到 .kicad_sch，无法确定文件格式版本")


SCH_FILE_VERSION = _read_sch_version()
```

- [ ] **Step 6: 运行，确认通过**

Run: `cd hardware/plush-toy-mainboard/scripts && python3 -m unittest test_kicad_env -v`
Expected: 4 条全部 `ok`。某个符号或封装报 FAIL 时，**不要改测试**：记下名字，在 KiCad 库目录里 `ls` 找到实际名称后改测试里的期望值；若官方库确实没有，把它加入 Task 4 的工程自带库清单。

- [ ] **Step 7: 提交**

```bash
git add hardware/plush-toy-mainboard/scripts/kicad_env.py hardware/plush-toy-mainboard/scripts/test_kicad_env.py
git commit -m "feat(pcb): KiCad 10 工具链定位与库名核对"
```

---

### Task 2: config.h 引脚解析

**Files:**
- Create: `hardware/plush-toy-mainboard/scripts/config_pins.py`
- Create: `hardware/plush-toy-mainboard/scripts/test_config_pins.py`

**Interfaces:**
- Produces: `config_pins.load(path: Path) -> dict[str, int]`，键为宏名（如 `"SERVO_I2C_SDA_PIN"`），值为 GPIO 号；`GPIO_NUM_NC` 的宏值为 `-1`。

- [ ] **Step 1: 写失败的测试**

```python
# hardware/plush-toy-mainboard/scripts/test_config_pins.py
import unittest
from pathlib import Path
import config_pins

CONFIG_H = Path(__file__).resolve().parents[3] / "main/boards/plush-toy/config.h"


class ConfigPinsTest(unittest.TestCase):
    def setUp(self):
        self.pins = config_pins.load(CONFIG_H)

    def test_known_values(self):
        self.assertEqual(self.pins["SERVO_I2C_SDA_PIN"], 44)
        self.assertEqual(self.pins["SERVO_I2C_SCL_PIN"], 3)
        self.assertEqual(self.pins["DISPLAY_CS_LEFT_PIN"], 45)
        self.assertEqual(self.pins["DISPLAY_CS_RIGHT_PIN"], 46)
        self.assertEqual(self.pins["CAMERA_PIN_XCLK"], 15)

    def test_nc_is_minus_one(self):
        self.assertEqual(self.pins["CAMERA_PIN_PWDN"], -1)
        self.assertEqual(self.pins["DISPLAY_BACKLIGHT_PIN"], -1)

    def test_comment_lines_ignored(self):
        self.assertNotIn("LAMP_GPIO", self.pins)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd hardware/plush-toy-mainboard/scripts && python3 -m unittest test_config_pins -v`
Expected: `ModuleNotFoundError: No module named 'config_pins'`

- [ ] **Step 3: 实现**

```python
# hardware/plush-toy-mainboard/scripts/config_pins.py
"""从固件 config.h 读取 GPIO 分配。PCB 的引脚只允许来自这里。"""
import re
from pathlib import Path

_DEFINE = re.compile(r"^\s*#define\s+(\w+)\s+GPIO_NUM_(\d+|NC)\b")


def load(path: Path) -> dict[str, int]:
    pins: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _DEFINE.match(line)
        if m:
            pins[m.group(1)] = -1 if m.group(2) == "NC" else int(m.group(2))
    return pins
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd hardware/plush-toy-mainboard/scripts && python3 -m unittest test_config_pins -v`
Expected: 3 条 `ok`

- [ ] **Step 5: 提交**

```bash
git add hardware/plush-toy-mainboard/scripts/config_pins.py hardware/plush-toy-mainboard/scripts/test_config_pins.py
git commit -m "feat(pcb): 解析 config.h GPIO 分配"
```

---

### Task 3: board_spec 数据模型与硬约束测试

**Files:**
- Create: `hardware/plush-toy-mainboard/scripts/board_spec.py`
- Create: `hardware/plush-toy-mainboard/scripts/test_board_spec.py`

**Interfaces:**
- Consumes: `config_pins.load`
- Produces:
  - `Part(ref: str, value: str, symbol: str, footprint: str, lcsc: str, fitted: bool, pins: dict[str, str])`，`pins` 为引脚号到网络名
  - `board_spec.PARTS: list[Part]`
  - `board_spec.GPIO_NET: dict[int, str]`，GPIO 号到网络名
  - `board_spec.nets() -> dict[str, list[tuple[str, str]]]`，网络名到 `(位号, 引脚号)` 列表
  - 网络名约定：电源 `+3V3`、`VBUS`、`VMOT`、`+2V8`、`+1V5`；地 `GND`、`PGND`；信号用大写蛇形，GPIO 信号带功能名（`I2C_SDA`、`LCD_CS_L`）

- [ ] **Step 1: 写失败的测试**

```python
# hardware/plush-toy-mainboard/scripts/test_board_spec.py
import unittest
from pathlib import Path
import board_spec
import config_pins

CONFIG_H = Path(__file__).resolve().parents[3] / "main/boards/plush-toy/config.h"

# config.h 宏 → 本板网络名。这张表本身就是 GPIO 分配的核对清单。
MACRO_TO_NET = {
    "AUDIO_I2S_MIC_GPIO_WS": "MIC_WS", "AUDIO_I2S_MIC_GPIO_SCK": "MIC_SCK",
    "AUDIO_I2S_MIC_GPIO_DIN": "MIC_SD", "AUDIO_I2S_SPK_GPIO_DOUT": "AMP_DIN",
    "AUDIO_I2S_SPK_GPIO_BCLK": "AMP_BCLK", "AUDIO_I2S_SPK_GPIO_LRCK": "AMP_LRCLK",
    "BUILTIN_LED_GPIO": "LED_RGB", "BOOT_BUTTON_GPIO": "BOOT",
    "CAMERA_PIN_D0": "CAM_Y2", "CAMERA_PIN_D1": "CAM_Y3", "CAMERA_PIN_D2": "CAM_Y4",
    "CAMERA_PIN_D3": "CAM_Y5", "CAMERA_PIN_D4": "CAM_Y6", "CAMERA_PIN_D5": "CAM_Y7",
    "CAMERA_PIN_D6": "CAM_Y8", "CAMERA_PIN_D7": "CAM_Y9", "CAMERA_PIN_XCLK": "CAM_XCLK",
    "CAMERA_PIN_PCLK": "CAM_PCLK", "CAMERA_PIN_VSYNC": "CAM_VSYNC", "CAMERA_PIN_HREF": "CAM_HREF",
    "CAMERA_PIN_SIOC": "CAM_SIOC", "CAMERA_PIN_SIOD": "CAM_SIOD",
    "DISPLAY_MOSI_PIN": "LCD_MOSI", "DISPLAY_CLK_PIN": "LCD_CLK", "DISPLAY_DC_PIN": "LCD_DC",
    "DISPLAY_RST_PIN": "LCD_RST", "DISPLAY_CS_LEFT_PIN": "LCD_CS_L", "DISPLAY_CS_RIGHT_PIN": "LCD_CS_R",
    "SERVO_I2C_SDA_PIN": "I2C_SDA", "SERVO_I2C_SCL_PIN": "I2C_SCL",
}
SUPPLIES = {"+3V3", "VBUS", "VMOT", "+2V8", "+1V5"}


def two_terminal(part):
    return len(part.pins) == 2


class GpioMatchesConfigTest(unittest.TestCase):
    def test_every_config_gpio_lands_on_its_net(self):
        pins = config_pins.load(CONFIG_H)
        for macro, net in MACRO_TO_NET.items():
            with self.subTest(macro=macro):
                self.assertEqual(board_spec.GPIO_NET[pins[macro]], net)

    def test_module_pins_follow_gpio_net(self):
        module = next(p for p in board_spec.PARTS if p.ref == "U1")
        for gpio, net in board_spec.GPIO_NET.items():
            with self.subTest(gpio=gpio):
                self.assertIn(net, module.pins.values())

    def test_flash_and_psram_gpios_unused(self):
        # GPIO26-37 在 N16R8 模组内部，模组焊盘只引出 35/36/37，且必须悬空
        for gpio in (35, 36, 37):
            self.assertNotIn(gpio, board_spec.GPIO_NET)


class HardConstraintTest(unittest.TestCase):
    def setUp(self):
        self.nets = board_spec.nets()
        self.fitted = [p for p in board_spec.PARTS if p.fitted]

    def test_hc1_no_part_bridges_vbus_and_vmot(self):
        for part in self.fitted:
            with self.subTest(ref=part.ref):
                self.assertFalse({"VBUS", "VMOT"} <= set(part.pins.values()))

    def test_hc2_single_star_link_between_pgnd_and_gnd(self):
        bridges = [p.ref for p in self.fitted if set(p.pins.values()) == {"GND", "PGND"}]
        self.assertEqual(bridges, ["R_STAR"])

    def test_hc3_heater_gate_pulldown(self):
        q = next(p for p in board_spec.PARTS if p.ref == "Q_HEAT")
        gate = q.pins["1"]
        pulldowns = [p for p in self.fitted if two_terminal(p)
                     and set(p.pins.values()) == {gate, "PGND"} and p.value == "100k"]
        self.assertEqual(len(pulldowns), 1)

    def test_hc4_no_pullup_on_strapping_cs(self):
        for net in ("LCD_CS_L", "LCD_CS_R"):
            for part in self.fitted:
                if two_terminal(part) and net in part.pins.values():
                    with self.subTest(net=net, ref=part.ref):
                        self.assertFalse(set(part.pins.values()) & SUPPLIES)

    def test_hc5_single_pullup_per_i2c_line(self):
        for net in ("I2C_SDA", "I2C_SCL"):
            ups = [p for p in self.fitted if two_terminal(p)
                   and set(p.pins.values()) == {net, "+3V3"}]
            with self.subTest(net=net):
                self.assertEqual(len(ups), 1)
                self.assertEqual(ups[0].value, "4.7k")


class NetIntegrityTest(unittest.TestCase):
    def test_no_single_pin_nets(self):
        for net, members in board_spec.nets().items():
            if net.startswith("NC_"):
                continue
            with self.subTest(net=net):
                self.assertGreaterEqual(len(members), 2)

    def test_refs_unique(self):
        refs = [p.ref for p in board_spec.PARTS]
        self.assertEqual(len(refs), len(set(refs)))

    def test_every_fitted_part_has_lcsc_code(self):
        for part in board_spec.PARTS:
            if part.fitted and not part.ref.startswith(("J_", "TP", "H")):
                with self.subTest(ref=part.ref):
                    self.assertRegex(part.lcsc, r"^C\d+$")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd hardware/plush-toy-mainboard/scripts && python3 -m unittest test_board_spec -v`
Expected: `ModuleNotFoundError: No module named 'board_spec'`

- [ ] **Step 3: 写数据模型骨架与模组**

```python
# hardware/plush-toy-mainboard/scripts/board_spec.py
"""plush-toy 主板的全部器件与连接。原理图和 PCB 都从这里生成，改连接只改这里。

引脚号一律来自原厂数据手册，出处写在每个器件旁。取值见设计方案第 12 节。
"""
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


# GPIO → 网络。键集合必须与 test_board_spec.MACRO_TO_NET 覆盖的 GPIO 一致，
# 另加 USB（19/20）与控制台 TX（43，引到测试点）。
GPIO_NET = {
    1: "MIC_WS", 2: "MIC_SCK", 3: "I2C_SCL", 4: "CAM_SIOD", 5: "CAM_SIOC",
    6: "CAM_VSYNC", 7: "CAM_HREF", 8: "CAM_Y4", 9: "CAM_Y3", 10: "CAM_Y5",
    11: "CAM_Y2", 12: "CAM_Y6", 13: "CAM_PCLK", 14: "LCD_MOSI", 15: "CAM_XCLK",
    16: "CAM_Y9", 17: "CAM_Y8", 18: "CAM_Y7", 19: "USB_DN", 20: "USB_DP",
    21: "LCD_RST", 38: "LCD_CLK", 39: "AMP_DIN", 40: "AMP_BCLK", 41: "AMP_LRCLK",
    42: "MIC_SD", 43: "UART_TX", 44: "I2C_SDA", 45: "LCD_CS_L", 46: "LCD_CS_R",
    47: "LCD_DC", 48: "LED_RGB", 0: "BOOT",
}

# ESP32-S3-WROOM-1 模组焊盘号 → GPIO，出自 esp32-s3-wroom-1_wroom-1u_datasheet_en v1.8 表 3-1
_WROOM_PAD_GPIO = {
    "4": 4, "5": 5, "6": 6, "7": 7, "8": 15, "9": 16, "10": 17, "11": 18, "12": 8,
    "13": 19, "14": 20, "15": 3, "16": 46, "17": 9, "18": 10, "19": 11, "20": 12,
    "21": 13, "22": 14, "23": 21, "24": 47, "25": 48, "26": 45, "27": 0,
    "31": 38, "32": 39, "33": 40, "34": 41, "35": 42, "36": 44, "37": 43, "38": 2, "39": 1,
}

_u1_pins = {"1": "GND", "2": "+3V3", "3": "EN", "40": "GND", "41": "GND",
            "28": "NC_IO35", "29": "NC_IO36", "30": "NC_IO37"}
_u1_pins.update({pad: GPIO_NET[g] for pad, g in _WROOM_PAD_GPIO.items()})

PARTS: list[Part] = [
    Part("U1", "ESP32-S3-WROOM-1-N16R8", "RF_Module:ESP32-S3-WROOM-1",
         "RF_Module:ESP32-S3-WROOM-1", "C2913202", pins=_u1_pins),
]


def nets() -> dict[str, list[tuple[str, str]]]:
    result: dict[str, list[tuple[str, str]]] = {}
    for part in PARTS:
        if not part.fitted:
            continue
        for pin, net in part.pins.items():
            result.setdefault(net, []).append((part.ref, pin))
    return result
```

- [ ] **Step 4: 按设计方案逐块补全 PARTS，每补一块跑一次测试**

每一块的器件、引脚号、取值**只从设计方案第 12 节和第 5.2、6.4 至 6.10 节的表格抄**，不得凭记忆。LCSC 编号在嘉立创零件库逐个核对，搜到的编号与第 12 节已列的冲突时以第 12 节为准。顺序与每块的验收条件：

| 块 | 位号 | 补完后应转绿的测试 |
|---|---|---|
| EN 复位与 BOOT | `R_EN` 10k、`C_EN` 1µF、`SW_RST`、`SW_BOOT` | `test_module_pins_follow_gpio_net` 中 `EN`、`BOOT` 不再是单引脚网络 |
| USB-C 与 ESD | `J_USB`（TYPE-C-31-M-12，CC1/CC2 各 5.1k 到 GND）、`F_USB`、`D_USB_DP`、`D_USB_DN` | `USB_DP`、`USB_DN`、`VBUS` 通过 `test_no_single_pin_nets` |
| 3V3 降压 | `U_BUCK` SY8089AAAC 与第 12.1 节全部外围 | `+3V3` 连到 U1 |
| 功率输入与星形地 | `J_VMOT`、`D_VMOT_TVS`、`Q_REV`（防反接 P-MOS）、`C_VMOT_BULK` 1000µF、`R_STAR` 0Ω | `test_hc1`、`test_hc2` |
| 主 I2C | `R_SDA`、`R_SCL` 各 4.7k | `test_hc5` |
| PCA9685 与舵机、加热 | `U_PWM`（V+ 取 VMOT，OE 经 10k 到 GND 并留测试点）、`J_SERVO_L`、`J_SERVO_R`、`Q_HEAT`、`R_GATE` 100Ω、`R_GATE_PD` 100k、`J_HEAT` | `test_hc3` |
| ADS1115 与 NTC | `U_ADC`、`R_NTC` 10k 1%、`C_NTC` 0.1µF C0G、`J_NTC`；A1 分压两颗 `fitted=False` | `test_no_single_pin_nets` |
| MPR121 | `U_TOUCH` 与 12 路电极焊盘 | 同上 |
| MPU-6050 | `U_IMU` | 同上 |
| 摄像头 | `J_CAM` 按第 12.2 节 24 针表；`U_LDO28`、`U_LDO15`；PWDN 10k 下拉、RESET 10k 上拉 + 0.1µF | `test_every_config_gpio_lands_on_its_net` 中 CAM 各项 |
| 双屏 | `J_LCD_L`、`J_LCD_R` 各 7 针；`R_LCD_CLK`、`R_LCD_MOSI` 各 33Ω | `test_hc4` 与 LCD 各项 |
| 音频 | `U_MIC` INMP441、`U_AMP` MAX98357A 与第 12.3 节外围、`J_SPK` | MIC/AMP 各项 |
| 测试点与安装孔 | 第 9 节测试点清单、`H1` 至 `H4` | 全部测试 |

Run（每块之后）: `cd hardware/plush-toy-mainboard/scripts && python3 -m unittest test_board_spec -v`

- [ ] **Step 5: 全部测试通过**

Run: `cd hardware/plush-toy-mainboard/scripts && python3 -m unittest discover -p "test_*.py" -v`
Expected: 全部 `ok`，无 skip。

- [ ] **Step 6: 提交**

```bash
git add hardware/plush-toy-mainboard/scripts/board_spec.py hardware/plush-toy-mainboard/scripts/test_board_spec.py
git commit -m "feat(pcb): 主板器件与连接数据，含 config.h 与六条硬约束核对"
```

---

### Task 4: 生成原理图并做网表回环核对

**Files:**
- Create: `hardware/plush-toy-mainboard/scripts/gen_schematic.py`
- Create: `hardware/plush-toy-mainboard/scripts/test_netlist_roundtrip.py`
- Create: `hardware/plush-toy-mainboard/plush-toy-mainboard.kicad_pro`（生成）
- Create: `hardware/plush-toy-mainboard/plush-toy-mainboard.kicad_sch`（生成）

**Interfaces:**
- Consumes: `board_spec.PARTS`、`board_spec.nets()`、`kicad_env.SYMBOL_DIR`、`kicad_env.SCH_FILE_VERSION`、`kicad_env.KICAD_CLI`
- Produces: `gen_schematic.main() -> Path`，返回生成的 `.kicad_sch` 路径

- [ ] **Step 1: 写失败的测试**

```python
# hardware/plush-toy-mainboard/scripts/test_netlist_roundtrip.py
"""原理图是生成物，必须证明它和 board_spec 等价：导出网表逐网络比对。"""
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import board_spec
import gen_schematic
import kicad_env


class NetlistRoundTripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sch = gen_schematic.main()
        out = Path(tempfile.mkdtemp()) / "net.xml"
        subprocess.run([kicad_env.KICAD_CLI, "sch", "export", "netlist",
                        "--format", "kicadxml", "-o", str(out), str(sch)], check=True)
        cls.exported = {}
        for net in ET.parse(out).getroot().iter("net"):
            members = sorted((n.get("ref"), n.get("pin")) for n in net.iter("node"))
            cls.exported[net.get("name").lstrip("/")] = members

    def test_every_spec_net_exported_identically(self):
        for name, members in board_spec.nets().items():
            if name.startswith("NC_"):
                continue
            with self.subTest(net=name):
                self.assertEqual(self.exported.get(name), sorted(members))

    def test_erc_has_no_errors(self):
        sch = gen_schematic.main()
        report = Path(tempfile.mkdtemp()) / "erc.json"
        subprocess.run([kicad_env.KICAD_CLI, "sch", "erc", "--format", "json",
                        "--severity-error", "-o", str(report), str(sch)], check=False)
        import json
        violations = [v for s in json.loads(report.read_text())["sheets"] for v in s["violations"]]
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd hardware/plush-toy-mainboard/scripts && python3 -m unittest test_netlist_roundtrip -v`
Expected: `ModuleNotFoundError: No module named 'gen_schematic'`

- [ ] **Step 3: 实现生成器**

> **实施修正（2026-09-14）**：下方代码是计划稿，实际实现以 `scripts/gen_schematic.py` 为准。与计划稿的差异：
> - 用本地 `label` 而非 `global_label`：单页原理图同名本地标签即相连，且语法照 KiCad 10 template 实际写法。
> - `lib_symbols` 中的符号必须展平：派生符号（`extends`，如 ADS1115IDGS、ME6211C28M5、TLV62569DBV、AO3400A）从父符号展开。
> - 每个放置的符号带 `instances` 块，否则网表里位号退化为 U?、R?。
> - 有电源输入引脚、但无电源输出引脚驱动的网络补 `PWR_FLAG`（#FLG），否则 ERC 报错。
> - 标签按引脚方向朝外伸出，不压住引脚名；锚点仍在引脚末端。
> - 网表比对忽略 # 开头的虚拟符号与不贴件（原理图保留不贴件以便改版补焊）。
> - 新增反向核对 `test_no_extra_connections` 与位号保持核对 `test_every_part_keeps_its_reference`。

生成策略：每个器件实例放在网格上，**每个引脚末端放一个同名全局网络标签**，不画导线。这样连接关系完全由标签名决定，与 `board_spec` 一一对应，人看原理图时按标签名跟网络。

```python
# hardware/plush-toy-mainboard/scripts/gen_schematic.py
import re
import uuid
from pathlib import Path

import board_spec
import kicad_env

ROOT = Path(__file__).resolve().parents[1]
SCH = ROOT / "plush-toy-mainboard.kicad_sch"
PRO = ROOT / "plush-toy-mainboard.kicad_pro"
GRID = 2.54


def _uid() -> str:
    return str(uuid.uuid4())


def _extract_symbol(lib: str, name: str) -> str:
    """从官方 .kicad_sym 中截取完整的 (symbol "name" ...) 块，括号配平截取。"""
    text = (kicad_env.SYMBOL_DIR / f"{lib}.kicad_sym").read_text(encoding="utf-8")
    start = text.index(f'(symbol "{name}"')
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                block = text[start:i + 1]
                return block.replace(f'(symbol "{name}"', f'(symbol "{lib}:{name}"', 1)
    raise ValueError(f"符号 {lib}:{name} 括号不配平")


def _pin_positions(symbol_block: str) -> dict[str, tuple[float, float, float]]:
    """引脚号 → (x, y, 角度)，坐标相对符号原点。只取第一个 unit 与默认 body style。"""
    pins = {}
    for m in re.finditer(r'\(pin \w+ \w+\s*\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\).*?\(number "([^"]+)"',
                         symbol_block, re.S):
        pins.setdefault(m.group(4), (float(m.group(1)), float(m.group(2)), float(m.group(3))))
    return pins


def main() -> Path:
    lib_blocks, placed = {}, []
    for index, part in enumerate(board_spec.PARTS):
        lib, name = part.symbol.split(":", 1)
        if part.symbol not in lib_blocks:
            lib_blocks[part.symbol] = _extract_symbol(lib, name)
        x = 25.4 + (index % 6) * 60 * GRID / 2.54
        y = 25.4 + (index // 6) * 60 * GRID / 2.54
        placed.append((part, x, y))

    out = [f'(kicad_sch (version {kicad_env.SCH_FILE_VERSION}) (generator "plush_gen")',
           f'  (uuid "{_uid()}") (paper "A1")', "  (lib_symbols"]
    out += [f"    {b}" for b in lib_blocks.values()]
    out.append("  )")
    for part, x, y in placed:
        pins = _pin_positions(lib_blocks[part.symbol])
        out.append(f'  (symbol (lib_id "{part.symbol}") (at {x:.2f} {y:.2f} 0) (unit 1)'
                   f' (in_bom yes) (on_board yes) (dnp {"no" if part.fitted else "yes"})'
                   f' (uuid "{_uid()}")')
        out.append(f'    (property "Reference" "{part.ref}" (at {x:.2f} {y - 5:.2f} 0))')
        out.append(f'    (property "Value" "{part.value}" (at {x:.2f} {y + 5:.2f} 0))')
        out.append(f'    (property "Footprint" "{part.footprint}" (at {x:.2f} {y:.2f} 0) (hide yes))')
        out.append(f'    (property "LCSC" "{part.lcsc}" (at {x:.2f} {y:.2f} 0) (hide yes))')
        out.append("  )")
        for number, net in part.pins.items():
            px, py, _ = pins[number]
            # 符号坐标 y 轴向上，原理图坐标 y 轴向下
            out.append(f'  (global_label "{net}" (shape passive) (at {x + px:.2f} {y - py:.2f} 0)'
                       f' (uuid "{_uid()}"))')
    out.append(")")
    SCH.write_text("\n".join(out) + "\n", encoding="utf-8")
    if not PRO.exists():
        PRO.write_text("{}\n", encoding="utf-8")
    return SCH


if __name__ == "__main__":
    print(main())
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd hardware/plush-toy-mainboard/scripts && python3 -m unittest test_netlist_roundtrip -v`
Expected: 2 条 `ok`。网络比对失败时，打印差异，**只改生成器**，不改 `board_spec` 去迁就生成器。ERC 报 `pin_not_connected` 时，把该引脚在 `board_spec` 里显式接到 `NC_` 前缀网络，生成器对 `NC_` 网络放 no_connect 标记而非标签。

- [ ] **Step 5: 导出原理图 PDF 给委托方过目**

Run: `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli sch export pdf -o hardware/plush-toy-mainboard/renders/schematic.pdf hardware/plush-toy-mainboard/plush-toy-mainboard.kicad_sch`
Expected: 生成 PDF。**停下，等委托方对照实物确认摄像头 FPC 与屏幕 7 针顺序**后再做 Task 5。

- [ ] **Step 6: 提交**

```bash
git add hardware/plush-toy-mainboard/scripts/gen_schematic.py hardware/plush-toy-mainboard/scripts/test_netlist_roundtrip.py hardware/plush-toy-mainboard/*.kicad_pro hardware/plush-toy-mainboard/*.kicad_sch hardware/plush-toy-mainboard/renders/schematic.pdf
git commit -m "feat(pcb): 由 board_spec 生成原理图，网表回环与 ERC 零错误"
```

---

### Task 5: PCB 外框、叠层、器件放置

**Files:**
- Create: `hardware/plush-toy-mainboard/scripts/placement.py`
- Create: `hardware/plush-toy-mainboard/scripts/gen_pcb.py`
- Create: `hardware/plush-toy-mainboard/scripts/test_pcb.py`
- Create: `hardware/plush-toy-mainboard/plush-toy-mainboard.kicad_pcb`（生成）

**Interfaces:**
- Consumes: `board_spec.PARTS`、`board_spec.nets()`、`kicad_env.FOOTPRINT_DIR`
- Produces: `placement.PLACE: dict[str, tuple[float, float, float, str]]`（位号 → x mm、y mm、角度、`"F"`/`"B"`）；`gen_pcb.py` 以 `KICAD_PYTHON gen_pcb.py` 运行，生成 `.kicad_pcb`

- [ ] **Step 1: 写失败的测试**

```python
# hardware/plush-toy-mainboard/scripts/test_pcb.py
"""用 KiCad 自带 Python 运行：KICAD_PYTHON -m unittest test_pcb"""
import unittest
from pathlib import Path

import pcbnew
import board_spec
import placement

PCB = Path(__file__).resolve().parents[1] / "plush-toy-mainboard.kicad_pcb"


class PcbTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = pcbnew.LoadBoard(str(PCB))

    def test_outline_is_70_by_50(self):
        box = self.board.GetBoardEdgesBoundingBox()
        self.assertAlmostEqual(pcbnew.ToMM(box.GetWidth()), 70.0, delta=0.2)
        self.assertAlmostEqual(pcbnew.ToMM(box.GetHeight()), 50.0, delta=0.2)

    def test_four_copper_layers(self):
        self.assertEqual(self.board.GetCopperLayerCount(), 4)

    def test_every_fitted_part_placed_inside_outline(self):
        box = self.board.GetBoardEdgesBoundingBox()
        refs = {fp.GetReference(): fp for fp in self.board.GetFootprints()}
        for part in board_spec.PARTS:
            if part.fitted:
                with self.subTest(ref=part.ref):
                    self.assertIn(part.ref, refs)
                    self.assertTrue(box.Contains(refs[part.ref].GetPosition()))

    def test_pad_nets_match_spec(self):
        refs = {fp.GetReference(): fp for fp in self.board.GetFootprints()}
        for part in board_spec.PARTS:
            if not part.fitted:
                continue
            for pad in refs[part.ref].Pads():
                expected = part.pins.get(pad.GetNumber())
                if expected and not expected.startswith("NC_"):
                    with self.subTest(ref=part.ref, pad=pad.GetNumber()):
                        self.assertEqual(pad.GetNetname(), expected)

    def test_antenna_and_power_zones_at_opposite_ends(self):
        u1 = placement.PLACE["U1"][0]
        q = placement.PLACE["Q_HEAT"][0]
        self.assertLess(u1, 20.0)
        self.assertGreater(q, 50.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd hardware/plush-toy-mainboard/scripts && /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_pcb -v`
Expected: `ModuleNotFoundError: No module named 'placement'`

- [ ] **Step 3: 写放置表**

按设计方案第 7 节分区。坐标原点在板子左上角，x 向右，y 向下，单位 mm。天线在 x=0 一端并伸出板边 3mm；功率区在 x≥50。

```python
# hardware/plush-toy-mainboard/scripts/placement.py
# 位号: (x, y, 角度, 面)。第一版手工放置，布线后按 DRC 与渲染图调整。
PLACE = {
    "U1": (9.0, 25.0, 90.0, "F"),        # 模组竖放，天线朝 x=0 伸出板边
    "J_USB": (22.0, 3.5, 180.0, "F"),
    "U_BUCK": (28.0, 8.0, 0.0, "F"),
    "J_CAM": (24.0, 46.0, 0.0, "F"),
    "U_LDO28": (30.0, 40.0, 0.0, "F"),
    "U_LDO15": (30.0, 44.0, 0.0, "F"),
    "J_LCD_L": (36.0, 4.0, 0.0, "F"),
    "J_LCD_R": (46.0, 4.0, 0.0, "F"),
    "U_MIC": (40.0, 47.0, 0.0, "B"),     # 底面，板上开声孔
    "R_SDA": (22.0, 20.0, 0.0, "F"),
    "R_SCL": (22.0, 22.0, 0.0, "F"),
    "U_TOUCH": (33.0, 16.0, 0.0, "F"),
    "U_IMU": (35.0, 25.0, 0.0, "F"),     # 板中部
    "U_ADC": (42.0, 33.0, 0.0, "F"),
    "R_NTC": (39.0, 33.0, 90.0, "F"),
    "C_NTC": (39.0, 36.0, 90.0, "F"),
    "U_PWM": (44.0, 20.0, 0.0, "F"),
    "R_STAR": (52.0, 25.0, 90.0, "F"),
    "J_VMOT": (66.0, 6.0, 90.0, "F"),
    "C_VMOT_BULK": (60.0, 10.0, 0.0, "F"),
    "J_SERVO_L": (66.0, 18.0, 90.0, "F"),
    "J_SERVO_R": (66.0, 27.0, 90.0, "F"),
    "Q_HEAT": (58.0, 36.0, 0.0, "F"),
    "R_GATE": (55.0, 36.0, 90.0, "F"),
    "R_GATE_PD": (55.0, 39.0, 90.0, "F"),
    "J_HEAT": (66.0, 38.0, 90.0, "F"),
    "J_NTC": (66.0, 46.0, 90.0, "F"),
    "U_AMP": (52.0, 46.0, 0.0, "F"),
    "J_SPK": (60.0, 46.0, 0.0, "F"),
    "H1": (3.5, 3.5, 0.0, "F"), "H2": (66.5, 3.5, 0.0, "F"),
    "H3": (3.5, 46.5, 0.0, "F"), "H4": (66.5, 46.5, 0.0, "F"),
}
```

Task 3 补全的其余位号（去耦电容、电阻、测试点）按「紧贴所服务芯片的电源引脚」原则追加到 `PLACE`，每个坐标距对应芯片中心不超过 4mm。`test_every_fitted_part_placed_inside_outline` 会抓出遗漏。

- [ ] **Step 4: 实现 PCB 生成**

```python
# hardware/plush-toy-mainboard/scripts/gen_pcb.py
"""用 KiCad 自带 Python 运行。生成外框、4 层叠层、器件、网络、分区铺铜。"""
from pathlib import Path

import pcbnew
import board_spec
import kicad_env
from placement import PLACE

ROOT = Path(__file__).resolve().parents[1]
PCB = ROOT / "plush-toy-mainboard.kicad_pcb"
W, H = 70.0, 50.0


def mm(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def add_outline(board):
    corners = [(0, 0), (W, 0), (W, H), (0, H)]
    for (x1, y1), (x2, y2) in zip(corners, corners[1:] + corners[:1]):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(mm(x1, y1))
        seg.SetEnd(mm(x2, y2))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(pcbnew.FromMM(0.1))
        board.Add(seg)


def add_zone(board, net_name, layer, rect):
    x1, y1, x2, y2 = rect
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    zone.SetNet(board.FindNet(net_name))
    outline = zone.Outline()
    outline.NewOutline()
    for x, y in [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]:
        outline.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    board.Add(zone)


def main():
    board = pcbnew.NewBoard(str(PCB))
    board.SetCopperLayerCount(4)
    add_outline(board)

    for name in board_spec.nets():
        board.Add(pcbnew.NETINFO_ITEM(board, name))

    for part in board_spec.PARTS:
        if not part.fitted:
            continue
        lib, name = part.footprint.split(":", 1)
        fp = pcbnew.FootprintLoad(str(kicad_env.FOOTPRINT_DIR / f"{lib}.pretty"), name)
        fp.SetReference(part.ref)
        fp.SetValue(part.value)
        x, y, angle, side = PLACE[part.ref]
        fp.SetPosition(mm(x, y))
        fp.SetOrientationDegrees(angle)
        board.Add(fp)
        if side == "B":
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        for pad in fp.Pads():
            net = part.pins.get(pad.GetNumber())
            if net and not net.startswith("NC_"):
                pad.SetNet(board.FindNet(net))

    # L2 整层 GND；L3 的 3V3 主平面避开功率区；L4 功率区铺 PGND 与 VMOT
    add_zone(board, "GND", pcbnew.In1_Cu, (0, 0, W, H))
    add_zone(board, "+3V3", pcbnew.In2_Cu, (0, 0, 48, H))
    add_zone(board, "PGND", pcbnew.B_Cu, (50, 0, W, H))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(PCB))
    print(PCB)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 生成并运行测试**

Run:
```bash
cd hardware/plush-toy-mainboard/scripts
KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
$KP gen_pcb.py && $KP -m unittest test_pcb -v
```
Expected: 5 条 `ok`。

- [ ] **Step 6: 渲染四层与 3D 给委托方过目**

Run:
```bash
KC=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
PCB=hardware/plush-toy-mainboard/plush-toy-mainboard.kicad_pcb
for L in F.Cu In1.Cu In2.Cu B.Cu; do $KC pcb export svg --layers "$L,Edge.Cuts" -o hardware/plush-toy-mainboard/renders/place_$L.svg $PCB; done
$KC pcb render --side top -o hardware/plush-toy-mainboard/renders/place_top.png $PCB
```
Expected: 4 张 SVG、1 张 PNG。**先自己用 Read 看 PNG 检查器件是否重叠、天线是否伸出板边**，再发给委托方。

- [ ] **Step 7: 提交**

```bash
git add hardware/plush-toy-mainboard/scripts/placement.py hardware/plush-toy-mainboard/scripts/gen_pcb.py hardware/plush-toy-mainboard/scripts/test_pcb.py hardware/plush-toy-mainboard/plush-toy-mainboard.kicad_pcb hardware/plush-toy-mainboard/renders/place_*
git commit -m "feat(pcb): 外框、4 层叠层、器件放置与分区铺铜"
```

---

### Task 6: 布线与 DRC

**Files:**
- Create: `hardware/plush-toy-mainboard/scripts/route.sh`
- Create: `hardware/plush-toy-mainboard/scripts/test_drc.py`
- Modify: `hardware/plush-toy-mainboard/plush-toy-mainboard.kicad_pcb`

**Interfaces:**
- Consumes: Task 5 生成的 `.kicad_pcb`、`tools/freerouting-2.4.1.jar`
- Produces: 布线完成、DRC 零错误的 `.kicad_pcb`

- [ ] **Step 1: 写失败的测试**

```python
# hardware/plush-toy-mainboard/scripts/test_drc.py
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import kicad_env

PCB = Path(__file__).resolve().parents[1] / "plush-toy-mainboard.kicad_pcb"


class DrcTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        report = Path(tempfile.mkdtemp()) / "drc.json"
        subprocess.run([kicad_env.KICAD_CLI, "pcb", "drc", "--format", "json",
                        "--schematic-parity", "--refill-zones",
                        "--severity-error", "-o", str(report), str(PCB)], check=False)
        cls.report = json.loads(report.read_text())

    def test_no_drc_errors(self):
        self.assertEqual(self.report["violations"], [])

    def test_no_unconnected_items(self):
        self.assertEqual(self.report["unconnected_items"], [])

    def test_schematic_parity(self):
        self.assertEqual(self.report.get("schematic_parity", []), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd hardware/plush-toy-mainboard/scripts && python3 -m unittest test_drc -v`
Expected: `test_no_unconnected_items` FAIL，未布线网络数大于 0。

- [ ] **Step 3: 手工先布关键线**

在 KiCad 图形界面里打开 `.kicad_pcb`，**自动布线前**先手工布这几类线，并在 Freerouting 里锁定：
1. `USB_DP` / `USB_DN`：L1 差分对，线宽与间距用嘉立创阻抗计算器按 JLC04161H-7628 的 90Ω 差分结果。
2. `CAM_XCLK`：L1，两侧包 GND 并每隔 3mm 打地过孔。
3. `CAM_Y2`–`CAM_Y9` 与 `CAM_PCLK`：L1，等长误差 ≤ 5mm。
4. `VMOT`、`PGND` 到舵机座与 `J_HEAT`、`Q_HEAT`：线宽 ≥ 1.5mm。
5. `LX`（降压开关节点）：尽量短，不与任何信号线平行。

- [ ] **Step 4: 实现自动布线脚本**

```bash
#!/usr/bin/env bash
# hardware/plush-toy-mainboard/scripts/route.sh
# 导出 Specctra DSN → Freerouting 自动布线 → 导回 SES。已手工锁定的线保持不动。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
JAVA="$(brew --prefix openjdk@21)/bin/java"
JAR="$ROOT/tools/freerouting-2.4.1.jar"
PCB="$ROOT/plush-toy-mainboard.kicad_pcb"
DSN="$ROOT/build/board.dsn"
SES="$ROOT/build/board.ses"
mkdir -p "$ROOT/build"

"$KP" -c "import pcbnew; b=pcbnew.LoadBoard('$PCB'); assert pcbnew.ExportSpecctraDSN(b, '$DSN')"
"$JAVA" -jar "$JAR" -de "$DSN" -do "$SES" -mp 20 -host "plush_gen"
"$KP" -c "import pcbnew; b=pcbnew.LoadBoard('$PCB'); assert pcbnew.ImportSpecctraSES(b, '$SES'); pcbnew.ZONE_FILLER(b).Fill(b.Zones()); b.Save('$PCB')"
echo "routed: $PCB"
```

- [ ] **Step 5: 布线并跑 DRC**

Run:
```bash
mkdir -p hardware/plush-toy-mainboard/tools
cp /private/tmp/claude-501/-Users-lianjia-Workspace-xiaozhi-esp32/83ed14f1-838a-4bd8-b999-4f58fd4e8d63/scratchpad/tools/freerouting-2.4.1.jar hardware/plush-toy-mainboard/tools/
bash hardware/plush-toy-mainboard/scripts/route.sh
cd hardware/plush-toy-mainboard/scripts && python3 -m unittest test_drc -v
```
Expected: 3 条 `ok`。DRC 有错误时逐条修，**不得用放宽规则的方式消除错误**；修改只能是移动器件、改手工线、调整铺铜。每修一轮重跑 `route.sh` 与测试。

- [ ] **Step 6: 硬约束的几何复查**

Run: `KP=...; $KP -c "import pcbnew; b=pcbnew.LoadBoard('hardware/plush-toy-mainboard/plush-toy-mainboard.kicad_pcb'); print(sorted({t.GetNetname() for t in b.GetTracks() if t.GetLayer()==pcbnew.In1_Cu}))"`
Expected: 输出只有 `['GND']` 或空列表，证明 L2 没被信号线切断。

- [ ] **Step 7: 提交**

```bash
git add hardware/plush-toy-mainboard/scripts/route.sh hardware/plush-toy-mainboard/scripts/test_drc.py hardware/plush-toy-mainboard/plush-toy-mainboard.kicad_pcb
git commit -m "feat(pcb): 关键线手工布线 + Freerouting 自动布线，DRC 零错误"
```

---

### Task 7: 制造文件与交付

**Files:**
- Create: `hardware/plush-toy-mainboard/scripts/export_fab.sh`
- Create: `hardware/plush-toy-mainboard/fab/`（生成）
- Modify: `hardware/plush-toy-mainboard/README.md`

**Interfaces:**
- Consumes: Task 6 的 `.kicad_pcb`、Task 4 的 `.kicad_sch`
- Produces: `fab/gerber.zip`、`fab/bom.csv`、`fab/positions.csv`、`renders/final_top.png`、`renders/final_bottom.png`

- [ ] **Step 1: 实现导出脚本**

```bash
#!/usr/bin/env bash
# hardware/plush-toy-mainboard/scripts/export_fab.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KC=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
PCB="$ROOT/plush-toy-mainboard.kicad_pcb"
SCH="$ROOT/plush-toy-mainboard.kicad_sch"
FAB="$ROOT/fab"
rm -rf "$FAB" && mkdir -p "$FAB/gerber"

$KC pcb export gerbers --layers "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts" -o "$FAB/gerber/" "$PCB"
$KC pcb export drill --format excellon --excellon-separate-th -o "$FAB/gerber/" "$PCB"
(cd "$FAB/gerber" && zip -q ../gerber.zip ./*)
$KC sch export bom --fields "Reference,Value,Footprint,LCSC,\${QUANTITY},\${DNP}" --group-by "Value,Footprint,LCSC" --exclude-dnp -o "$FAB/bom.csv" "$SCH"
$KC pcb export pos --format csv --units mm --side both -o "$FAB/positions.csv" "$PCB"
$KC pcb render --side top -o "$ROOT/renders/final_top.png" "$PCB"
$KC pcb render --side bottom -o "$ROOT/renders/final_bottom.png" "$PCB"
echo "fab files in $FAB"
```

- [ ] **Step 2: 导出并核对**

Run:
```bash
bash hardware/plush-toy-mainboard/scripts/export_fab.sh
unzip -l hardware/plush-toy-mainboard/fab/gerber.zip
```
Expected: zip 中含 4 个铜层（`F_Cu`、`In1_Cu`、`In2_Cu`、`B_Cu`）、2 个阻焊、2 个丝印、2 个钢网、1 个 `Edge_Cuts`、钻孔文件。

- [ ] **Step 3: 看最终渲染图**

用 Read 打开 `renders/final_top.png` 和 `renders/final_bottom.png`，逐项检查：天线伸出板边且下方无铜；`J_HEAT` 旁丝印有「必须串 KSD9700 65℃ 常闭」；两个电源输入的极性标识清楚。缺丝印就在 `gen_pcb.py` 里用 `PCB_TEXT` 加上，重新生成、布线、导出。

- [ ] **Step 4: 全量回归**

Run:
```bash
cd hardware/plush-toy-mainboard/scripts
python3 -m unittest test_kicad_env test_config_pins test_board_spec test_netlist_roundtrip test_drc -v
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_pcb -v
```
Expected: 全部 `ok`。

- [ ] **Step 5: 更新 README 状态表并提交**

README 状态表全部改为「完成」，写明产物路径，以及「首板上电按设计方案第 9 节顺序」。

```bash
git add hardware/plush-toy-mainboard/scripts/export_fab.sh hardware/plush-toy-mainboard/fab hardware/plush-toy-mainboard/renders hardware/plush-toy-mainboard/README.md
git commit -m "feat(pcb): 制造文件、BOM、坐标文件与最终渲染"
```

---

## Self-Review 记录

- **Spec 覆盖**：
  - 硬约束 HC-1 到 HC-5 → Task 3 测试；HC-6 丝印 → Task 7 Step 3。
  - 叠层 → Task 5 `SetCopperLayerCount(4)` 与分区铺铜。
  - 各接口布线要求（6.3 至 6.10 节）→ Task 6 Step 3 手工关键线。
  - 布局分区（第 7 节）→ Task 5 放置表与 `test_antenna_and_power_zones_at_opposite_ends`。
  - 引脚总表（第 8 节）→ Task 2、3。
  - 交付物（10.3 节）→ Task 7。
  - 首板上电（第 9 节）→ README 指引。电池预留（4.4 节）只留焊盘，已含在 Task 3 测试点块中。
- **已知不能由测试保证、需人工判断的**：USB 阻抗是否真为 90Ω、天线性能、40MHz 线的信号质量、摄像头 FPC 与屏幕 7 针的实物顺序。这些在 Task 4 Step 5 和 Task 5 Step 6 设了委托方确认点。
- **类型一致性**：`Part.pins` 键为字符串形式的引脚号，与 KiCad `pad.GetNumber()` 返回字符串一致；`placement.PLACE` 在 Task 5 定义，Task 6、7 只消费 `.kicad_pcb` 文件，不直接引用。
