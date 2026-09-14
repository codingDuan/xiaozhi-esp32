# plush-toy 主板（4 层）

设计依据：[`docs/superpowers/specs/2026-09-14-plush-toy-pcb-4layer-design.md`](../../docs/superpowers/specs/2026-09-14-plush-toy-pcb-4layer-design.md)。引脚以 [`main/boards/plush-toy/config.h`](../../main/boards/plush-toy/config.h) 为唯一事实来源，本工程不得改动任何 GPIO 分配。

## 状态

| 阶段 | 状态 | 产物 |
|---|---|---|
| 工具链 | 完成 | KiCad 10.0.6、OpenJDK 26（Freerouting 2.4.1 需 Java 25+） |
| 器件与连接数据 | 完成 | `scripts/board_spec.py`，config.h、硬约束、库引脚核对全绿 |
| 原理图 | **生成完成，待委托方评审** | `plush-toy-mainboard.kicad_sch`，网表与 board_spec 逐网络一致，ERC 零错误；`renders/schematic.pdf` |
| 布局 | **完成，待委托方过目** | `plush-toy-mainboard.kicad_pcb`：90×60mm 四层、单面贴片，108 个器件，test_pcb 8 项全绿；`renders/place_top.png` |
| 走线 | 未开始 | DRC 报告 |
| 制造文件 | 未开始 | `fab/` 下 Gerber、钻孔、BOM、坐标文件 |

## 已定的物理约束

- 板子 **90×60mm，单面贴片**（原定 70×50mm 按实际封装量放不下）
- 摄像头为 **OV3660**（排线丝印 TY-OV3660-21MM-V3.0），金手指朝下插入，用下接触 FPC 座
- 圆屏 7 针顺序、舵机线序均已对照实物确认

## 原理图评审需要委托方确认的三件事（已全部确认，2026-09-14）

1. **摄像头排线金手指朝向**：拍一张 OV2640 排线末端的照片。本板按下接触 FPC 座（AFC01-S24FCA-00）绘制，若金手指朝上需换上接触座（设计方案 12.5 节）。
2. **两块圆屏的 7 针顺序**：拍屏幕模块排针丝印，确认是 RST / CS / DC / SDA / SCL / GND / VCC。
3. **舵机插头顺序**：本板按 PWM / V+ / GND，与原 PCA9685 模块一致；若舵机线序不同需调换。

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
