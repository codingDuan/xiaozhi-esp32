"""用 KiCad 自带 Python 运行：fanout.py --variant A

把顶层贴片焊盘里属于内层平面的网络（GND、+3V3、VSYS）就近打过孔接到平面。
Freerouting 不会主动往 power 类型的内层打孔（一期教训），先扇出，布线器只剩信号线。

移植自一期 fanout.py 的通用部分；一期针对具体位号的预布线不搬。规则同一期：
大焊盘（散热焊盘）焊盘内打孔；小焊盘先连同器件同网络散热焊盘的过孔，再在焊盘外由近到远找位置。
"""
import math

import pcbnew

import context
import project_rules

TO_MM = 1e-6
VIA_D, VIA_DRILL = 0.6, 0.3
CLEARANCE = 0.15
POWER_NETS = {"VUSB", "VSYS", "VBAT", "VBAT_PACK", "HEAT_LOW", "CHG_SW"}
POWER_CLEARANCE = 0.2     # Power 类间距；统一用 0.15 时 GND 过孔贴着 CHG_SW 焊盘报间距错误
HOLE_CLEARANCE = 0.3
EDGE = 0.6
MAX_TRACK_W = 0.4
BIG_PAD_AREA = 1.0          # mm²，超过视为散热焊盘，焊盘内打过孔
ALREADY_CONNECTED = 2.0     # mm，同网络通孔焊盘在此距离内视为已接平面
STEPS = (0.0, 0.3, 0.6, 1.0, 1.5, 2.0)
pl = None
PLANES = {}


def v(x: float, y: float) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def box_mm(b):
    return b.GetX() * TO_MM, b.GetY() * TO_MM, b.GetRight() * TO_MM, b.GetBottom() * TO_MM


def circle_hits_box(cx, cy, r, box) -> bool:
    nx = min(max(cx, box[0]), box[2])
    ny = min(max(cy, box[1]), box[3])
    return (cx - nx) ** 2 + (cy - ny) ** 2 < r * r


def segment_hits_box(x1, y1, x2, y2, half_w, box) -> bool:
    # 线段短（< 5mm），每 0.05mm 取一点，按「线宽一半 + 间距」为半径判断
    n = max(2, int(math.hypot(x2 - x1, y2 - y1) / 0.05))
    return any(circle_hits_box(x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n, half_w, box) for i in range(n + 1))


class Fanout:
    def __init__(self, board: pcbnew.BOARD):
        self.board = board
        self.pads = [p for fp in board.GetFootprints() for p in fp.Pads()]
        # (网络, 包围盒, 是否非金属化孔, 所在铜层集合)
        # 只有带铜的焊盘才是障碍：QFN 散热焊盘上叠的纯钢网小焊盘没有网络，
        # 算进去会挡住散热焊盘内打孔（二期首跑 U_AMP.17、U_CHG.9 因此失败）
        self.obstacles = [(p.GetNetname(), box_mm(p.GetBoundingBox()),
                           p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH, p.GetLayerSet()) for p in self.pads
                          if p.IsOnCopperLayer() or p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH]
        self.vias: list[tuple[str, float, float]] = []

    def clear(self, net, check, layer=None) -> bool:
        """每对网络按两者中较严的间距规则检查（Power 类 0.2mm，其余 0.15mm）。"""
        def gap(other, npth):
            if npth:
                return HOLE_CLEARANCE
            return POWER_CLEARANCE if net in POWER_NETS or other in POWER_NETS else CLEARANCE
        return not any(n != net and (layer is None or npth or layers.Contains(layer))
                       and check(ob, gap(n, npth)) for n, ob, npth, layers in self.obstacles)

    def add_layer_track(self, net_item, start, end, width, layer):
        t = pcbnew.PCB_TRACK(self.board)
        t.SetStart(start)
        t.SetEnd(end)
        t.SetWidth(pcbnew.FromMM(width))
        t.SetLayer(layer)
        t.SetNet(net_item)
        self.board.Add(t)
        x1, x2 = sorted((start.x * TO_MM, end.x * TO_MM))
        y1, y2 = sorted((start.y * TO_MM, end.y * TO_MM))
        layers = pcbnew.LSET()
        layers.AddLayer(layer)
        self.obstacles.append((net_item.GetNetname(),
                               (x1 - width / 2, y1 - width / 2,
                                x2 + width / 2, y2 + width / 2), False, layers))
        return t

    def add_track(self, net_item, start, end, width, layer):
        return self.add_layer_track(net_item, start, end, width, layer)

    def add_via(self, net_item, net, x, y, diameter=VIA_D, drill=VIA_DRILL):
        via = pcbnew.PCB_VIA(self.board)
        via.SetPosition(v(x, y))
        via.SetWidth(pcbnew.FromMM(diameter))
        via.SetDrill(pcbnew.FromMM(drill))
        via.SetNet(net_item)
        self.board.Add(via)
        self.vias.append((net, x, y))
        self.obstacles.append((net, (x - diameter / 2, y - diameter / 2,
                                     x + diameter / 2, y + diameter / 2), False,
                               pcbnew.LSET.AllCuMask()))
        return via

    def via_ok(self, net, x, y, plane) -> bool:
        if not (EDGE <= x <= pl.W - EDGE and EDGE <= y <= pl.H - EDGE and plane(x, y)):
            return False
        if any(math.hypot(x - ox, y - oy) < VIA_D + CLEARANCE for _, ox, oy in self.vias):
            return False
        return self.clear(net, lambda ob, c: circle_hits_box(x, y, VIA_D / 2 + c, ob))

    def connect_to_own_pad(self, pad, fp, net: str, width: float) -> bool:
        px, py = pad.GetPosition().x * TO_MM, pad.GetPosition().y * TO_MM
        for other in fp.Pads():
            if other is pad or other.GetNetname() != net or other.GetSizeX() * other.GetSizeY() * TO_MM * TO_MM < BIG_PAD_AREA:
                continue
            ex1, ey1, ex2, ey2 = box_mm(other.GetBoundingBox())
            # 目标点：散热焊盘上离本焊盘最近的点，只在横向或纵向对齐时才取（保证是直线）
            tx, ty = min(max(px, ex1), ex2), min(max(py, ey1), ey2)
            if tx != px and ty != py:
                continue
            half = width / 2
            layer = fp.GetLayer()
            if self.clear(net, lambda ob, c: segment_hits_box(px, py, tx, ty, half + c, ob), layer):
                self.add_track(pad.GetNet(), pad.GetPosition(), v(tx, ty), width, layer)
                return True
        return False

    def pad(self, ref: str, number: str):
        return self.board.FindFootprintByReference(ref).FindPadByNumber(number)

    def run(self) -> tuple[int, list[str]]:
        added = 0
        skipped = []
        pth = [(p.GetNetname(), p.GetPosition().x * TO_MM, p.GetPosition().y * TO_MM) for p in self.pads
               if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
        # 大焊盘先处理：小引脚要连到它们的过孔上
        targets = [p for p in self.pads if p.GetNetname() in PLANES
                   and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD
                   and (p.IsOnLayer(pcbnew.F_Cu) or p.IsOnLayer(pcbnew.B_Cu))]
        targets.sort(key=lambda p: -(p.GetSizeX() * p.GetSizeY()))
        ep_vias: dict[tuple[str, str], tuple[float, float]] = {}

        for pad in targets:
            net = pad.GetNetname()
            fp = pad.GetParentFootprint()
            surface_layer = fp.GetLayer()
            ref = fp.GetReference()
            px, py = pad.GetPosition().x * TO_MM, pad.GetPosition().y * TO_MM
            plane = PLANES[net]
            if not plane(px, py):
                continue
            if any(n == net and math.hypot(x - px, y - py) <= ALREADY_CONNECTED for n, x, y in pth):
                continue
            if any(n == net and math.hypot(x - px, y - py) <= VIA_D for n, x, y in self.vias):
                continue
            b = box_mm(pad.GetBoundingBox())
            w, h = b[2] - b[0], b[3] - b[1]

            if w * h >= BIG_PAD_AREA and self.via_ok(net, px, py, plane):
                self.add_via(pad.GetNet(), net, px, py)          # 散热焊盘内打过孔
                ep_vias[(ref, net)] = (px, py)
                added += 1
                continue

            width = min(MAX_TRACK_W, w, h)
            half = width / 2

            # 先试沿引脚方向直线接到同器件同网络的散热焊盘：QFN 的 GND 脚与中心焊盘相对，
            # 直线不会靠近相邻引脚（斜拉到中心过孔会，二期首跑 U_AMP 三个 GND 脚因此失败）
            if self.connect_to_own_pad(pad, fp, net, width):
                continue

            # 再试连到同器件同网络散热焊盘的过孔
            if (ref, net) in ep_vias:
                ex, ey = ep_vias[(ref, net)]
                if math.hypot(ex - px, ey - py) <= 3.0 and \
                        self.clear(net, lambda ob, c: segment_hits_box(px, py, ex, ey, half + c, ob),
                                   surface_layer):
                    self.add_track(pad.GetNet(), pad.GetPosition(), v(ex, ey), width, surface_layer)
                    continue

            cx, cy = fp.GetPosition().x * TO_MM, fp.GetPosition().y * TO_MM
            out = math.atan2(py - cy, px - cx) if (px, py) != (cx, cy) else 0.0
            directions = [out, out + math.pi / 4, out - math.pi / 4, out + math.pi / 2, out - math.pi / 2,
                          out + 3 * math.pi / 4, out - 3 * math.pi / 4, out + math.pi]
            placed = False
            for step in STEPS:
                for a in directions:
                    dx, dy = math.cos(a), math.sin(a)
                    # 焊盘在该方向上的半宽
                    extent = abs(dx) * w / 2 + abs(dy) * h / 2
                    reach = extent + CLEARANCE + VIA_D / 2 + step
                    vx, vy = px + reach * dx, py + reach * dy
                    if not self.via_ok(net, vx, vy, plane):
                        continue
                    if not self.clear(net, lambda ob, c: segment_hits_box(px, py, vx, vy, half + c, ob),
                                      surface_layer):
                        continue
                    self.add_via(pad.GetNet(), net, vx, vy)
                    self.add_track(pad.GetNet(), pad.GetPosition(), v(vx, vy), width, surface_layer)
                    added += 1
                    placed = True
                    break
                if placed:
                    break
            if not placed:
                skipped.append(f"{ref}.{pad.GetNumber()}[{net}]")
        return added, skipped


def inside_polygon(points, x: float, y: float) -> bool:
    """射线法；落在边上的点算在内（与铺铜边界的取舍无关紧要，扇出过孔另有平面间距检查）。"""
    inside = False
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        if min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2) \
                and abs((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) < 1e-9:
            return True
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def main(ctx=None) -> tuple[int, list[str]]:
    global pl, PLANES
    ctx = ctx or context.from_argv()
    pl = ctx.placement
    # 网络 → 该点是否在平面覆盖范围内（与 gen_pcb 的内层铺铜一致）
    vsys = pl.VSYS_POLY
    in_vsys = lambda x, y: inside_polygon(vsys, x, y)
    PLANES = {"GND": lambda x, y: True, "+3V3": lambda x, y: not in_vsys(x, y), "VSYS": in_vsys}
    board = pcbnew.LoadBoard(str(ctx.pcb))
    added, skipped = Fanout(board).run()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(ctx.pcb))
    project_rules.apply(ctx.pro)
    return added, skipped


if __name__ == "__main__":
    added, skipped = main()
    print(f"扇出过孔 {added} 个；找不到位置 {len(skipped)} 个：{skipped}")
