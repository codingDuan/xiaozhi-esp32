"""生成 INMP441 封装。KiCad 官方库没有这颗麦克风，按 TDK DS-INMP441-00 Rev1.0 自行绘制。

几何推导（写在这里，出错时能对照原始资料复核）：
- 图 3（第 8 页）是 **底视图**：左列自上而下 4 L/R、3 WS、2 SD、1 SCK；
  右列自上而下 6 GND、7 VDD、8 CHIPEN、9 GND；声孔铜环 5 GND 在两列顶端之间。
- 图 14（第 17 页）是 **PCB 顶视图** 焊盘图：两行各 4 个 0.40×0.60 焊盘，行距 2.66，
  列距 1.05；铜环外径 1.56、内径 0.96，位于第 4 列、两行正中。
- 顶视图是底视图的镜像。把底视图镜像后顺时针旋转 90°，铜环落到右侧，与图 14 一致，得到：
  上行（y=-1.33）自左向右 9、8、7、6；下行（y=+1.33）自左向右 1、2、3、4。
- 图 15（第 17 页）：封装 4.72×3.76；第 4 列中心距封装右边 1.07，
  故第 4 列 x = 4.72/2 - 1.07 = 1.29，各列 x = 1.29 - 1.05·k。
  第 1 列到第 4 列 3.15，与图中 3.16 吻合。
- 声孔：数据手册要求不小于 0.25，推荐 0.5 到 1。取 0.4 非金属化孔：铜环内径 0.96，
  孔到铜 (0.96-0.4)/2 = 0.28mm，满足工程规则 min_hole_clearance 0.25。原取 0.5 时只剩
  0.23mm，DRC 报 hole_clearance（2026-09-14）。0.4 仍远大于声孔下限，不影响灵敏度。
- 钢网：信号焊盘开口 0.35×0.55（外扩 -0.025）；铜环开口内径 1.05，
  两条 0.20 宽排气槽，位于 45° 与 225° 方向。
"""
import math
import uuid
from pathlib import Path

NAME = "InvenSense_INMP441_LGA-9_4.72x3.76mm"
OUT = Path(__file__).resolve().parents[1] / "lib/plush.pretty" / f"{NAME}.kicad_mod"

BODY_W, BODY_H = 4.72, 3.76
ROW_Y = 1.33
COL_X = [1.29 - 1.05 * k for k in (3, 2, 1, 0)]   # 自左向右
PAD_W, PAD_H = 0.40, 0.60
TOP_ROW = ["9", "8", "7", "6"]
BOTTOM_ROW = ["1", "2", "3", "4"]
RING_X, RING_Y = COL_X[3], 0.0
RING_R_IN, RING_R_OUT = 0.96 / 2, 1.56 / 2
PASTE_R_IN = 1.05 / 2
SOUND_HOLE = 0.4
SLOT_W = 0.20


def uid() -> str:
    return str(uuid.uuid4())


def rect_pad(number: str, x: float, y: float) -> str:
    return (f'\t(pad "{number}" smd rect\n\t\t(at {x:.3f} {y:.3f})\n\t\t(size {PAD_W} {PAD_H})\n'
            f'\t\t(layers "F.Cu" "F.Paste" "F.Mask")\n\t\t(solder_paste_margin -0.025)\n'
            f'\t\t(uuid "{uid()}")\n\t)\n')


def ring_pad() -> str:
    mid = (RING_R_IN + RING_R_OUT) / 2
    width = RING_R_OUT - RING_R_IN
    # 锚点放在铜环上（环的最右点），图元圆心相对锚点向左偏移 mid
    return (f'\t(pad "5" smd custom\n\t\t(at {RING_X + mid:.3f} {RING_Y:.3f})\n\t\t(size {width:.3f} {width:.3f})\n'
            f'\t\t(layers "F.Cu" "F.Mask")\n\t\t(options\n\t\t\t(clearance outline)\n\t\t\t(anchor circle)\n\t\t)\n'
            f'\t\t(primitives\n\t\t\t(gr_circle\n\t\t\t\t(center {-mid:.4f} 0)\n\t\t\t\t(end 0 0)\n'
            f'\t\t\t\t(width {width:.4f})\n\t\t\t\t(fill no)\n\t\t\t)\n\t\t)\n\t\t(uuid "{uid()}")\n\t)\n')


def paste_arc(start_deg: float, end_deg: float, steps: int = 24) -> str:
    pts = []
    for i in range(steps + 1):
        a = math.radians(start_deg + (end_deg - start_deg) * i / steps)
        pts.append((RING_X + RING_R_OUT * math.cos(a), RING_Y + RING_R_OUT * math.sin(a)))
    for i in range(steps, -1, -1):
        a = math.radians(start_deg + (end_deg - start_deg) * i / steps)
        pts.append((RING_X + PASTE_R_IN * math.cos(a), RING_Y + PASTE_R_IN * math.sin(a)))
    xy = " ".join(f"(xy {x:.4f} {y:.4f})" for x, y in pts)
    return (f'\t(fp_poly\n\t\t(pts {xy})\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type solid)\n\t\t)\n'
            f'\t\t(fill yes)\n\t\t(layer "F.Paste")\n\t\t(uuid "{uid()}")\n\t)\n')


def line(layer: str, x1, y1, x2, y2, width: float) -> str:
    return (f'\t(fp_line\n\t\t(start {x1:.3f} {y1:.3f})\n\t\t(end {x2:.3f} {y2:.3f})\n'
            f'\t\t(stroke\n\t\t\t(width {width})\n\t\t\t(type solid)\n\t\t)\n\t\t(layer "{layer}")\n'
            f'\t\t(uuid "{uid()}")\n\t)\n')


def rect(layer: str, x, y, width: float) -> str:
    return "".join(line(layer, *seg, width) for seg in [(-x, -y, x, -y), (x, -y, x, y), (x, y, -x, y), (-x, y, -x, -y)])


def main() -> Path:
    hx, hy = BODY_W / 2, BODY_H / 2
    # 排气槽在 45° 与 225°（KiCad y 轴向下，图 15 的右上方向即 -45°）
    half_gap = math.degrees(math.asin((SLOT_W / 2) / ((PASTE_R_IN + RING_R_OUT) / 2)))
    parts = [
        f'(footprint "{NAME}"\n\t(version 20260206)\n\t(generator "plush_gen")\n\t(generator_version "10.0")\n',
        '\t(layer "F.Cu")\n',
        '\t(descr "TDK InvenSense INMP441 bottom-port I2S MEMS microphone, LGA-9 4.72x3.76mm, DS-INMP441-00 Rev1.0 Fig.14/15")\n',
        '\t(tags "microphone MEMS I2S INMP441 bottom port")\n',
        f'\t(property "Reference" "REF**"\n\t\t(at 0 {-hy - 0.9:.2f} 0)\n\t\t(layer "F.SilkS")\n\t\t(uuid "{uid()}")\n'
        '\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1 1)\n\t\t\t\t(thickness 0.15)\n\t\t\t)\n\t\t)\n\t)\n',
        f'\t(property "Value" "{NAME}"\n\t\t(at 0 {hy + 0.9:.2f} 0)\n\t\t(layer "F.Fab")\n\t\t(uuid "{uid()}")\n'
        '\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1 1)\n\t\t\t\t(thickness 0.15)\n\t\t\t)\n\t\t)\n\t)\n',
        '\t(attr smd)\n',
        rect("F.SilkS", hx + 0.1, hy + 0.1, 0.12),
        rect("F.Fab", hx, hy, 0.1),
        rect("F.CrtYd", hx + 0.25, hy + 0.25, 0.05),
        # 1 脚标记：下行最左焊盘外侧
        line("F.SilkS", COL_X[0] - 0.6, hy + 0.35, COL_X[0] + 0.2, hy + 0.35, 0.12),
        paste_arc(-45 + half_gap, 135 - half_gap),
        paste_arc(135 + half_gap, 315 - half_gap),
        f'\t(pad "" np_thru_hole circle\n\t\t(at {RING_X:.3f} {RING_Y:.3f})\n\t\t(size {SOUND_HOLE} {SOUND_HOLE})\n'
        f'\t\t(drill {SOUND_HOLE})\n\t\t(layers "*.Cu" "*.Mask")\n\t\t(uuid "{uid()}")\n\t)\n',
    ]
    parts += [rect_pad(n, x, -ROW_Y) for n, x in zip(TOP_ROW, COL_X)]
    parts += [rect_pad(n, x, ROW_Y) for n, x in zip(BOTTOM_ROW, COL_X)]
    parts.append(ring_pad())
    parts.append("\t(embedded_fonts no)\n)\n")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(parts), encoding="utf-8")
    return OUT


if __name__ == "__main__":
    print(main())
