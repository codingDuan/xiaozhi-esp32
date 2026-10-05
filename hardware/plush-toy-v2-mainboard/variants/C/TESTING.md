# 二期版本 C 首板验收

版本 C：带摄像头 · 单面贴片 · 65×55mm · 锂电池供电。

> **当前禁止下单。** 先完成 [CAMERA_VERIFICATION.md](CAMERA_VERIFICATION.md) 的 spec §7.3
> 实物方向照片与 1/24 脚落点核验。生产导出脚本在证据不全时会拒绝生成 `fab/`。

本清单在 DRC、未连接项、原理图一致性均为零问题后执行。静态检查不能代替实物测试；
每项应记录日期、板号、实测值和结论。接线针序与外购件见 [WIRING.md](WIRING.md)。

## 一、下单前硬门禁

1. 使用一期 2 号板或 1:1 打印封装图，配 AFC01-S24FCA-00 实物排线拍照。
2. 确认触点朝下、摄像头 pin 1 → PCB pad 24、pin 24 → PCB pad 1、镜头朝 PCB 外。
3. 将原始照片放入本目录，计算 SHA256，在 `CAMERA_VERIFICATION.md` 记录核验人和日期。
4. `python3 camera_gate.py ../variants/C/CAMERA_VERIFICATION.md` 必须返回“摄像头物理门禁通过”。

## 二、制造资料

| 项目 | 通过标准 |
|---|---|
| 静态门槛 | `test_pcb_C` 24 项、`test_drc_C` 5 项全部 OK |
| 摄像头下单门禁 | spec §7.3 证据完整，`camera_gate.py` 通过 |
| 制造资料 | 门禁通过后，`fab/gerber.zip`、`bom.csv`、`positions.csv`、`parts_report.txt` 均存在 |
| 贴片预览 | 所有装配位号都在 Top，方向与渲染图一致；选单面贴片 |
| 板参数 | 4 层、1.6mm、JLC04161H-7628 |

重点复核 J_CAM 的 1 脚、排线插入方向、“FPC 触点朝下”丝印，以及两路摄像头 LDO。

## 三、到货后不通电检查

1. 对光检查缺件、立碑、连锡和连接器歪斜；全部装配件应已由工厂贴在正面。
2. 万用表短接表笔确认约 0Ω，再确认开路显示；避免把 `OL` 当短路。
3. `TP_VUSB`、`TP_VSYS`、`TP_VBAT`、`TP_3V3`、J_CAM 的 +2V8/+1V5 分别对 `TP_GND`，均不得为 0Ω。
4. **不通电插入摄像头**：座子空脚对 +1V5 必须为 OL；记录插入前后 +1V5→GND 二极管档读数，插入后不得明显降低。
5. 只有将读数写入 `CAMERA_VERIFICATION.md`并使 `camera_gate.py --power` 通过，才可进入摄像头上电测试。

## 四、首次上电

1. **先不接摄像头、电池和其他外设**，用充电头 + POWER-Z 插 USB；电流不得持续攀升。
2. 测 `TP_VUSB≈5V`、`TP_VSYS≈5V`、`TP_3V3=3.3V±5%`、J_CAM `+2V8`和 `+1V5`。
3. 30 秒后检查 U_CHG、L_CHG、U_BUCK、U_EFUSE、U_LDO28、U_LDO15，无烫手热点。
4. 烧录固件；I2C 应发现 IP5306、LIS2DH12、MPR121 和 ADS1115。
5. spec §7.4 门禁通过后才断电插摄像头，再上电识别 OV3660；连续采集不得持续掉帧。

## 五、电池、外设与加热

1. 固件关闭 IP5306 轻载关机后接 1S 带保护板电池；待机 5 分钟不掉电。
2. 逐个连接屏、麦克风、喇叭、按键、触摸和舵机，每次重新确认无复位和异常发热。
3. 双眼 40MHz 无花屏；音频录放正常；双舵机无 BROWNOUT；满电连续对话不少于 4 小时。
4. 加热膜必须在板外串 KSD9700 65℃ 常闭开关。只有 5V/3A C-C 电源且 CC 判定允许时才能开启。
5. 验证 MPR121 未初始化和复位时加热始终关闭，NTC 超温软件关断和 KSD9700 硬件断开均有效。

## 六、静态复验命令

```sh
cd hardware/plush-toy-v2-mainboard/scripts
python3 -m unittest test_parts_db test_gpio test_core test_variants test_camera test_netlist test_export test_camera_gate -v
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \
  -m unittest test_pcb_C test_drc_C -v
bash export_fab.sh C   # 没有 spec §7.3 实物证据时必须失败
```

这些检查证明工程数据自洽；USB、无线、音频、电源、温升、摄像头和机械装配仍须首板实测。
