# plush-toy 主板布线收尾 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过可重复的 KiCad Python 后处理，令 plush-toy 主板 DRC 零错误、零未连接且与原理图一致。

**Architecture:** `gen_pcb.py`、`fanout.py`、`route.py` 保持各自职责，新增 `post_route.py` 作为 Freerouting 导入后的确定性收尾层。该层仅在顶层加入受控短线/通孔、清理 U_MIC 声孔禁区内的 GND 过孔，并在保存前重铺铜和恢复工程规则。

**Tech Stack:** KiCad 10 `pcbnew` Python API、`kicad-cli pcb drc`、Python `unittest`、Freerouting 2.4.1。

---

## 文件职责

| 文件 | 职责 |
|---|---|
| `hardware/plush-toy-mainboard/scripts/post_route.py` | 后处理板：删除声孔违规 GND 过孔、添加经过几何净距检查的手工段/过孔、重铺铜并保存。 |
| `hardware/plush-toy-mainboard/scripts/test_pcb.py` | 断言 U_MIC 声孔禁区未被过孔侵入，且指定收尾网络已导通。 |
| `hardware/plush-toy-mainboard/README.md` | 将流水线、状态及已知问题更新为完成后的真实结果。 |
| `hardware/plush-toy-mainboard/TESTING.md` | 下单前审阅与首板功能、安全、压力测试的记录模板及通过标准。 |

### Task 1: 添加当前问题的可执行回归测试

**Files:**
- Modify: `hardware/plush-toy-mainboard/scripts/test_pcb.py:166-201`
- Test: `hardware/plush-toy-mainboard/scripts/test_pcb.py`

- [ ] **Step 1: 写入会失败的声孔禁区测试**

  在 `PcbTest` 中添加几何辅助函数和断言；禁区半径以声孔中心 `(15.29, 50.00)`、声孔半径 `0.20 mm`、规则净距 `0.25 mm`、过孔半径 `0.30 mm` 计算：

  ```python
      def test_microphone_acoustic_hole_clear_of_vias(self):
          hole_x, hole_y, exclusion = 15.29, 50.00, 0.20 + 0.25 + 0.30
          offenders = [
              (round(t.GetPosition().x / MM, 3), round(t.GetPosition().y / MM, 3))
              for t in self.board.GetTracks()
              if t.GetClass() == "PCB_VIA"
              and ((t.GetPosition().x / MM - hole_x) ** 2 +
                   (t.GetPosition().y / MM - hole_y) ** 2) ** 0.5 < exclusion
          ]
          self.assertEqual(offenders, [])
  ```

- [ ] **Step 2: 写入会失败的收尾网络导通测试**

  在 `test_drc.py` 的 `DrcTest` 中增加一个只检查目标焊盘的 DRC 断言；`kicad-cli` 的 `unconnected_items` 是此处物理导通的权威来源，不能只比较两个焊盘的网名：

  ```python
      def test_post_route_target_pads_have_no_open_connection(self):
          targets = {
              "Pad 4 [GND] of U_TOUCH", "Pad 8 [+3V3] of U_IMU",
              "Pad 9 [GND] of U_IMU", "Pad 11 [GND] of U_IMU",
              "Pad 28 [+3V3] of U_PWM", "Pad 8 [+3V3] of U_ADC",
              "Pad 4 [+2V8] of J_CAM", "Pad 10 [+1V5] of J_CAM",
              "Pad 1 [TOUCH_E0] of TP_E0", "Pad 20 [CAM_Y6] of U1",
          }
          opens = [
              item for finding in self.report.get("unconnected_items", [])
              for item in finding.get("items", [])
              if item.get("description") in targets
          ]
          self.assertEqual(opens, [], self._brief(self.report.get("unconnected_items", [])))
  ```

  增加该测试的文件到本任务的 Files 列表：`hardware/plush-toy-mainboard/scripts/test_drc.py:1-43`。

- [ ] **Step 3: 验证 RED**

  Run:

  ```sh
  cd hardware/plush-toy-mainboard/scripts
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_pcb.PcbTest.test_microphone_acoustic_hole_clear_of_vias -v
  ```

  Expected: FAIL，列出 `(15.92, 50.0)`。

- [ ] **Step 4: 提交测试基线**

  ```sh
  git add hardware/plush-toy-mainboard/scripts/test_pcb.py
  git commit -m "test(pcb): cover routing completion constraints"
  ```

### Task 2: 实现确定性后处理器

**Files:**
- Create: `hardware/plush-toy-mainboard/scripts/post_route.py`
- Test: `hardware/plush-toy-mainboard/scripts/test_pcb.py`

- [ ] **Step 1: 写入最小后处理器骨架**

  创建以下 API 和常量；所有坐标均以 mm 表示，所有添加的走线在 `F_Cu`，内层不承载信号线：

  ```python
  ROOT = Path(__file__).resolve().parents[1]
  PCB = ROOT / "plush-toy-mainboard.kicad_pcb"
  VIA_D, VIA_DRILL = 0.6, 0.3
  TRACE_W, CLEARANCE = 0.20, 0.15
  MIC_HOLE = (15.29, 50.00)
  MIC_EXCLUSION = 0.20 + 0.25 + VIA_D / 2

  def mm(value: float) -> int:
      return pcbnew.FromMM(value)

  def point(x: float, y: float) -> pcbnew.VECTOR2I:
      return pcbnew.VECTOR2I(mm(x), mm(y))

  class PostRouter:
      def __init__(self, board: pcbnew.BOARD):
          self.board = board

      def remove_microphone_vias(self) -> int:
          removed = 0
          for item in list(self.board.GetTracks()):
              if item.GetClass() != "PCB_VIA" or item.GetNetname() != "GND":
                  continue
              x, y = item.GetPosition().x / 1e6, item.GetPosition().y / 1e6
              if math.hypot(x - MIC_HOLE[0], y - MIC_HOLE[1]) < MIC_EXCLUSION:
                  self.board.Remove(item)
                  removed += 1
          return removed

      def run(self) -> None:
          self.remove_microphone_vias()
          pcbnew.ZONE_FILLER(self.board).Fill(self.board.Zones())
  ```

- [ ] **Step 2: 以失败测试驱动声孔过孔移除**

  追加入口并运行该脚本：

  ```python
  def main() -> None:
      board = pcbnew.LoadBoard(str(PCB))
      PostRouter(board).run()
      board.Save(str(PCB))
      project_rules.apply()

  if __name__ == "__main__":
      main()
  ```

  Run:

  ```sh
  cd hardware/plush-toy-mainboard/scripts
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 post_route.py
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_pcb.PcbTest.test_microphone_acoustic_hole_clear_of_vias -v
  ```

  Expected: PASS。若 U_MIC.5 因删过孔成为未连接，下一任务必须为该焊盘添加位于禁区外的 GND 扇出。

- [ ] **Step 3: 为受控短连接实现几何原语**

  向 `PostRouter` 添加以下原语；`add_segment` 和 `add_via` 必须取得起点焊盘的网络对象，避免按字符串新建网络：

  ```python
      def add_segment(self, net: pcbnew.NETINFO_ITEM, start, end, width=TRACE_W):
          track = pcbnew.PCB_TRACK(self.board)
          track.SetStart(start)
          track.SetEnd(end)
          track.SetLayer(pcbnew.F_Cu)
          track.SetWidth(mm(width))
          track.SetNet(net)
          self.board.Add(track)

      def add_via(self, net: pcbnew.NETINFO_ITEM, x: float, y: float):
          via = pcbnew.PCB_VIA(self.board)
          via.SetPosition(point(x, y))
          via.SetWidth(mm(VIA_D))
          via.SetDrill(mm(VIA_DRILL))
          via.SetNet(net)
          self.board.Add(via)
          return via
  ```

  再实现 `pad(ref, number)`、`connect_points(net_pad, points)`；后者按顺序添加段，最后一个点是过孔时调用 `add_via`。每一段和过孔落点须先检查：板边至少 `0.6 mm`、不在 `MIC_EXCLUSION` 内、与不同网络焊盘/过孔的距离至少为 `CLEARANCE`（NPTH 用 `0.25 mm`）。检查失败应抛出 `RuntimeError`，包括网络名和候选坐标。

- [ ] **Step 4: 加入收尾连接表并验证 GREEN**

  将 `PostRouter.run()` 的收尾表保持为一组可审阅的 `(net, 起点焊盘, 中继点, 终点焊盘/过孔)` 项，覆盖以下确切端点：

  ```python
  TARGETS = (
      ("GND", ("U_TOUCH", "4")),
      ("+3V3", ("U_IMU", "8")),
      ("GND", ("U_IMU", "9")),
      ("GND", ("U_IMU", "11")),
      ("+3V3", ("U_PWM", "28")),
      ("+3V3", ("U_ADC", "8")),
      ("+2V8", ("J_CAM", "4")),
      ("+1V5", ("J_CAM", "10")),
      ("TOUCH_E0", ("TP_E0", "1")),
      ("CAM_Y6", ("U1", "20")),
  )
  ```

  对每一项，先从当前板的 DRC 缺失连接端点/既有同网铜中选择最短的可行曼哈顿路径；候选不通过上述几何检查时只改变一个中继点后重试。将最终坐标写为常量，禁止运行时做无界搜索或依赖 Freerouting 的随机结果。将 `U_MIC.5` 的 GND 连接加入同一表（若 Task 2 确认需要）。

  Run:

  ```sh
  cd hardware/plush-toy-mainboard/scripts
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 post_route.py
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_pcb -v
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_drc -v
  ```

  Expected: `test_pcb` 通过；`test_drc` 的 `violations`、`unconnected_items`、`schematic_parity` 均为空。

- [ ] **Step 5: 提交实现**

  ```sh
  git add hardware/plush-toy-mainboard/scripts/post_route.py hardware/plush-toy-mainboard/plush-toy-mainboard.kicad_pcb
  git commit -m "fix(pcb): complete deterministic post-routing"
  ```

### Task 3: 验证完整流水线并更新交接说明

**Files:**
- Modify: `hardware/plush-toy-mainboard/README.md:10-57`
- Test: `hardware/plush-toy-mainboard/scripts/test_pcb.py`, `hardware/plush-toy-mainboard/scripts/test_drc.py`

- [ ] **Step 1: 从干净生成状态运行完整链**

  ```sh
  cd hardware/plush-toy-mainboard/scripts
  KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
  $KP gen_pcb.py
  $KP fanout.py
  JAVA_TOOL_OPTIONS=-Djava.awt.headless=true $KP route.py 30
  $KP post_route.py
  $KP -m unittest test_pcb -v
  $KP -m unittest test_drc -v
  python3 -m unittest test_kicad_env test_config_pins test_board_spec test_part_pins test_netlist_roundtrip -v
  $KP -m unittest test_project_lib -v
  ```

  Expected: 全部通过；不要在 KiCad 图形界面保存 PCB。

- [ ] **Step 2: 更新 README 的命令和状态**

  在布线命令中 `route.py` 后加 `$KP post_route.py`。将布线状态更新为 DRC 零错误、零未连接、原理图一致；移除已解决的 10 条未连接、4 项孔间距违规及“扇出找不到位置”表项。保留 USB 差分、XCLK、功率线宽的人工/物理审查项与打样风险。

- [ ] **Step 3: 验证 README 与最终产物一致**

  ```sh
  git diff --check
  git diff -- hardware/plush-toy-mainboard/README.md
  cd hardware/plush-toy-mainboard/scripts
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_pcb test_drc -v
  ```

  Expected: 无空白错误；README 的每条状态都与刚才命令输出一致；测试全通过。

- [ ] **Step 4: 提交文档与再生 PCB**

  ```sh
  git add hardware/plush-toy-mainboard/README.md hardware/plush-toy-mainboard/plush-toy-mainboard.kicad_pcb
  git commit -m "docs(pcb): record completed routing verification"
  ```

### Task 4: 建立首板验收记录

**Files:**
- Create: `hardware/plush-toy-mainboard/TESTING.md`
- Test: `hardware/plush-toy-mainboard/scripts/test_drc.py`, `hardware/plush-toy-mainboard/scripts/test_pcb.py`

- [ ] **Step 1: 创建下单前与首板测试清单**

  创建 Markdown 表格，包含这些不可替代的验证和记录列：`阶段`、`仪器/夹具`、`操作`、`通过标准`、`实测值/结论`。按以下精确顺序填写项目：

  ```text
  下单前：DRC/原理图一致性零问题；Gerber、钻孔、阻焊、丝印、BOM、坐标文件逐层预览；USB-C、FPC 下接触、INMP441 声孔、极性件与连接器针序逐项对数据手册。
  未上电：VBUS、3V3、VMOT 对 GND 不短路；VMOT 对 VBUS、3V3 开路；PGND/GND 仅单点连通。
  分域上电：限流电源下 USB-only 的 3V3 正确且降压器不异常发热；VMOT-only 时 3V3=0 V；记录启动浪涌与 Wi-Fi 发射时 3V3 纹波。
  连接与高速：原生 USB 烧录/串口稳定；双屏 40 MHz 无花屏；OV3660 识别与连续取帧；示波器检查 USB、SPI CLK、XCLK。
  外设：status 中 servo_present、touch_present、motion_present、thermal_available 均为 true；运行 tools/plush_toy_i2c_trial.py 并记录丢帧率；录放音、触摸、IMU、两舵机均连续工作。
  安全和压力：5Ω/10W 假负载先验证加热 MOSFET，再接加热膜；确认 KSD9700 保护；Wi-Fi、屏、音频、两舵机、加热同时运行时无复位；记录 SY8089、Q_REV、Q_HEAT、电感和端子的温升。
  ```

- [ ] **Step 2: 链接可复现的静态证据**

  在同文件保留以下命令和预期结果，并说明它们不能替代硬件实测：

  ```sh
  cd hardware/plush-toy-mainboard/scripts
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_pcb test_drc -v
  python3 -m unittest test_kicad_env test_config_pins test_board_spec test_part_pins test_netlist_roundtrip -v
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_project_lib -v
  ```

- [ ] **Step 3: 验证文档和静态门槛**

  ```sh
  git diff --check -- hardware/plush-toy-mainboard/TESTING.md
  cd hardware/plush-toy-mainboard/scripts
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_pcb test_drc -v
  ```

  Expected: 文档无空白错误；静态检查通过后才将首板记录标记为“准备测试”。

- [ ] **Step 4: 提交测试记录模板**

  ```sh
  git add hardware/plush-toy-mainboard/TESTING.md
  git commit -m "docs(pcb): add first-article validation checklist"
  ```
