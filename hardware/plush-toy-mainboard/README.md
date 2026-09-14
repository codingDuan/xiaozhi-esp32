# plush-toy 主板（4 层）

设计依据：[`docs/superpowers/specs/2026-09-14-plush-toy-pcb-4layer-design.md`](../../docs/superpowers/specs/2026-09-14-plush-toy-pcb-4layer-design.md)。引脚以 [`main/boards/plush-toy/config.h`](../../main/boards/plush-toy/config.h) 为唯一事实来源，本工程不得改动任何 GPIO 分配。

## 状态

| 阶段 | 状态 | 产物 |
|---|---|---|
| 工具链 | 完成 | KiCad 10.0.6、OpenJDK 26（Freerouting 2.4.1 需 Java 25+） |
| 器件与连接数据 | 完成 | `scripts/board_spec.py`，config.h、硬约束、库引脚核对全绿 |
| 原理图 | **生成完成，待委托方评审** | `plush-toy-mainboard.kicad_sch`，网表与 board_spec 逐网络一致，ERC 零错误；`renders/schematic.pdf` |
| 布局 | **完成，待委托方过目** | `plush-toy-mainboard.kicad_pcb`：90×60mm 四层、单面贴片，108 个器件，test_pcb 8 项全绿；`renders/place_top.png` |
| 走线 | **进行中（2026-09-14 存档）** | 扇出 101 个平面过孔 + Freerouting 自动布线；DRC 剩 **10 条未连接、4 处孔间距违规**，与原理图一致，test_pcb 16 项全绿 |
| 制造文件 | 未开始 | `fab/` 下 Gerber、钻孔、BOM、坐标文件 |

## 已定的物理约束

- 板子 **90×60mm，单面贴片**（原定 70×50mm 按实际封装量放不下）
- 摄像头为 **OV3660**（排线丝印 TY-OV3660-21MM-V3.0），金手指朝下插入，用下接触 FPC 座
- 圆屏 7 针顺序、舵机线序均已对照实物确认

## 原理图评审需要委托方确认的三件事（已全部确认，2026-09-14）

1. **摄像头排线金手指朝向**：拍一张 OV2640 排线末端的照片。本板按下接触 FPC 座（AFC01-S24FCA-00）绘制，若金手指朝上需换上接触座（设计方案 12.5 节）。
2. **两块圆屏的 7 针顺序**：拍屏幕模块排针丝印，确认是 RST / CS / DC / SDA / SCL / GND / VCC。
3. **舵机插头顺序**：本板按 PWM / V+ / GND，与原 PCA9685 模块一致；若舵机线序不同需调换。

## 布线流水线与剩余问题

重新布线按顺序执行（均用 KiCad 自带 Python，记作 `KP`）：

```sh
cd hardware/plush-toy-mainboard/scripts
KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
$KP gen_pcb.py                                                     # 外框、放置、铺铜、丝印
$KP fanout.py                                                      # GND / +3V3 焊盘打过孔下平面
JAVA_TOOL_OPTIONS=-Djava.awt.headless=true $KP route.py 30          # Freerouting 自动布线，约 5 分钟
$KP -m unittest test_pcb && python3 -m unittest test_drc            # 布局核对与 DRC
```

**已知坑**（都已写进脚本与测试）：
- 独立脚本里 `board.Save()` 会把 KiCad 默认规则写回 `.kicad_pro`，冲掉网络类。每次保存后必须 `project_rules.apply()`，否则 DRC 按默认 0.2mm 间距报几百处假错误
- 内层 In1 / In2 必须设为 power 类型，否则 Freerouting 会把信号线走在 GND / 3V3 平面上
- Freerouting 不会主动打过孔接平面，所以先跑 `fanout.py`
- 生成过程中请勿在 KiCad 图形界面里保存 PCB，会覆盖脚本结果

**2026-09-14 存档时的剩余问题**（下次从这里继续）：

| 问题 | 数量 | 处理方向 |
|---|---|---|
| 未连接：U_IMU 的 GND/+3V3 引脚（8/9/11）、U_TOUCH.4、J_CAM +2V8/+1V5、U_PWM/U_ADC 的 +3V3（位于 +3V3 平面覆盖范围 x<62 之外）、TOUCH_E0、CAM_Y6 | 10 | IMU 与 TOUCH 细间距引脚手工扇出；U_PWM、U_ADC 的 +3V3 需要走线或扩大 In2 平面；两条信号线手工补 |
| 孔间距：Freerouting 打的 GND 过孔离 U_MIC 声孔 0.13mm（规则 0.25mm） | 4 | 在声孔周围加禁布区，或布线后挪过孔 |
| 扇出找不到位置：J_CAM.2、D_USB_DP/DN.2、U_IMU.8/9/11、U_TOUCH.4 | 7 | 同上，手工处理 |
| 关键线未专门处理：USB 差分 90Ω、摄像头 XCLK、功率线宽 | — | 布通后在渲染图上逐条核查 |

## 运行测试

```sh
cd hardware/plush-toy-mainboard/scripts
python3 -m unittest test_kicad_env test_config_pins test_board_spec test_part_pins test_netlist_roundtrip -v
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_project_lib -v
```

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
