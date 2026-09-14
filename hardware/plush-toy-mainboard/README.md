# plush-toy 主板（4 层）

设计依据：[`docs/superpowers/specs/2026-09-14-plush-toy-pcb-4layer-design.md`](../../docs/superpowers/specs/2026-09-14-plush-toy-pcb-4layer-design.md)。引脚以 [`main/boards/plush-toy/config.h`](../../main/boards/plush-toy/config.h) 为唯一事实来源，本工程不得改动任何 GPIO 分配。

## 状态

| 阶段 | 状态 | 产物 |
|---|---|---|
| 工具链 | 进行中 | KiCad、Java 21、Freerouting 2.4.1 |
| 原理图 | 未开始 | `*.kicad_sch`、ERC 报告、原理图 PDF |
| 布局 | 未开始 | `*.kicad_pcb`、四层渲染图 |
| 走线 | 未开始 | DRC 报告 |
| 制造文件 | 未开始 | `fab/` 下 Gerber、钻孔、BOM、坐标文件 |

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
