# plush-toy 主板首板验收

本清单在 DRC、未连接项、原理图一致性均为零问题后执行。静态检查不能代替实物测试；每项都应记录日期、板号、仪器、实测值和结论。

## 下单前

| 项目 | 操作 | 通过标准 | 实测值 / 结论 |
|---|---|---|---|
| 制造文件 | 在工厂预览 Gerber、钻孔、阻焊、丝印、板框 | 层、孔、开窗和丝印位置均正确 | |
| 装配文件 | 审阅 BOM、贴片坐标和贴片面 | 料号、极性、数量、DNP 项与原理图一致 | |
| 关键封装 | 对数据手册和实物核 USB-C、FPC 下接触座、极性件、连接器针序（含 J_MIC / J_EXT 两个 SH 座） | 无方向、针序或封装尺寸错误 | |
| 天线与分区 | 审阅 ESP32 天线净空、开关节点、麦克风及功率区 | 天线净空无铜/器件；开关节点远离麦克风 | |

## 未上电与分域上电

| 项目 | 仪器 / 操作 | 通过标准 | 实测值 / 结论 |
|---|---|---|---|
| 电源短路 | 万用表量 VBUS、3V3、VMOT 对地电阻 | 均不短路 | |
| 电源隔离 | 万用表量 VMOT 对 VBUS、3V3 | 均开路；PGND/GND 只在设计的单点连通 | |
| USB 单独供电 | 限流电源接 USB | 3V3 正确；降压器不异常发热 | |
| VMOT 单独供电 | 限流电源接 VMOT | 3V3 为 0 V | |
| 电源质量 | 示波器记录启动浪涌、Wi-Fi 发射时 3V3 纹波 | 无欠压复位；纹波不影响外设 | |

## 接口与功能

| 项目 | 操作 | 通过标准 | 实测值 / 结论 |
|---|---|---|---|
| USB | 烧录固件、连续读取串口日志 | 可稳定下载，无枚举/日志异常 | |
| 双屏 | 40 MHz SPI 连续显示动画 | 无花屏、撕裂或颜色错位 | |
| 背光 | 上电观察，再逐级调 `GetBacklight()->SetBrightness()` 到 0 与 100 | 上电默认灭；两眼亮度一致、无可见闪烁；0 时完全熄灭 | |
| 背光开关 | 万用表量 Q_LCD_BL 漏极对 +3V3 压差，示波器看 GPIO48 | GPIO48 低电平导通，压降 < 0.1V；PWM 约 25kHz | |
| 摄像头 | 识别 OV3660，连续采集图像 | 无初始化失败或持续掉帧 | |
| 高速波形 | 示波器检查 USB D+/D-、SPI CLK、XCLK | 无明显振铃、毛刺或幅度不足 | |
| I2C | 运行 `tools/plush_toy_i2c_trial.py` | 丢帧率不劣于面包板基线 | |
| 外设 | 读取 status，测试触摸、IMU、双舵机、录放音 | servo/touch/motion/thermal 均可用；音频无异常底噪 | |

## 安全、热与压力

| 项目 | 操作 | 通过标准 | 实测值 / 结论 |
|---|---|---|---|
| 加热开关 | 先接 5Ω / 10W 假负载，再接加热膜 | MOSFET 受控开关；KSD9700 保护有效 | |
| 负载组合 | Wi-Fi、屏、音频、双舵机、加热同时运行 | 无复位、掉线、花屏或异常噪声 | |
| 温升 | 热像仪或热电偶测 SY8089、Q_REV、Q_HEAT、电感、端子 | 温升处于器件额定范围内，无烫伤/塑料软化风险 | |
| 长时间运行 | 满载持续运行并记录异常 | 无功能退化或间歇性复位 | |

## 静态门槛

```sh
cd hardware/plush-toy-mainboard/scripts
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_pcb test_drc -v
python3 -m unittest test_kicad_env test_config_pins test_board_spec test_part_pins test_netlist_roundtrip -v
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m unittest test_project_lib -v
```

这些命令通过只证明工程数据、连接规则和封装检查满足要求；USB、相机、SPI、音频、无线、电源和加热安全必须由首板实测确认。
