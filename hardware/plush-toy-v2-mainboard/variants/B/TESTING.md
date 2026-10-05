# 二期版本 B 首板验收

版本 B：不带摄像头 · 双面贴片 · 50×46mm · 锂电池供电。

本清单在 DRC、未连接项、原理图一致性均为零问题后执行。静态检查不能代替实物测试；
每项应记录日期、板号、实测值和结论。接线针序与外购件见 [WIRING.md](WIRING.md)。

## 一、下单前

| 项目 | 通过标准 |
|---|---|
| 静态门槛 | `test_pcb_B`、`test_drc_B` 全部 OK |
| 制造资料 | `fab/gerber.zip`、`bom.csv`、`positions.csv`、`parts_report.txt` 均存在 |
| 库存 | `parts_report.txt` 无“查不到”或“库存不足” |
| 嘉立创贴片预览 | 88 个贴装位号全部出现：Top 16、Bottom 72；方向与渲染图一致 |
| 板参数 | 4 层、1.6mm；Gerber 同时含 F.Paste 与 B.Paste，选择双面贴片 |

重点复核 IP5306、TPS259531、MAX98357A、LIS2DH12、USB-C 与所有卧式出线座的 1 脚和开口方向。

## 二、到货后不通电检查

1. 对光检查缺件、立碑、连锡和连接器歪斜；正反两面都检查。
2. 万用表短接表笔确认约 0Ω，再确认开路显示；避免把 `OL` 当短路。
3. `TP_VUSB`、`TP_VSYS`、`TP_VBAT`、`TP_3V3` 分别对 `TP_GND`，均不得为 0Ω。
4. `TP_EN`、`TP_BOOT` 对 `TP_3V3` 各约 10kΩ；`TP_CC` 对地约 52kΩ。
5. `J_HEAT` 两脚不得接近 0Ω；两只舵机座的 5V 对 GND 不得接近 0Ω。

通电时只接触背面测试点，不用表笔碰细间距芯片引脚。

## 三、首次上电

1. 不接电池和外设，用充电头 + POWER-Z 插 USB；电流不得持续攀升或接近 eFuse 限流值。
2. 测 `TP_VUSB≈5V`、`TP_VSYS≈5V`、`TP_3V3=3.3V±5%`。
3. 30 秒后检查 U_CHG、L_CHG、U_BUCK、U_EFUSE，无烫手热点。
4. 再接电脑烧录；启动无 BROWNOUT/反复重启，I2C 可发现 IP5306（0x75）和 LIS2DH12（0x19）。

## 四、电池与外设

1. 固件关闭 IP5306 轻载关机后再接带保护板的 1S 电池，确认红线对 `J_BAT +`。
2. 电池供电待机 5 分钟不掉电；充电至满电时 `TP_VBAT≈4.2V`。
3. 逐个连接屏、麦克风、喇叭、按键、触摸、舵机，每增加一个外设重新确认无复位和异常发热。
4. 双眼 40MHz 无花屏；音频录放正常；双舵机在 USB 与电池供电下均无 BROWNOUT。
5. 满电、不加热连续对话目标不少于 4 小时。

## 五、加热安全

加热膜必须在板外串联 KSD9700 65℃常闭开关。先用 5Ω/10W 假负载验证控制；只有 5V/3A C-C
电源且 CC 判断允许时才能开启。加热中拔 USB 后加热必须立即断电。最后验证 NTC 超温软件关断与
KSD9700 硬件断开；任何冒烟、异味或烫手都立即断电并拔电池。

## 六、静态复验命令

```sh
cd hardware/plush-toy-v2-mainboard/scripts
python3 -m unittest test_parts_db test_gpio test_core test_variants test_netlist test_export -v
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \
  -m unittest test_pcb_B test_drc_B -v
bash export_fab.sh B
```

这些检查证明工程数据和制造资料自洽；USB、无线、音频、电源、温升和机械装配仍须首板实测。
