"""用 KiCad 自带 Python 运行：给贴在顶层的 GND / +3V3 焊盘接到内层平面。

为什么要这一步：Freerouting 不会主动往 power 类型的内层平面打过孔，GND 与 +3V3 焊盘
在 2026-09-14 第二次布线后仍有 41 条未连接。这些网络本来就该就近下平面，先扇出，
布线器只剩真正的信号线要走。

规则：
- GND 平面在 In1，覆盖整板；+3V3 平面在 In2，只覆盖逻辑区（x < 62，gen_pcb.add_zone）
- 只处理 F.Cu 贴片焊盘；附近已有同网络通孔焊盘（如 U1.41 模组自带的散热过孔）视为已接
- 大焊盘（散热焊盘）直接在焊盘内打过孔
- 小焊盘先试着连到同器件、同网络的散热焊盘上；不行再在焊盘外找过孔位置，
  优先朝器件中心的反方向，由近到远最多 2mm
- 间距取工程规则 Default 类的 0.15mm；非金属化孔按孔间距规则 0.25mm 再加余量取 0.3mm。
  线宽取 0.4mm 与焊盘短边中较小者，细间距引脚才挤得出去
  （首版统一 0.4mm 线宽、0.2mm 间距，0.5mm 间距的 QFN 引脚全部找不到位置）
"""
import math
from pathlib import Path

import pcbnew

import placement as pl
import project_rules

ROOT = Path(__file__).resolve().parents[1]
PCB = ROOT / "plush-toy-mainboard.kicad_pcb"
TO_MM = 1e-6

PLANES = {"GND": (0.0, pl.W), "+3V3": (0.0, 61.5)}     # 网络 → 平面在 x 方向的覆盖范围
VIA_D, VIA_DRILL = 0.6, 0.3
CLEARANCE = 0.15
HOLE_CLEARANCE = 0.3
EDGE = 0.6
MAX_TRACK_W = 0.4
BIG_PAD_AREA = 1.0          # mm²，超过视为散热焊盘，焊盘内打过孔
ALREADY_CONNECTED = 2.0     # mm，同网络通孔焊盘在此距离内视为已接平面
STEPS = (0.0, 0.3, 0.6, 1.0, 1.5, 2.0)


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
        # (网络, 包围盒, 是否非金属化孔)
        self.obstacles = [(p.GetNetname(), box_mm(p.GetBoundingBox()),
                           p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH) for p in self.pads]
        self.vias: list[tuple[str, float, float]] = []

    def clear(self, net, check) -> bool:
        return not any(n != net and check(ob, HOLE_CLEARANCE if npth else CLEARANCE)
                       for n, ob, npth in self.obstacles)

    def add_track(self, net_item, start, end, width) -> None:
        t = pcbnew.PCB_TRACK(self.board)
        t.SetStart(start)
        t.SetEnd(end)
        t.SetWidth(pcbnew.FromMM(width))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(net_item)
        self.board.Add(t)

    def add_via(self, net_item, net, x, y) -> None:
        via = pcbnew.PCB_VIA(self.board)
        via.SetPosition(v(x, y))
        via.SetWidth(pcbnew.FromMM(VIA_D))
        via.SetDrill(pcbnew.FromMM(VIA_DRILL))
        via.SetNet(net_item)
        self.board.Add(via)
        self.vias.append((net, x, y))
        self.obstacles.append((net, (x - VIA_D / 2, y - VIA_D / 2, x + VIA_D / 2, y + VIA_D / 2), False))

    def via_ok(self, net, x, y, plane) -> bool:
        if not (EDGE <= x <= pl.W - EDGE and EDGE <= y <= pl.H - EDGE and plane[0] <= x <= plane[1]):
            return False
        if any(math.hypot(x - ox, y - oy) < VIA_D + CLEARANCE for _, ox, oy in self.vias):
            return False
        return self.clear(net, lambda ob, c: circle_hits_box(x, y, VIA_D / 2 + c, ob))

    def run(self) -> tuple[int, list[str]]:
        added, skipped = 0, []
        pth = [(p.GetNetname(), p.GetPosition().x * TO_MM, p.GetPosition().y * TO_MM) for p in self.pads
               if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
        # 大焊盘先处理：小引脚要连到它们的过孔上
        targets = [p for p in self.pads
                   if p.GetNetname() in PLANES and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and p.IsOnLayer(pcbnew.F_Cu)]
        targets.sort(key=lambda p: -(p.GetSizeX() * p.GetSizeY()))
        ep_vias: dict[tuple[str, str], tuple[float, float]] = {}

        for pad in targets:
            net = pad.GetNetname()
            fp = pad.GetParentFootprint()
            ref = fp.GetReference()
            px, py = pad.GetPosition().x * TO_MM, pad.GetPosition().y * TO_MM
            plane = PLANES[net]
            if not (plane[0] <= px <= plane[1]):
                continue
            if any(n == net and math.hypot(x - px, y - py) <= ALREADY_CONNECTED for n, x, y in pth):
                continue
            if any(n == net and math.hypot(x - px, y - py) <= VIA_D for n, x, y in self.vias):
                continue
            b = box_mm(pad.GetBoundingBox())
            w, h = b[2] - b[0], b[3] - b[1]

            if w * h >= BIG_PAD_AREA:
                self.add_via(pad.GetNet(), net, px, py)          # 散热焊盘内打过孔
                ep_vias[(ref, net)] = (px, py)
                added += 1
                continue

            width = min(MAX_TRACK_W, w, h)
            half = width / 2

            # 先试连到同器件同网络散热焊盘的过孔
            if (ref, net) in ep_vias:
                ex, ey = ep_vias[(ref, net)]
                own = [o for o in self.obstacles if o[0] == net]
                if math.hypot(ex - px, ey - py) <= 3.0 and \
                        self.clear(net, lambda ob, c: segment_hits_box(px, py, ex, ey, half + c, ob)):
                    self.add_track(pad.GetNet(), pad.GetPosition(), v(ex, ey), width)
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
                    if not self.clear(net, lambda ob, c: segment_hits_box(px, py, vx, vy, half + c, ob)):
                        continue
                    self.add_via(pad.GetNet(), net, vx, vy)
                    self.add_track(pad.GetNet(), pad.GetPosition(), v(vx, vy), width)
                    added += 1
                    placed = True
                    break
                if placed:
                    break
            if not placed:
                skipped.append(f"{ref}.{pad.GetNumber()}[{net}]")
        return added, skipped


def main() -> tuple[int, list[str]]:
    board = pcbnew.LoadBoard(str(PCB))
    added, skipped = Fanout(board).run()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(PCB))
    project_rules.apply()
    return added, skipped


if __name__ == "__main__":
    added, skipped = main()
    print(f"扇出过孔 {added} 个；找不到位置 {len(skipped)} 个：{skipped}")
