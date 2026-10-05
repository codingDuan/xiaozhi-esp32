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
```

## 版本状态

| 版本 | 状态 | 尺寸 |
|---|---|---|
| A 不带摄像头 · 单面 | 布局完成，待布线 | 52×46mm |
| B 不带摄像头 · 双面 | 未开始 | — |
| C 带摄像头 · 单面 | 未开始（须先满足 spec 第 7 节） | — |
| D 带摄像头 · 双面 | 未开始 | — |

## 版本 A 尺寸迭代

| 轮次 | 尺寸 | 面积 / 一期 5400mm² | 结果 |
|---|---|---|---|
| 0 | 52×42 | 40% | spec 估算起点。按委托方要求加每个引脚的丝印标注后，右下角、右上角的标注与座子冲突 |
| 1 | 52×46 | 44% | 可行：全部器件与丝印放下，布局测试通过 |
| 2 | 51×46 | 43% | 失败：左上安装孔与触摸座重叠 |
| 2 | 52×45 | 43% | 失败：触摸座、测温座的引脚标注放不下 |

**结论**：单面版本的尺寸由板边长度决定，不由面积决定：上边 4 个、下边 4 个、右边 3 个出线座已排满，左边是模组与天线。再缩小需要减少出线座或改双面（版本 B）。
暂不加布线余量：板中部仍有空地，Task 10 布线不收敛时再加。
