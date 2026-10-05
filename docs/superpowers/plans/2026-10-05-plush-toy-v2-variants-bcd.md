# 毛绒玩具主板二期 B/C/D 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以已完成的版本 A 为电气、制造与验收基线，产出 B（无摄像头·双面）、C（带摄像头·单面）、D（带摄像头·双面）的原理图、PCB、静态验收、生产文件与接线/测试文档，并对 C/D 强制执行 spec 第 7 节摄像头安全门禁。

**Architecture:** 保留 `v2/core.py` 的四版本共用电路，用 `v2/nocam.py` 与 `v2/cam.py` 表达功能差异，用 `placement_<版本>.py` 只表达板形、面别与布局约束。把 A 专用测试抽成可复用基类，各版本只声明预期尺寸、单/双面、摄像头能力和允许告警；生成、布线、导出仍统一走现有 `context.load(variant)` 链路。

**Tech Stack:** Python 3、KiCad 10 Python/`pcbnew`、`kicad-cli`、Freerouting 2.4.1、`unittest`、项目既有 fab 导出脚本。

**Spec:** `docs/superpowers/specs/2026-10-05-plush-toy-v2-hardware-design.md`

## Global Constraints

- 一期目录 `hardware/plush-toy-mainboard` 只读；只允许复制已核对的摄像头封装/符号作为二期本地库输入。
- A 的电气连接、网络命名、网络类、去耦距离、制造检查和已收敛 PCB 不得回退。
- 四版本都是 4 层、1.6mm、JLC04161H-7628；In1/In2 保持 `LT_POWER`。
- 除测试点与安装孔外，所有器件均须 `assembly=True` 且有 LCSC 料号。
- B/D 正面只放模组、全部连接器与按键；电源、功放、传感器芯片及其阻容放背面。C 为单面贴片。
- C/D 沿用 AFC01-S24FCA-00 下接座；焊盘 `n` 对应摄像头脚 `25-n`，不得从参考设计或截图重新推算。
- C/D 在 spec §7.3 实物方向照片未记录前只能标为“数字设计完成/禁止下单”；首板到手后，spec §7.4 断电测量未通过前必须标为“禁止接摄像头上电”。两级门禁不可混为一个循环条件。
- 所有 DRC 必须先重新灌铜并保存，再分别报告 `unconnected_items`、`violations`、`schematic_parity`。
- 生成 PCB 必须先写临时文件，全部检查成功后再替换正式文件；不得用 KiCad GUI 手工补板。

## Review Focus

1. **摄像头座反序再次回归**：`test_camera_pad_mapping` 必须逐项验证“焊盘 → 摄像头脚 → 信号”，并单独断言 DVDD/AVDD/DOVDD/AGND/DGND 与 ESP32 GPIO 隔离。
2. **双面导出漏掉背面钢网/坐标**：`test_export_layers_for_double_sided` 必须验证 B/D Gerber 有 `B.Paste`，坐标同时含 top/bottom 且贴片器件数与 BOM 一致。
3. **翻面后去耦在芯片另一面**：通用 PCB 测试按器件所在铜层检查服务电容与 IC 同面、焊盘距离满足 `DECOUPLING`。
4. **C/D 的 MPR121 复位态误开加热**：测试固定 HEAT GPIO 使用 MPR121 可作 GPIO 的电极脚，且 `HEAT_GATE` 仍有 100kΩ 硬件下拉；未初始化时必须保持关断。
5. **物理门禁被文档或导出误报为已通过**：`camera_gate.py` 对缺照片/占位文字拒绝“可下单”发布；对缺表笔读数/占位文字拒绝“可接摄像头上电”状态，且不让后者反向阻止首板打样。

---

### Task 1: 摄像头电路、料号与 spec §7 自动门禁

**Files:**
- Modify: `hardware/plush-toy-v2-mainboard/scripts/v2/parts_db.py`
- Modify: `hardware/plush-toy-v2-mainboard/scripts/v2/cam.py`
- Modify: `hardware/plush-toy-v2-mainboard/scripts/test_parts_db.py`
- Modify: `hardware/plush-toy-v2-mainboard/scripts/test_variants.py`
- Create: `hardware/plush-toy-v2-mainboard/scripts/test_camera.py`
- Copy/adapt: `hardware/plush-toy-v2-mainboard/lib/plushv2.kicad_sym`
- Copy/adapt: `hardware/plush-toy-v2-mainboard/lib/plushv2.pretty/FPC-SMD_24P-P0.50_AFC01-S24FCA-00.kicad_mod`

**Interfaces:**
- Produces: `cam.CAMERA_PIN_SIGNALS: dict[int, str]`（摄像头脚号到信号）、`cam.CAMERA_PAD_TO_PIN: dict[str, int]`（FPC 焊盘到摄像头脚号）、`cam.camera_parts() -> list[Part]`。
- Camera parts: `J_CAM`、`U_LDO28`、`U_LDO15`、`U_TOUCH`（MPR121）、`U_ADC`（ADS1115）及各自去耦/配置阻容；不加入 PCA9685。

- [ ] **Step 1: 写失败测试**

  `test_camera.py` 固定断言 `CAMERA_PAD_TO_PIN[str(n)] == 25 - n`（1..24）；摄像头脚 4/10/11/2/15 分别映射 DOVDD/DVDD/AVDD/AGND/DGND 对应电源/地网络；这些焊盘网络不属于 `gpio.CAM.values()`。同时断言 ADS1115 AIN0..3 依次连接 `NTC_SENSE/VBAT_SENSE/CC_SENSE/BAT_NTC_SENSE`，MPR121 ELE0/可作 GPIO 的两个电极分别连接 `TOUCH_E0/HEAT_GATE_DRV/KEY_MUTE`。

- [ ] **Step 2: 运行并确认失败**

  Run: `cd hardware/plush-toy-v2-mainboard/scripts && python3 -m unittest test_parts_db test_variants test_camera -v`
  Expected: FAIL，`camera_parts()` 仍抛 `NotImplementedError` 或缺少映射常量。

- [ ] **Step 3: 增加已定料号与本地库**

  在 `parts_db.DB` 增加 `CAM_FPC=C262669`、`LDO_2V8=C53099`、`LDO_1V5=C53100`、`MPR121=C91322`、`ADS1115=C37593`；逐个声明语义焊盘。FPC 封装从一期已实测使用的同型号封装复制到 `plushv2` 库，并在 F.SilkS 明确画插入方向与“触点朝下”。

- [ ] **Step 4: 实现 `camera_parts()`**

  用两级映射生成 `J_CAM.pins`；保留 PWDN 10k 下拉、RESET 10k 上拉与 100nF 延时、SCCB 4.7k 上拉、两路 LDO 输入/输出去耦。MPR121 复位时 HEAT 输出为高阻，既有 `R_GATE_PD=100k` 保证加热关闭。

- [ ] **Step 5: 运行主机与 KiCad 封装测试**

  Run: `python3 -m unittest test_parts_db test_gpio test_core test_variants test_camera -v`
  Run: `/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_parts_db -v`
  Expected: 全部 PASS，C/D 不再抛 `NotImplementedError`。

### Task 2: 四版本生成、测试与双面制造导出基础设施

**Files:**
- Create: `hardware/plush-toy-v2-mainboard/scripts/pcb_test_base.py`
- Create: `hardware/plush-toy-v2-mainboard/scripts/drc_test_base.py`
- Modify: `hardware/plush-toy-v2-mainboard/scripts/test_pcb_A.py`
- Modify: `hardware/plush-toy-v2-mainboard/scripts/test_drc_A.py`
- Modify: `hardware/plush-toy-v2-mainboard/scripts/gen_pcb.py`
- Modify: `hardware/plush-toy-v2-mainboard/scripts/fab_tools.py`
- Modify: `hardware/plush-toy-v2-mainboard/scripts/export_fab.sh`
- Modify: `hardware/plush-toy-v2-mainboard/scripts/test_export.py`

**Interfaces:**
- Produces: `PcbVariantTestsMixin`、`DrcVariantTestsMixin`；placement 新增 `BACK_PARTS`（背面贴片件位号集合）和 `BACK_NEAR`（背面自动放置目标），A 的 `BACK_PARTS` 为空。

- [ ] **Step 1: 写失败测试**

  覆盖：单/双面器件约束、连接器均在正面、去耦与所服务 IC 同面、双面坐标包含两面、B/D Gerber 含 `B.Paste`、A/C 不含装配用背面钢网输出。

- [ ] **Step 2: 运行并确认失败**

  Run: `python3 -m unittest test_export -v`
  Expected: FAIL，当前导出只导 `F.Paste` 且 positions 只取 front。

- [ ] **Step 3: 泛化放置与测试**

  `gen_pcb.py` 按 `BACK_PARTS` 翻面并在独立占位池排布；通孔/大焊盘跨面避让保持不变。把 A 的结构、去耦、丝印、网络、板边、平面层和功率线测试迁到 mixin，A 测试只绑定 `VARIANT="A"`。

- [ ] **Step 4: 泛化制造导出**

  单面版本导出 F.Paste 与 front positions；双面版本导出 F.Paste+B.Paste，并合并 front/back positions，保留正确 Layer/Rotation。`fab_tools validate` 按当前变体核对装配器件数而非写死 A。

- [ ] **Step 5: 验证 A 不回退**

  Run: `python3 -m unittest test_parts_db test_gpio test_core test_variants test_camera test_netlist test_export -v`
  Run: `KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3; $KP -m unittest test_pcb_A test_drc_A -v`
  Expected: A 的既有静态结果仍为 0 error、0 unconnected、0 schematic parity。

### Task 3: 版本 B 布局与尺寸收缩

**Files:**
- Create: `hardware/plush-toy-v2-mainboard/scripts/placement_B.py`
- Create: `hardware/plush-toy-v2-mainboard/scripts/test_pcb_B.py`
- Create: `hardware/plush-toy-v2-mainboard/variants/B/`

**Interfaces:**
- Consumes: Task 2 的 `BACK_PARTS` 与通用 PCB 测试。
- Produces: B 的原理图和未布线 PCB；所有连接器/按键/U1 正面，电源、功放、IMU 与所属阻容背面。

- [ ] **Step 1: 写 `test_pcb_B.py` 并确认缺文件失败**

  断言双面规则、目标起步尺寸 42×34mm（允许按 A 同样方式记录迭代后调整）、天线伸板边、连接器开口朝外、同面去耦与无同面庭院重叠。

- [ ] **Step 2: 写 `placement_B.py` 并生成原理图/PCB**

  Run: `python3 gen_schematic.py --variant B`
  Run: `$KP gen_pcb.py --variant B`

- [ ] **Step 3: 运行布局测试并逐轮收缩**

  Run: `$KP -m unittest test_pcb_B -v`
  Run: `$KP shrink.py --variant B`
  Expected: 布局测试 PASS；README 记录每轮尺寸、失败原因和最终尺寸。

### Task 4: 版本 B 布线、DRC 与生产资料

**Files:**
- Create: `hardware/plush-toy-v2-mainboard/scripts/test_drc_B.py`
- Create: `hardware/plush-toy-v2-mainboard/variants/B/WIRING.md`
- Create: `hardware/plush-toy-v2-mainboard/variants/B/TESTING.md`
- Create: `hardware/plush-toy-v2-mainboard/variants/B/fab/`

- [ ] **Step 1: 先写 DRC/生产资料失败测试**
- [ ] **Step 2: 运行 `fanout.py --variant B`、`route.py --variant B`、`post_route.py --variant B --from-snapshot`，只接受未连接和 DRC error 不回退的候选**
- [ ] **Step 3: 重新灌铜并运行 `$KP -m unittest test_pcb_B test_drc_B -v`**
- [ ] **Step 4: 生成 `WIRING.md`、`TESTING.md`，运行 `bash export_fab.sh B`**
- [ ] **Step 5: 分别记录 unconnected/violations/schematic_parity、BOM/坐标数量、双面钢网与仍需实物验证项**

### Task 5: 版本 C 单面摄像头布局

**Files:**
- Create: `hardware/plush-toy-v2-mainboard/scripts/placement_C.py`
- Create: `hardware/plush-toy-v2-mainboard/scripts/test_pcb_C.py`
- Create: `hardware/plush-toy-v2-mainboard/variants/C/`

- [ ] **Step 1: 写 C 的布局与摄像头丝印失败测试**

  除通用单面规则外，断言 J_CAM 在板边、F.SilkS 同时包含排线方向箭头和“触点朝下”、两路 LDO 靠近 J_CAM、摄像头数据/时钟线串联电阻若采用则全部一致。

- [ ] **Step 2: 以 60×45mm 为起点实现 `placement_C.py`，生成原理图/PCB**
- [ ] **Step 3: 运行 `$KP -m unittest test_pcb_C -v` 并逐轮收缩，记录最终尺寸**

### Task 6: 版本 C 布线、DRC 与受门禁保护的生产资料

**Files:**
- Create: `hardware/plush-toy-v2-mainboard/scripts/test_drc_C.py`
- Create: `hardware/plush-toy-v2-mainboard/scripts/camera_gate.py`
- Create: `hardware/plush-toy-v2-mainboard/scripts/test_camera_gate.py`
- Create: `hardware/plush-toy-v2-mainboard/variants/C/CAMERA_VERIFICATION.md`
- Create: `hardware/plush-toy-v2-mainboard/variants/C/WIRING.md`
- Create: `hardware/plush-toy-v2-mainboard/variants/C/TESTING.md`

**Interfaces:**
- Produces: `camera_gate.validate_for_order(path: Path) -> list[str]`（§7.3）与 `camera_gate.validate_for_camera_power(path: Path) -> list[str]`（§7.3+§7.4）；C/D production export 只以前者为发布门禁，测试文档以后者为摄像头上电门禁。

- [ ] **Step 1: TDD 实现 fail-closed 的摄像头物理门禁**
- [ ] **Step 2: 完成 C 扇出、布线、重新灌铜、DRC 与原理图一致性**
- [ ] **Step 3: 生成接线和测试文档；§7.3 未有真实证据时标红“禁止下单”，§7.4 未通过时标红“禁止接摄像头上电”**
- [ ] **Step 4: 运行 `export_fab.sh C`，确认缺 §7.3 证据时拒绝发布；§7.3 齐全后允许生成首板 fab，但仍保留 §7.4 上电门禁**

### Task 7: 版本 D 双面摄像头布局、布线与生产资料

**Files:**
- Create: `hardware/plush-toy-v2-mainboard/scripts/placement_D.py`
- Create: `hardware/plush-toy-v2-mainboard/scripts/test_pcb_D.py`
- Create: `hardware/plush-toy-v2-mainboard/scripts/test_drc_D.py`
- Create: `hardware/plush-toy-v2-mainboard/variants/D/`

- [ ] **Step 1: 写 D 的双面布局、同面去耦、J_CAM 丝印与双面导出失败测试**
- [ ] **Step 2: 以 46×38mm 为起点实现布局，生成原理图/PCB并逐轮收缩**
- [ ] **Step 3: 完成扇出、布线、重新灌铜、DRC 与原理图一致性**
- [ ] **Step 4: 生成 WIRING/TESTING/CAMERA_VERIFICATION；按 §7.3/§7.4 分别保持禁止下单/禁止摄像头上电状态**
- [ ] **Step 5: §7.3 证据齐全后运行 `bash export_fab.sh D`，核对 B.Paste 与双面坐标；§7.4 留待首板断电测量**

### Task 8: 四版本完成审计与文档同步

**Files:**
- Modify: `hardware/plush-toy-v2-mainboard/README.md`
- Modify: `hardware/plush-toy-v2-mainboard/SELECTION.md`
- Modify: `docs/superpowers/specs/2026-10-05-plush-toy-v2-hardware-design.md`（只同步已经发生的尺寸/料号事实，不改原始要求）

- [ ] **Step 1: 运行全部主机测试与 A/B/C/D KiCad 测试**
- [ ] **Step 2: 对四个版本逐一列出尺寸、面别、器件数、BOM 行数、扩展库种类、库存、DRC 三分类与 fab 文件清单**
- [ ] **Step 3: 核对 README 状态不把缺物理证据的 C/D 写成可下单或已硬件验证**
- [ ] **Step 4: 明确报告仍需真实板完成的摄像头断电测量、首次上电、续航、3A 加热、双眼 40MHz 等项目**
