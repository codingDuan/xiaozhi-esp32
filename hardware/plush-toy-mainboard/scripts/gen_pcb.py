"""用 KiCad 自带 Python 运行，生成 plush-toy-mainboard.kicad_pcb：
外框、4 层、器件放置、网络、分区铺铜、HC-6 丝印。

放置分两步：placement.ANCHORS 里的器件定点；其余器件按 placement.NEAR 从目标点
螺旋向外找第一个不与已放器件庭院层重叠、且在板内的位置。

重叠判断用矩形：每个器件的占位矩形取自封装庭院层。唯一例外是 U1，它的庭院层是
「模组本体 + 天线净空区」组成的 L 形，净空区放置后整体在板外，只取本体部分。
"""
import math
from pathlib import Path

import pcbnew

import board_spec
import kicad_env
import placement as pl

ROOT = Path(__file__).resolve().parents[1]
PCB = ROOT / "plush-toy-mainboard.kicad_pcb"
TO_MM = 1e-6


def v(x: float, y: float) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def load(part: board_spec.Part) -> pcbnew.FOOTPRINT:
    lib, name = part.footprint.split(":", 1)
    fp = pcbnew.FootprintLoad(str(kicad_env.footprint_dir(lib)), name)
    if fp is None:
        raise RuntimeError(f"{part.ref} 封装加载失败：{part.footprint}")
    fp.SetFPIDAsString(part.footprint)
    fp.SetReference(part.ref)
    fp.SetValue(part.value)
    return fp


def local_rect(fp: pcbnew.FOOTPRINT, ref: str) -> tuple[float, float, float, float]:
    """封装在原点、0° 时的占位矩形 (x1, y1, x2, y2)。"""
    court = fp.GetCourtyard(pcbnew.F_CrtYd)
    if court.OutlineCount():
        outline = court.Outline(0)
        pts = [(outline.CPoint(i).x * TO_MM, outline.CPoint(i).y * TO_MM) for i in range(outline.PointCount())]
        if ref == "U1":
            # 只取模组本体：净空区宽 ±24，本体宽 ±9.74（ESP32-S3-WROOM-1 封装实测）
            pts = [p for p in pts if abs(p[0]) <= 10.0]
    else:
        box = fp.GetBoundingBox(False)
        pts = [(box.GetX() * TO_MM, box.GetY() * TO_MM), (box.GetRight() * TO_MM, box.GetBottom() * TO_MM)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def rotate(x: float, y: float, angle: int) -> tuple[float, float]:
    # KiCad 角度正值为屏幕逆时针，y 轴向下：转 +90° 时 (x, y) → (y, -x)
    for _ in range((angle // 90) % 4):
        x, y = y, -x
    return x, y


def placed_rect(rect, x: float, y: float, angle: int):
    corners = [rotate(cx, cy, angle) for cx in (rect[0], rect[2]) for cy in (rect[1], rect[3])]
    xs, ys = [c[0] + x for c in corners], [c[1] + y for c in corners]
    return min(xs), min(ys), max(xs), max(ys)


def overlaps(a, b) -> bool:
    return not (a[2] + pl.GAP <= b[0] or b[2] + pl.GAP <= a[0] or a[3] + pl.GAP <= b[1] or b[3] + pl.GAP <= a[1])


def inside_board(rect) -> bool:
    m = pl.EDGE_MARGIN
    return rect[0] >= m and rect[1] >= m and rect[2] <= pl.W - m and rect[3] <= pl.H - m


def spiral(cx: float, cy: float, step: float = 0.5, max_r: float = 40.0):
    yield cx, cy
    r = step
    while r <= max_r:
        n = max(8, int(2 * math.pi * r / step))
        for k in range(n):
            a = 2 * math.pi * k / n
            yield cx + r * math.cos(a), cy + r * math.sin(a)
        r += step


def add_outline(board: pcbnew.BOARD) -> None:
    corners = [(0, 0), (pl.W, 0), (pl.W, pl.H), (0, pl.H)]
    for (x1, y1), (x2, y2) in zip(corners, corners[1:] + corners[:1]):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(v(x1, y1))
        seg.SetEnd(v(x2, y2))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(pcbnew.FromMM(0.1))
        board.Add(seg)


def add_zone(board: pcbnew.BOARD, net: str, layer: int, x1: float, y1: float, x2: float, y2: float) -> None:
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    zone.SetNet(board.FindNet(net))
    outline = zone.Outline()
    outline.NewOutline()
    for x, y in [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]:
        outline.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    board.Add(zone)


def main() -> Path:
    board = pcbnew.NewBoard(str(PCB))
    board.SetCopperLayerCount(4)
    add_outline(board)
    for name in board_spec.nets():
        if not name.startswith("NC_"):
            board.Add(pcbnew.NETINFO_ITEM(board, name))

    fitted = [p for p in board_spec.PARTS if p.fitted]
    missing = [p.ref for p in fitted if p.ref not in pl.ANCHORS and p.ref not in pl.NEAR]
    if missing:
        raise RuntimeError(f"placement.py 没有给出这些位号的位置：{missing}")

    occupied: list[tuple[float, float, float, float]] = []
    where: dict[str, tuple[float, float, int]] = {}
    fps: dict[str, pcbnew.FOOTPRINT] = {}

    def commit(part, fp, x, y, angle, rect):
        fp.SetPosition(v(x, y))
        fp.SetOrientationDegrees(angle)
        board.Add(fp)
        occupied.append(rect)
        where[part.ref] = (x, y, angle)
        fps[part.ref] = fp

    # 定点器件：一次收集全部问题再报，免得改一个跑一次
    problems = []
    anchor_rects: dict[str, tuple[float, float, float, float]] = {}
    for part in fitted:
        if part.ref not in pl.ANCHORS:
            continue
        fp = load(part)
        x, y, angle = pl.ANCHORS[part.ref]
        rect = placed_rect(local_rect(fp, part.ref), x, y, angle)
        if part.ref != "U1" and not inside_board(rect):
            problems.append(f"{part.ref} 超出板边 {tuple(round(c, 2) for c in rect)}")
        for other, r in anchor_rects.items():
            if overlaps(rect, r):
                problems.append(f"{part.ref} 与 {other} 重叠")
        anchor_rects[part.ref] = rect
        commit(part, fp, x, y, angle, rect)
    if problems:
        raise RuntimeError("定点器件位置有误：\n  " + "\n  ".join(problems))

    # 自动排布：先排大件，大件更难找位置
    auto = [p for p in fitted if p.ref not in pl.ANCHORS]
    sizes = {}
    loaded = {}
    for part in auto:
        loaded[part.ref] = load(part)
        r = local_rect(loaded[part.ref], part.ref)
        sizes[part.ref] = (r[2] - r[0]) * (r[3] - r[1])
    for part in sorted(auto, key=lambda p: -sizes[p.ref]):
        fp = loaded[part.ref]
        target = pl.NEAR[part.ref]
        cx, cy = (where[target][0], where[target][1]) if isinstance(target, str) else target
        local = local_rect(fp, part.ref)
        for x, y in spiral(cx, cy):
            x, y = round(x * 4) / 4, round(y * 4) / 4        # 0.25mm 网格
            found = None
            for angle in (0, 90):
                rect = placed_rect(local, x, y, angle)
                if inside_board(rect) and not any(overlaps(rect, r) for r in occupied):
                    found = (angle, rect)
                    break
            if found:
                commit(part, fp, x, y, found[0], found[1])
                break
        else:
            raise RuntimeError(f"{part.ref} 在 {target} 附近 40mm 内找不到空位，板子太挤")

    # 自检：手工旋转公式必须与 KiCad 实际庭院层一致，否则所有重叠判断都不可信
    for ref, fp in fps.items():
        if ref == "U1" or not fp.GetCourtyard(pcbnew.F_CrtYd).OutlineCount():
            continue
        fp.BuildCourtyardCaches()
        box = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
        x, y, angle = where[ref]
        mine = placed_rect(local_rect(load(next(p for p in fitted if p.ref == ref)), ref), x, y, angle)
        kicad = (box.GetX() * TO_MM, box.GetY() * TO_MM, box.GetRight() * TO_MM, box.GetBottom() * TO_MM)
        # 比中心与宽高，不比四条边：KiCad 的庭院层包围盒把 0.05mm 线宽也算进去，
        # 四边各大 0.05mm。旋转算错时宽高会互换，比宽高足以抓住
        centre = lambda r: ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)
        size = lambda r: (r[2] - r[0], r[3] - r[1])
        if (any(abs(a - b) > 0.05 for a, b in zip(centre(mine), centre(kicad)))
                or any(abs(a - b) > 0.15 for a, b in zip(size(mine), size(kicad)))):
            raise RuntimeError(f"{ref} 旋转换算与 KiCad 不一致：{mine} vs {kicad}")

    # 网络
    for part in fitted:
        for pad in fps[part.ref].Pads():
            net = part.pins.get(pad.GetNumber())
            if net and not net.startswith("NC_"):
                pad.SetNet(board.FindNet(net))

    # 分区铺铜：L2 整层 GND；L3 的 3V3 只铺逻辑区；L4 功率区铺 PGND（设计方案 4.3、6.1 节）
    add_zone(board, "GND", pcbnew.In1_Cu, 0, 0, pl.W, pl.H)
    add_zone(board, "+3V3", pcbnew.In2_Cu, 0, 0, 62.0, pl.H)
    add_zone(board, "PGND", pcbnew.B_Cu, 64.0, 0, pl.W, pl.H)

    # HC-6 丝印
    text, tx, ty = pl.HEATER_SILK
    silk = pcbnew.PCB_TEXT(board)
    silk.SetText(text)
    silk.SetPosition(v(tx, ty))
    silk.SetLayer(pcbnew.F_SilkS)
    silk.SetTextSize(v(1.0, 1.0))
    silk.SetTextThickness(pcbnew.FromMM(0.15))
    board.Add(silk)

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(PCB))
    return PCB


if __name__ == "__main__":
    print(main())
