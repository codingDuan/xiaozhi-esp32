"""用 KiCad 自带 Python 运行：gen_pcb.py --variant A

生成当前版本的 .kicad_pcb：圆角外框、4 层、器件放置、网络、内层平面、丝印。移植自一期
hardware/plush-toy-mainboard/scripts/gen_pcb.py，放置算法相同：

- 出线座按 placement.EDGE_CONNECTORS 贴边，离边距离按封装实际占位计算
- placement.ANCHORS 定点
- 其余按 placement.NEAR 从目标点螺旋向外找第一个不重叠、在板内的位置
- 测试点按 placement.BACK_NEAR 放背面，只与背面器件比重叠

重叠判断用矩形：庭院层 ∪ 焊盘。U1 的庭院层含板外天线净空区，只取本体。
"""
import math
from pathlib import Path

import pcbnew

import context
import kicad_env
import project_rules

TO_MM = 1e-6
CTX = None
pl = None


def v(x: float, y: float) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def load(part) -> pcbnew.FOOTPRINT:
    lib, name = part.footprint.split(":", 1)
    fp = pcbnew.FootprintLoad(str(kicad_env.footprint_dir(lib)), name)
    if fp is None:
        raise RuntimeError(f"{part.ref} 封装加载失败：{part.footprint}")
    fp.SetFPIDAsString(part.footprint)
    fp.SetReference(part.ref)
    fp.SetValue(part.value)
    fp.SetExcludedFromBOM(not part.assembly)
    fp.SetExcludedFromPosFiles(not part.assembly)
    if part.lcsc:
        fp.SetField("LCSC", part.lcsc)
        fp.GetField("LCSC").SetVisible(False)
    return fp


def local_rect(fp: pcbnew.FOOTPRINT, ref: str, include_pads: bool = True) -> tuple[float, float, float, float]:
    """封装在原点、0° 时的占位矩形 (x1, y1, x2, y2)：庭院层 ∪ 焊盘（一期教训：第三方封装庭院层可能比焊盘小）。"""
    court = fp.GetCourtyard(pcbnew.F_CrtYd)
    if court.OutlineCount():
        outline = court.Outline(0)
        pts = [(outline.CPoint(i).x * TO_MM, outline.CPoint(i).y * TO_MM) for i in range(outline.PointCount())]
        if ref == "U1":
            pts = [p for p in pts if abs(p[0]) <= 10.0]   # 只取模组本体，净空区在板外
    else:
        pts = []
    if ref != "U1" and (include_pads or not pts):
        # 只取焊盘，不取外形线：卧贴排针把伸出板外的长针也画在封装图形里，
        # 按整个外形算会把座子整体推进板内十几毫米
        for pad in fp.Pads():
            box = pad.GetBoundingBox()
            pts += [(box.GetX() * TO_MM, box.GetY() * TO_MM), (box.GetRight() * TO_MM, box.GetBottom() * TO_MM)]
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
    g = pl.GAP
    return not (a[2] + g <= b[0] or b[2] + g <= a[0] or a[3] + g <= b[1] or b[3] + g <= a[1])


def inside_board(rect) -> bool:
    """矩形四角都在「缩进 EDGE_MARGIN 的圆角板框」里。"""
    m, r = pl.EDGE_MARGIN, pl.CORNER_R
    x1, y1, x2, y2 = rect
    if x1 < m or y1 < m or x2 > pl.W - m or y2 > pl.H - m:
        return False
    for cx, cy in ((r, r), (pl.W - r, r), (r, pl.H - r), (pl.W - r, pl.H - r)):
        for px in (x1, x2):
            for py in (y1, y2):
                in_corner = (px < r if cx == r else px > pl.W - r) and (py < r if cy == r else py > pl.H - r)
                if in_corner and math.hypot(px - cx, py - cy) > r - m:
                    return False
    return True


def spiral(cx: float, cy: float, step: float = 0.5, max_r: float = 60.0):
    yield cx, cy
    r = step
    while r <= max_r:
        n = max(8, int(2 * math.pi * r / step))
        for k in range(n):
            a = 2 * math.pi * k / n
            yield cx + r * math.cos(a), cy + r * math.sin(a)
        r += step


def edge_position(local, side: str, along: float) -> tuple[float, float, int]:
    """出线座贴边：返回 (x, y, 角度)，使占位矩形外沿正好距板边 EDGE_MARGIN。"""
    angle = pl.EDGE_ANGLE[side]
    rx1, ry1, rx2, ry2 = placed_rect(local, 0.0, 0.0, angle)
    m = pl.EDGE_MARGIN
    if side == "top":
        return along - (rx1 + rx2) / 2, m - ry1, angle
    if side == "bottom":
        return along - (rx1 + rx2) / 2, pl.H - m - ry2, angle
    if side == "right":
        return pl.W - m - rx2, along - (ry1 + ry2) / 2, angle
    return m - rx1, along - (ry1 + ry2) / 2, angle


SILK_HEIGHT = 0.8          # 嘉立创字高下限 0.8mm（委托方 2026-10-05 要求字号小一点）；线宽 ≥ 0.15mm、距焊盘 ≥ 0.25mm
SILK_STROKE = 0.15
SILK_MIN_HEIGHT = 0.8      # 嘉立创字高绝对下限
SILK_PAD_CLEARANCE = 0.25

STACKUP = '''\t\t(stackup
\t\t\t(layer "F.SilkS" (type "Top Silk Screen"))
\t\t\t(layer "F.Paste" (type "Top Solder Paste"))
\t\t\t(layer "F.Mask" (type "Top Solder Mask") (color "Green") (thickness 0.01))
\t\t\t(layer "F.Cu" (type "copper") (thickness 0.035))
\t\t\t(layer "dielectric 1" (type "prepreg") (thickness 0.2104) (material "7628") (epsilon_r 4.2) (loss_tangent 0.02))
\t\t\t(layer "In1.Cu" (type "copper") (thickness 0.0152))
\t\t\t(layer "dielectric 2" (type "core") (thickness 1.065) (material "FR4") (epsilon_r 4.2) (loss_tangent 0.02))
\t\t\t(layer "In2.Cu" (type "copper") (thickness 0.0152))
\t\t\t(layer "dielectric 3" (type "prepreg") (thickness 0.2104) (material "7628") (epsilon_r 4.2) (loss_tangent 0.02))
\t\t\t(layer "B.Cu" (type "copper") (thickness 0.035))
\t\t\t(layer "B.Mask" (type "Bottom Solder Mask") (color "Green") (thickness 0.01))
\t\t\t(layer "B.Paste" (type "Bottom Solder Paste"))
\t\t\t(layer "B.SilkS" (type "Bottom Silk Screen"))
\t\t\t(copper_finish "None")
\t\t\t(dielectric_constraints no)
\t\t)
'''


def apply_stackup(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    marker = "\t(setup\n"
    if marker not in text:
        raise RuntimeError(f"{path} 找不到 setup 块")
    if "\t\t(stackup\n" in text:
        raise RuntimeError(f"{path} 已存在 stackup，拒绝重复插入")
    path.write_text(text.replace(marker, marker + STACKUP, 1), encoding="utf-8")


def add_silk_text(board, text: str, x: float, y: float, justify: str = "center") -> pcbnew.PCB_TEXT:
    silk = pcbnew.PCB_TEXT(board)
    silk.SetText(text)
    if justify == "right":
        silk.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_RIGHT)
    elif justify == "left":
        silk.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
    silk.SetPosition(v(x, y))
    silk.SetLayer(pcbnew.F_SilkS)
    silk.SetTextSize(v(SILK_HEIGHT, SILK_HEIGHT))
    silk.SetTextThickness(pcbnew.FromMM(SILK_STROKE))
    board.Add(silk)
    return silk


def label_candidates(fp, side: str) -> list[tuple[float, float]]:
    """出线座功能名的候选位置：朝板内一侧由近到远，每一圈再沿边左右错开。"""
    bb = pad_box(fp)
    l, t, r, b = bb.GetX() * TO_MM, bb.GetY() * TO_MM, bb.GetRight() * TO_MM, bb.GetBottom() * TO_MM
    cx, cy = (l + r) / 2, (t + b) / 2
    out = []
    for d in (2.6, 3.4, 4.2, 5.0, 6.0, 7.0):
        for s in (0.0, -2.0, 2.0, -4.0, 4.0):
            out.append({"top": (cx + s, b + d), "bottom": (cx + s, t - d),
                        "right": (l - d - 2.0, cy + s), "left": (r + d + 2.0, cy + s)}[side])
    return out


def pad_box(fp) -> pcbnew.BOX2I:
    box = None
    for pad in fp.Pads():
        b = pad.GetBoundingBox()
        if box is None:
            box = b
        else:
            box.Merge(b)
    return box


def must_label(part) -> bool:
    return part.ref.startswith("U")       # 芯片必须印位号，返修要找得到；接插件已有功能名


def place_text(item, candidates, blocked, board_box) -> bool:
    """在候选位置里找第一个不压焊盘、不压已有文字、不出板的位置；先 1.0mm 字高再 0.8mm。"""
    for height in sorted({SILK_HEIGHT, SILK_MIN_HEIGHT}, reverse=True):
        item.SetTextSize(v(height, height))
        for angle in (0, 90):
            item.SetTextAngleDegrees(angle)
            for x, y in candidates:
                item.SetPosition(v(x, y))
                bb = item.GetBoundingBox()
                if board_box.Contains(bb.GetOrigin()) and board_box.Contains(bb.GetEnd()) \
                        and not any(bb.Intersects(o) for o in blocked):
                    blocked.append(bb)
                    return True
    return False


def body_box(fp) -> pcbnew.BOX2I:
    """器件本体占位：庭院层包围盒；U1 的庭院层含板外天线区，用焊盘范围。"""
    if fp.GetReference() == "U1":
        return pad_box(fp)
    fp.BuildCourtyardCaches()
    court = fp.GetCourtyard(pcbnew.F_CrtYd)
    return court.BBox() if court.OutlineCount() else fp.GetBoundingBox(False)


INWARD = {"top": (0, 1), "bottom": (0, -1), "right": (-1, 0), "left": (1, 0)}


def place_pin_legends(board, fps, blocked, board_box) -> list:
    """每个焊盘朝板内一侧贴一个简短标注；上下边的座子标注竖排（与引脚方向一致）。
    按焊盘实际坐标放，标注不会与针序错位。"""
    boxes, failed = [], []
    boxes_of = {ref: [] for ref in pl.PIN_LEGEND}
    pitch, row2 = {}, {}
    for ref, tokens in pl.PIN_LEGEND.items():
        p1, p2 = fps[ref].FindPadByNumber("1").GetPosition(), fps[ref].FindPadByNumber("2").GetPosition()
        pitch[ref] = math.hypot(p1.x - p2.x, p1.y - p2.y) * TO_MM
        probe = add_silk_text(board, max(tokens, key=len), 0, 0)
        probe.SetTextAngleDegrees(90)
        row2[ref] = probe.GetBoundingBox().GetHeight() * TO_MM + 0.3
        board.Remove(probe)
    for ref, tokens in pl.PIN_LEGEND.items():
        side = pl.EDGE_CONNECTORS[ref][0]
        court = body_box(fps[ref])
        for number, token in enumerate(tokens, start=1):
            pad = fps[ref].FindPadByNumber(str(number))
            pb = pad.GetBoundingBox()
            text = add_silk_text(board, token, 0, 0)
            # 单个字符横排：竖排的「-」会被看成「|」
            text.SetTextAngleDegrees(90 if side in ("top", "bottom") and len(token) > 1 else 0)
            px, py = pad.GetPosition().x * TO_MM, pad.GetPosition().y * TO_MM
            text.SetPosition(v(px, py))
            tb = text.GetBoundingBox()
            # 沿板内方向推到「庭院层与焊盘」外沿再留间距，横向对齐焊盘中心
            gap = SILK_PAD_CLEARANCE + 0.1
            if side == "top":
                shift = (0, max(court.GetBottom(), pb.GetBottom()) * TO_MM + gap - tb.GetY() * TO_MM)
            elif side == "bottom":
                shift = (0, min(court.GetY(), pb.GetY()) * TO_MM - gap - tb.GetBottom() * TO_MM)
            elif side == "right":
                shift = (min(court.GetX(), pb.GetX()) * TO_MM - gap - tb.GetRight() * TO_MM, 0)
            else:
                shift = (max(court.GetRight(), pb.GetRight()) * TO_MM + gap - tb.GetX() * TO_MM, 0)
            # 间距小于 1.6mm 的座子两排交错：偶数脚排在本座子最长标注之外
            if pitch[ref] < 1.6 and number % 2 == 0:
                dx, dy = INWARD[side]
                shift = (shift[0] + dx * row2[ref], shift[1] + dy * row2[ref])
            text.SetPosition(v(px + shift[0], py + shift[1]))
            tb = text.GetBoundingBox()
            if not (board_box.Contains(tb.GetOrigin()) and board_box.Contains(tb.GetEnd())) \
                    or any(tb.Intersects(o) for o in blocked):
                why = "出板" if not (board_box.Contains(tb.GetOrigin()) and board_box.Contains(tb.GetEnd())) else \
                    ",".join(sorted({f.GetReference() for f in fps.values()
                                     if any(tb.Intersects(p.GetBoundingBox()) for p in f.Pads())
                                     or tb.Intersects(body_box(f))} | ({"标注"} if any(tb.Intersects(o) for o in boxes) else set())))
                failed.append(f"{ref}.{number}({why})")
                continue
            blocked.append(tb)
            boxes.append(tb)
            boxes_of[ref].append(tb)
    if failed:
        raise RuntimeError(f"这些引脚标注放不下：{failed}，需要调整 placement")
    return boxes


def place_connector_labels(board, fps) -> list:
    """出线座一放好就排功能名（spec 4 节），只避让已放器件的焊盘与丝印；返回文字框，
    自动排布的器件要避开这些位置。"""
    blocked = []
    for fp in fps.values():
        for p in fp.Pads():
            box = p.GetBoundingBox()
            box.Inflate(pcbnew.FromMM(SILK_PAD_CLEARANCE))
            blocked.append(box)
        blocked += [item.GetBoundingBox() for item in fp.GraphicalItems() if item.GetLayer() == pcbnew.F_SilkS]
    board_box = pcbnew.BOX2I(v(0.3, 0.3), v(pl.W - 0.6, pl.H - 0.6))
    legends = place_pin_legends(board, fps, blocked, board_box)
    # 功能名不能印在器件本体底下（会被挡住）：已放器件的本体都避开
    blocked += [body_box(fp) for fp in fps.values()]
    boxes, failed = list(legends), []
    for ref, text in pl.CONNECTOR_LABELS.items():
        label = add_silk_text(board, text, 0, 0)
        if place_text(label, label_candidates(fps[ref], pl.EDGE_CONNECTORS[ref][0]), blocked, board_box):
            boxes.append(label.GetBoundingBox())
        else:
            failed.append(ref)
    if failed:
        raise RuntimeError(f"这些出线座的功能名找不到丝印位置：{failed}，需要调整 placement")
    return boxes


def tidy_silkscreen(board, fitted, fps, reserved) -> int:
    """位号统一 1.0mm / 0.15mm，在器件四周找不压焊盘、不压其他文字、不出板的位置。
    阻容、背面测试点、接插件（已印功能名）不印位号；芯片放不下时隐藏。"""
    blocked = list(reserved) + [body_box(fp) for fp in fps.values() if fp.GetLayer() == pcbnew.F_Cu]
    for fp in fps.values():
        for p in fp.Pads():
            if p.IsOnLayer(pcbnew.F_Cu):
                box = p.GetBoundingBox()
                box.Inflate(pcbnew.FromMM(SILK_PAD_CLEARANCE))
                blocked.append(box)
        blocked += [item.GetBoundingBox() for item in fp.GraphicalItems() if item.GetLayer() == pcbnew.F_SilkS]
    board_box = pcbnew.BOX2I(v(0.3, 0.3), v(pl.W - 0.6, pl.H - 0.6))
    small = ("Device:R", "Device:C", "Device:L", "Device:D_TVS", "Device:Thermistor_NTC", "Device:Fuse")
    labelled = [p for p in fitted
                if not (p.symbol in small or p.ref.startswith(("TP_", "J_", "H")))]
    for part in fitted:
        fps[part.ref].Value().SetVisible(False)
        if part not in labelled:
            fps[part.ref].Reference().SetVisible(False)
    order = sorted(labelled, key=lambda p: (not must_label(p), -fps[p.ref].GetBoundingBox(False).GetArea()))
    hidden, failed = 0, []
    for part in order:
        fp = fps[part.ref]
        ref = fp.Reference()
        ref.SetVisible(True)
        ref.SetLayer(pcbnew.F_SilkS)
        ref.SetTextSize(v(SILK_HEIGHT, SILK_HEIGHT))
        ref.SetTextThickness(pcbnew.FromMM(SILK_STROKE))
        # U1 外形含板外天线区，按焊盘范围找位置
        box = pad_box(fp) if part.ref == "U1" else fp.GetBoundingBox(False)
        l, t = box.GetX() * TO_MM, box.GetY() * TO_MM
        r, b = box.GetRight() * TO_MM, box.GetBottom() * TO_MM
        cx, cy = (l + r) / 2, (t + b) / 2
        candidates = []
        for d in (0.8, 1.6, 2.6, 3.8):
            candidates += [(cx, t - d), (cx, b + d), (l - d - 1.5, cy), (r + d + 1.5, cy),
                           (l, t - d), (r, t - d), (l, b + d), (r, b + d)]
        candidates.append((cx, cy))
        if not place_text(ref, candidates, blocked, board_box):
            ref.SetVisible(False)
            if must_label(part):
                failed.append(part.ref)
            else:
                hidden += 1
    if failed:
        # 二期板子密，芯片位号放不下时隐藏而不报错；位号仍在装配层（F.Fab），返修可查
        print(f"丝印：这些芯片位号放不下已隐藏：{failed}")
    return hidden + len(failed)


def add_outline(board) -> None:
    """圆角矩形：4 段直线 + 4 段圆弧。"""
    W, H, r = pl.W, pl.H, pl.CORNER_R
    k = r * (1 - math.sqrt(0.5))           # 圆弧中点距直角顶点的偏移
    segs = [((r, 0), (W - r, 0)), ((W, r), (W, H - r)), ((W - r, H), (r, H)), ((0, H - r), (0, r))]
    arcs = [((W - r, 0), (W - k, k), (W, r)), ((W, H - r), (W - k, H - k), (W - r, H)),
            ((r, H), (k, H - k), (0, H - r)), ((0, r), (k, k), (r, 0))]
    for (x1, y1), (x2, y2) in segs:
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(v(x1, y1))
        seg.SetEnd(v(x2, y2))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(pcbnew.FromMM(0.1))
        board.Add(seg)
    for start, mid, end in arcs:
        arc = pcbnew.PCB_SHAPE(board)
        arc.SetShape(pcbnew.SHAPE_T_ARC)
        arc.SetArcGeometry(v(*start), v(*mid), v(*end))
        arc.SetLayer(pcbnew.Edge_Cuts)
        arc.SetWidth(pcbnew.FromMM(0.1))
        board.Add(arc)


def add_zone(board, net: str, layer: int, x1: float, y1: float, x2: float, y2: float) -> None:
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    zone.SetNet(board.FindNet(net))
    outline = zone.Outline()
    outline.NewOutline()
    for x, y in [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]:
        outline.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    board.Add(zone)


def main(ctx=None) -> Path:
    global CTX, pl
    CTX = ctx or context.from_argv()
    pl = CTX.placement
    CTX.build.mkdir(parents=True, exist_ok=True)
    # 先写临时文件，全部成功后再替换正式文件（一期 2026-09-14 教训：NewBoard 抹掉过正式板）
    tmp = CTX.build / "gen.tmp.kicad_pcb"
    board = pcbnew.NewBoard(str(tmp))
    board.SetCopperLayerCount(4)
    # 内层整层平面标成 power，Freerouting 只打过孔接平面，不在上面走信号（一期教训）
    board.SetLayerType(pcbnew.In1_Cu, pcbnew.LT_POWER)
    board.SetLayerType(pcbnew.In2_Cu, pcbnew.LT_POWER)
    add_outline(board)
    for name in CTX.nets:
        if not name.startswith("NC_"):
            board.Add(pcbnew.NETINFO_ITEM(board, name))

    fitted = [p for p in CTX.parts if p.fitted]
    known = set(pl.ANCHORS) | set(pl.NEAR) | set(pl.EDGE_CONNECTORS) | set(pl.BACK_NEAR)
    missing = [p.ref for p in fitted if p.ref not in known]
    if missing:
        raise RuntimeError(f"placement 没有给出这些位号的位置：{missing}")

    occupied: list = []
    occupied_back: list = []
    where: dict[str, tuple[float, float, int]] = {}
    fps: dict[str, pcbnew.FOOTPRINT] = {}

    def commit(part, fp, x, y, angle, rect, back=False):
        fp.SetPosition(v(x, y))
        fp.SetOrientationDegrees(angle)
        board.Add(fp)
        if back:
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        (occupied_back if back else occupied).append(rect)
        where[part.ref] = (x, y, angle)
        fps[part.ref] = fp

    problems = []
    fixed = [(p, pl.EDGE_CONNECTORS.get(p.ref)) for p in fitted
             if p.ref in pl.ANCHORS or p.ref in pl.EDGE_CONNECTORS]
    fixed_rects: dict[str, tuple] = {}
    for part, edge in fixed:
        fp = load(part)
        local = local_rect(fp, part.ref)
        x, y, angle = edge_position(local, *edge) if edge else pl.ANCHORS[part.ref]
        rect = placed_rect(local, x, y, angle)
        if part.ref != "U1" and not inside_board(rect):
            problems.append(f"{part.ref} 超出板边 {tuple(round(c, 2) for c in rect)}")
        for other, r in fixed_rects.items():
            if overlaps(rect, r):
                problems.append(f"{part.ref} 与 {other} 重叠")
        fixed_rects[part.ref] = rect
        commit(part, fp, x, y, angle, rect)
    if problems:
        raise RuntimeError("定点器件位置有误：\n  " + "\n  ".join(problems))

    def auto_place(parts, targets, pool, back=False):
        loaded = {p.ref: load(p) for p in parts}
        size = {}
        for p in parts:
            r = local_rect(loaded[p.ref], p.ref)
            size[p.ref] = (r[2] - r[0]) * (r[3] - r[1])
        pending = sorted(parts, key=lambda p: -size[p.ref])
        while pending:
            # 目标器件还没放的先跳过，等它放好再排（NEAR 可以指向自动排布的器件）
            ready = [p for p in pending if not isinstance(targets[p.ref], str) or targets[p.ref] in where]
            if not ready:
                raise RuntimeError(f"NEAR 目标循环或缺失：{[p.ref for p in pending]}")
            for part in ready:
                pending.remove(part)
                fp = loaded[part.ref]
                target = targets[part.ref]
                cx, cy = (where[target][0], where[target][1]) if isinstance(target, str) else target
                local = local_rect(fp, part.ref)
                for x, y in spiral(cx, cy):
                    x, y = round(x * 4) / 4, round(y * 4) / 4        # 0.25mm 网格
                    found = None
                    for angle in (0, 90):
                        rect = placed_rect(local, x, y, angle)
                        if inside_board(rect) and not any(overlaps(rect, r) for r in pool):
                            found = (angle, rect)
                            break
                    if found:
                        commit(part, fp, x, y, found[0], found[1], back)
                        break
                else:
                    raise RuntimeError(f"{part.ref} 在 {target} 附近找不到空位，板子太挤")

    label_boxes = place_connector_labels(board, fps)
    occupied += [(b.GetX() * TO_MM, b.GetY() * TO_MM, b.GetRight() * TO_MM, b.GetBottom() * TO_MM)
                 for b in label_boxes]
    auto_place([p for p in fitted if p.ref in pl.NEAR], pl.NEAR, occupied)
    auto_place([p for p in fitted if p.ref in pl.BACK_NEAR], pl.BACK_NEAR, occupied_back, back=True)

    # 自检：手工旋转公式必须与 KiCad 实际庭院层一致，否则所有重叠判断都不可信
    for ref, fp in fps.items():
        if ref == "U1" or fp.GetLayer() == pcbnew.B_Cu or not fp.GetCourtyard(pcbnew.F_CrtYd).OutlineCount():
            continue
        fp.BuildCourtyardCaches()
        box = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
        x, y, angle = where[ref]
        mine = placed_rect(local_rect(load(next(p for p in fitted if p.ref == ref)), ref, include_pads=False),
                           x, y, angle)
        kicad = (box.GetX() * TO_MM, box.GetY() * TO_MM, box.GetRight() * TO_MM, box.GetBottom() * TO_MM)
        centre = lambda r: ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)
        size = lambda r: (r[2] - r[0], r[3] - r[1])
        if (any(abs(a - b) > 0.05 for a, b in zip(centre(mine), centre(kicad)))
                or any(abs(a - b) > 0.15 for a, b in zip(size(mine), size(kicad)))):
            raise RuntimeError(f"{ref} 旋转换算与 KiCad 不一致：{mine} vs {kicad}")

    for part in fitted:
        for pad in fps[part.ref].Pads():
            net = part.pins.get(pad.GetNumber())
            if net and not net.startswith("NC_"):
                pad.SetNet(board.FindNet(net))
    # USB 外壳脚只承担屏蔽接地；内层整面地用实连，避免细长热焊盘辐条被截断
    for pad in fps["J_USB"].Pads():
        if pad.GetNumber() == "SH":
            pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)

    hidden = tidy_silkscreen(board, fitted, fps, label_boxes)
    print(f"丝印：{hidden} 个位号找不到空位已隐藏")

    add_zone(board, "GND", pcbnew.In1_Cu, 0, 0, pl.W, pl.H)
    add_zone(board, "+3V3", pcbnew.In2_Cu, 0, 0, pl.VSYS_PLANE_X, pl.H)
    add_zone(board, "VSYS", pcbnew.In2_Cu, pl.VSYS_PLANE_X, 0, pl.W, pl.H)

    board.Save(str(tmp))
    apply_stackup(tmp)
    tmp.replace(CTX.pcb)
    for leftover in (tmp.with_suffix(".kicad_pro"), tmp.with_suffix(".kicad_prl")):
        leftover.unlink(missing_ok=True)
    # 铺铜必须在加载正式工程规则之后再灌（一期教训：临时板按默认规则灌铜离孔、离边都不够）
    project_rules.apply(CTX.pro)
    board = pcbnew.LoadBoard(str(CTX.pcb))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(CTX.pcb))
    # board.Save 会把内存里的默认工程设置写回 .kicad_pro，必须再写一次规则（一期教训）
    project_rules.apply(CTX.pro)
    return CTX.pcb


if __name__ == "__main__":
    print(main())
