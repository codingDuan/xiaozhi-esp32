# plush-toy 主板（4 层）

设计依据：[`docs/superpowers/specs/2026-09-14-plush-toy-pcb-4layer-design.md`](../../docs/superpowers/specs/2026-09-14-plush-toy-pcb-4layer-design.md)。引脚以 [`main/boards/plush-toy/config.h`](../../main/boards/plush-toy/config.h) 为唯一事实来源，本工程不得改动任何 GPIO 分配。

## 状态

| 阶段 | 状态 | 产物 |
|---|---|---|
| 工具链 | 完成 | KiCad 10.0.6、OpenJDK 26（Freerouting 2.4.1 需 Java 25+） |
| 器件与连接数据 | 完成 | USB eFuse、必贴 SCCB 上拉、头部触摸连接器与 3.3V 状态灯已加入 |
| 原理图 | 完成 | ERC、网表往返与 PCB 原理图一致性检查通过 |
| 布局 | 完成 | 降压、ESP32 去耦/EN 与 XCLK 关键几何均由测试锁定 |
| 走线 | 完成 | 0 条未连接；内层保持纯电源平面；仅余 2 个已审阅 U1 丝印告警 |
| 制造文件 | 完成 | Gerber/BOM/CPL 已从最终 PCB 重新导出并通过静态检查 |
| 首板验收 | 清单完成，待打样 | [`TESTING.md`](TESTING.md)：制造文件、电源隔离、接口、外设、热与压力测试 |

## 已定的物理约束

- 板子 **90×60mm，单面贴片**（原定 70×50mm 按实际封装量放不下）
- 摄像头为 **OV3660**（排线丝印 TY-OV3660-21MM-V3.0），金手指朝下插入，用下接触 FPC 座
- 圆屏 7 针顺序、舵机线序均已对照实物确认

## 原理图评审需要委托方确认的三件事（已全部确认，2026-09-14）

1. **摄像头排线金手指朝向**：拍一张 OV2640 排线末端的照片。本板按下接触 FPC 座（AFC01-S24FCA-00）绘制，若金手指朝上需换上接触座（设计方案 12.5 节）。
2. **两块圆屏的 7 针顺序**：拍屏幕模块排针丝印，确认是 RST / CS / DC / SDA / SCL / GND / VCC。
3. **舵机插头顺序**：本板按 PWM / V+ / GND，与原 PCA9685 模块一致；若舵机线序不同需调换。

## 布线流水线

重新布线按顺序执行（均用 KiCad 自带 Python，记作 `KP`）：

```sh
cd hardware/plush-toy-mainboard/scripts
KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
$KP gen_pcb.py                                                     # 外框、放置、铺铜、丝印
$KP fanout.py                                                      # 电源平面、密脚距器件与相机 FPC 的确定性扇出
JAVA_TOOL_OPTIONS=-Djava.awt.headless=true $KP route.py 30          # Freerouting 自动布线，约 5 分钟
$KP post_route.py --apply                                          # 候选板完整 DRC/一致性通过后才覆盖正式 PCB
$KP -m unittest test_pcb test_drc -v                               # 布局、DRC、未连接与原理图一致性
```

**当前正式 PCB 的来历（2026-09-14 第二轮评审修改）**：以提交 c7b9cb5 已收敛的布线为起点，运行 `$KP apply_review_eco.py && $KP post_route.py --apply` 做三项局部修改（5V/触摸丝印挪位、C_BUCK_IN 转 180°、VBUS_FUSED 0.5mm 主干），其余走线未动。同样的意图已写进 `placement.py` 与 `fanout.py`，但**从 `gen_pcb.py` 整板重跑目前不收敛**：连续两轮 Freerouting + 收尾都在 U_TOUCH / J_CAM 密集区留下 6 条开路（TOUCH_E1/E4/E5/E6、CAM_VSYNC、CAM_HREF）。下次需要整板重布时先解决这一区域的确定性出线。

**已知坑**（都已写进脚本与测试）：
- 独立脚本里 `board.Save()` 会把 KiCad 默认规则写回 `.kicad_pro`，冲掉网络类。每次保存后必须 `project_rules.apply()`，否则 DRC 按默认 0.2mm 间距报几百处假错误
- 内层 In1 / In2 必须设为 power 类型，否则 Freerouting 会把信号线走在 GND / 3V3 平面上
- Freerouting 不会主动打过孔接平面，所以先跑 `fanout.py`
- Freerouting 的收尾结果不稳定；`route.py` 会拒绝未连接增加、新 DRC error 或一致性缺陷替换，并在运行前删除旧 SES；`post_route.py` 每次都从正式 PCB 生成独立候选，不自动续用来源不明的旧候选，完整检查后才允许 `--apply`
- 相机 0.5mm FPC、IMU、触摸与功放先做确定性逃逸；最终收尾会删除已被正式路径替代的悬空 stub/过孔，并按网络类宽度重走超过 2mm 的窄电源线
- 收尾路由器的窄颈逃逸会在宽焊盘出口留下 0.2mm 短线，逐段 2mm 的检查抓不到。保险丝到 eFuse 的 VBUS_FUSED 主干因此在 `fanout.py` 按 0.5mm 预布并锁定；`test_high_current_nets_have_no_long_necks` 把 VBUS/VMOT/PGND 等主干上相连的窄线合并计长，只允许在比线宽还窄的焊盘出口处总长 ≤ 2mm
- U1 标准库封装的天线边界丝印距板边约 0.54mm，不涉及铜、阻焊或铣刀路径；工程保留 warning，并由测试按告警类型、对象和坐标精确白名单，避免掩盖新增问题
- 描述性位号（如 `C_ADC`）不符合 KiCad 自动注释的字母+数字格式，制造 BOM 必须由 `board_spec.py` 经 `export_bom.py` 导出，不能直接使用 KiCad BOM 导出器
- 生成过程中请勿在 KiCad 图形界面里保存 PCB，会覆盖脚本结果

**2026-09-14 静态验收结果**：

| 检查 | 结果 | 处理 |
|---|---|---|
| KiCad DRC | 0 错误、2 个已审阅告警 | U1 标准封装天线端两条丝印线距板边约 0.54mm；告警按对象精确白名单，未全局屏蔽；其余孔间距、铜间距、板边与禁布区规则均通过 |
| 未连接项 | 0 | DRC 驱动的候选补线通过后应用 |
| 原理图一致性 | 通过 | `--schematic-parity` 与逐网络测试均通过 |
| 板级结构与 DRC | 通过 | 包含电源线宽/过孔、连接器/IC 丝印、PGND 锚线、完整 DRC 与原理图一致性 |
| 制造文件 | 通过 | BOM 与坐标各 81 个唯一自动贴装位号，均有 LCSC 料号且无 `?`；9 个接线座手焊；Gerber zip 14 个文件、无空文件 |
| 实物电气与信号质量 | 待首板 | 按 [`TESTING.md`](TESTING.md) 验证 USB、DVP、SPI、音频、供电与热测试 |

## 运行测试

```sh
cd hardware/plush-toy-mainboard/scripts
python3 -m unittest test_kicad_env test_config_pins test_board_spec test_part_pins test_netlist_roundtrip test_export_bom -v
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_project_lib -v
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_pcb test_drc test_post_route -v
```

静态检查通过后，按 [`TESTING.md`](TESTING.md) 完成下单前检查；收到首板后继续填写分域上电、接口、外设、热和压力测试的实测记录。

## 已知风险

DRC 通过只证明连接与规则正确。天线、40MHz SPI、摄像头 DVP、USB 90Ω 的实际质量只能打样验证，第一版预计需要改版。详见设计方案第 10 节。

## 目录约定

```
plush-toy-mainboard.kicad_pro   工程
plush-toy-mainboard.kicad_sch   原理图（按功能分页）
plush-toy-mainboard.kicad_pcb   PCB
lib/                            工程专用符号与封装（KiCad 官方库没有的）
scripts/                        生成与检查脚本，含 config.h 引脚对照检查
fab/                            制造文件，下单直接用这个目录
renders/                        各阶段渲染图
```
