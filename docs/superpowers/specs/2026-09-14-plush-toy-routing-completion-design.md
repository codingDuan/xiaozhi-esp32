# plush-toy 主板布线收尾设计

## 目标

让 `hardware/plush-toy-mainboard` 的可重复 KiCad Python 流水线产出 DRC 零错误、零未连接且与原理图一致的 PCB。范围只包括自动布线后的收尾，不改变器件、网表、GPIO、板框或既定的电源分区。

## 决策

在 Freerouting 后新增确定性的 `scripts/post_route.py`。它是生成链的一部分，不允许在 KiCad 图形界面手工保存来替代它。

`gen_pcb.py` 继续负责外框、放置与平面；`fanout.py` 继续负责可通用的 GND / +3V3 焊盘下平面；`route.py` 继续只负责 DSN/SES 自动布线；`post_route.py` 负责当前自动布线器无法可靠解决的受控短连接与过孔清理。

## 布线策略

- 保持 In1 为全板 GND，In2 的 +3V3 平面只覆盖 `x <= 62 mm`；不扩大平面到功率区。
- 后处理用固定、经净距验证的顶层短线和过孔，连接 U_IMU、U_TOUCH、J_CAM、U_PWM、U_ADC 的剩余电源焊盘，以及 `TOUCH_E0`、`CAM_Y6`。
- U_MIC 声孔周边视为禁布圆：后处理删除或重定位 Freerouting 产生且违反孔间距的 GND 过孔。声孔本身仍为 0.4 mm 非金属化孔。
- 每次后处理都重铺铜并调用 `project_rules.apply()`，避免 `board.Save()` 覆盖工程网络类。

## 验证

先在 `test_pcb.py` 添加对受控收尾连接和声孔过孔禁区的断言，使当前存档板失败；再以最小实现使它们通过。完整生成链必须运行 `gen_pcb.py`、`fanout.py`、`route.py`、`post_route.py`，随后运行 `test_pcb` 与 `test_drc`。成功标准是 DRC 错误、未连接项和原理图一致性问题均为零。

物理硬件仍需在打样后验证 USB 90Ω、摄像头 DVP、40 MHz SPI、天线与麦克风声学表现；DRC 不能替代这些验证。
