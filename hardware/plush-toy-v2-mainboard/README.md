# 毛绒玩具主板二期

设计方案：[`docs/superpowers/specs/2026-10-05-plush-toy-v2-hardware-design.md`](../../docs/superpowers/specs/2026-10-05-plush-toy-v2-hardware-design.md)
实施计划：[`docs/superpowers/plans/2026-10-05-plush-toy-v2-hardware.md`](../../docs/superpowers/plans/2026-10-05-plush-toy-v2-hardware.md)
选型记录：[`SELECTION.md`](SELECTION.md)　电池防反接：[`BATTERY_PROTECTION.md`](BATTERY_PROTECTION.md)

四个版本共用一份电路描述（`scripts/v2/`），各自一份布局（`scripts/placement_<X>.py`），产物在 `variants/<X>/`。

## 命令

```sh
cd hardware/plush-toy-v2-mainboard/scripts
KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
python3 -m unittest test_parts_db test_gpio test_core test_variants test_netlist   # 电路描述与原理图
python3 gen_schematic.py --variant A
$KP gen_pcb.py --variant A
$KP -m unittest test_pcb_A
$KP shrink.py --variant A        # 试探能否继续缩小（不改文件）
$KP fanout.py --variant A && $KP route.py --variant A   # 扇出 + Freerouting，成功后存 build/routed-snapshot
$KP post_route.py --variant A --from-snapshot           # 网格补线（不重跑 Freerouting）
bash export_fab.sh A             # 测试 + Gerber/BOM/坐标/库存报告/渲染图 → variants/A/fab/
python3 export_wiring.py --variant A                    # 接线表与外购清单
```

## 版本状态

| 版本 | 状态 | 尺寸 |
|---|---|---|
| A 不带摄像头 · 单面 | 生产文件已出，待委托方决定是否打样 | 54×46mm |
| B 不带摄像头 · 双面 | 生产文件已出，待首板实测 | 50×46mm |
| C 带摄像头 · 单面 | 未开始（须先满足 spec 第 7 节） | — |
| D 带摄像头 · 双面 | 未开始 | — |

## 版本 A 尺寸迭代

| 轮次 | 尺寸 | 面积 / 一期 5400mm² | 结果 |
|---|---|---|---|
| 0 | 52×42 | 40% | spec 估算起点。按委托方要求加每个引脚的丝印标注后，右下角、右上角的标注与座子冲突 |
| 1 | 52×46 | 44% | 可行：全部器件与丝印放下，布局测试通过 |
| 2 | 51×46 | 43% | 失败：左上安装孔与触摸座重叠 |
| 2 | 52×45 | 43% | 失败：触摸座、测温座的引脚标注放不下 |
| 4 | 54×46 | 46% | 去耦复查后加宽 2mm（委托方 2026-10-05 同意）：去耦电容须贴引脚同侧，52×46 只剩 1 个降压位置且布不通 |

**结论**：单面版本的尺寸由板边长度决定，不由面积决定：上边 4 个、下边 4 个、右边 3 个出线座已排满，左边是模组与天线。再缩小需要减少出线座或改双面（版本 B）。
暂不加布线余量：板中部仍有空地，Task 10 布线不收敛时再加。

## 版本 A 结果（2026-10-05）

| 项 | 结果 |
|---|---|
| 尺寸 | 54×46mm，4 层，面积 2484mm²，**一期的 46%** |
| 器件 | 88 颗全部贴片（单面），BOM 38 行；另有 8 个背面测试点、2 个安装孔，**板上无手焊件** |
| 扩展库 | 20 种（每种每单一笔换料费），库存全部 ≥ 20，见 `variants/A/fab/parts_report.txt` |
| 单板器件费 | 约 $13.1（嘉立创 1–49 片档；ESP32 模组 $5.14 占四成，其次 MAX98357A $1.32、LIS2DH12 $0.93、eFuse $0.87） |
| DRC（重新灌铜后） | 0 错误、0 未连接、原理图一致性 0；孔距按错误检查。警告 17 条均为丝印：舵机排针外形伸出板边（设计如此）、模组天线外形、外框相碰、电池座自带外框压到其固定焊盘（导出时自动裁掉） |
| 布局质量（测试保证） | 去耦电容焊盘距所服务引脚 ≤ 3mm 且在同侧（第二颗储能电容 ≤ 6mm）；降压热回路表层 1.2mm；降压输出焊盘直接打孔进 3V3 平面；功率网络无长细线；出线座全部卧式、开口朝板边；功能名不会印到邻座旁 |
| 生产文件 | `variants/A/fab/`：`gerber.zip`、`bom.csv`、`positions.csv` |
| 接线 / 验收 | [`variants/A/WIRING.md`](variants/A/WIRING.md)、[`variants/A/TESTING.md`](variants/A/TESTING.md) |
| 渲染图 | `variants/A/renders/final_top.png`、`final_bottom.png` |

固件需要配套改动（另立计划）：I2C 在 GPIO43/44，LIS2DH12 地址 0x19，开机后经 I2C 关掉 IP5306 轻载关机，
按 CC 电压判定是否允许加热。
