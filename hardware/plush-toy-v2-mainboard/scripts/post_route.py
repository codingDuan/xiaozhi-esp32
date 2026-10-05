"""二期布线后处理：只做重新灌铜、DRC 与非回退判定。

一期那套针对具体位号的修补不搬过来；二期遇到自动布线解决不了的开路，先改 placement，
仍不行再在本文件末尾加专门的 ECO 函数并登记位号与原因。
"""
from __future__ import annotations

import heapq
import json
import math
import shutil
import subprocess
import tempfile

import pcbnew

import kicad_env
import project_rules


def refill_and_save(ctx, path=None) -> None:
    path = path or ctx.pcb
    board = pcbnew.LoadBoard(str(path))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(path))
    # board.Save 会把默认规则写回 .kicad_pro（一期教训）
    project_rules.apply(ctx.pro)


def drc(ctx, path=None) -> dict:
    """在完整工程上下文（原理图、库表、库）里跑未过滤的 DRC 与原理图一致性检查。"""
    path = path or ctx.pcb
    with tempfile.TemporaryDirectory() as directory:
        work = __import__("pathlib").Path(directory) / "variants" / ctx.variant.name
        work.mkdir(parents=True)
        candidate = work / f"{ctx.project}.kicad_pcb"
        shutil.copy2(path, candidate)
        for suffix in (".kicad_pro", ".kicad_sch"):
            shutil.copy2(ctx.dir / f"{ctx.project}{suffix}", work / f"{ctx.project}{suffix}")
        for name in ("fp-lib-table", "sym-lib-table"):
            shutil.copy2(ctx.dir / name, work / name)
        shutil.copytree(ctx.dir.parent.parent / "lib", work.parent.parent / "lib")
        report = work / "drc.json"
        subprocess.run([kicad_env.KICAD_CLI, "pcb", "drc", "--format", "json", "--schematic-parity",
                        "-o", str(report), str(candidate)], check=True, capture_output=True)
        result = json.loads(report.read_text())
    missing = {"violations", "unconnected_items", "schematic_parity"} - result.keys()
    if missing:
        raise RuntimeError(f"DRC 报告缺少字段: {sorted(missing)}")
    return result


def summary(report: dict) -> str:
    errors = [v for v in report["violations"] if v.get("severity") == "error"]
    kinds = {}
    for v in errors:
        kinds[v["type"]] = kinds.get(v["type"], 0) + 1
    return (f"错误 {len(errors)} {kinds}；未连接 {len(report['unconnected_items'])}；"
            f"一致性 {len(report['schematic_parity'])}")

GRID = 0.10
EDGE = 0.60
BOARD_W, BOARD_H = 0.0, 0.0      # close_opens() 按当前版本设置
MAX_OPENS = 30                    # 补线只收尾；开路太多说明还没自动布线
GRID_STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1),
              (1, 1), (1, -1), (-1, 1), (-1, -1))


def net_class(net: str) -> dict:
    """按 project_rules 的网络类取线宽、间距与过孔尺寸。"""
    by_name = {c["name"]: c for c in project_rules.NETCLASSES}
    for pattern in project_rules.PATTERNS:
        if pattern["pattern"] == net:
            return by_name[pattern["netclass"]]
    return by_name["Default"]


def fallback_widths(net: str):
    """信号可退到制造下限逃逸；功率网络禁止用长细线伪装成已连接。"""
    if net_class(net)["track_width"] >= 0.6:
        return (None, 0.2)
    return (None, 0.2, project_rules.RULES["min_track_width"])


def mm(value: int) -> float:
    return value / 1e6


def vec(p: tuple[float, float]) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I(pcbnew.FromMM(p[0]), pcbnew.FromMM(p[1]))


def point_segment_distance(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 and dy == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


class Router:
    HOLE_BUCKET = 2.0

    def __init__(self, board: pcbnew.BOARD):
        self.board = board
        self._blocked_cache: dict[tuple[str, int, float], set[tuple[int, int]]] = {}
        self._holes: list[tuple[float, float, float]] | None = None
        self._hole_buckets: dict[tuple[int, int], list[tuple[float, float, float]]] = {}
        self._max_hole_diameter = 0.0

    def invalidate_obstacles(self, added_net: str | None = None) -> None:
        self._holes = None      # 新过孔对所有网络都是钻孔障碍
        self._hole_buckets = {}
        self._max_hole_diameter = 0.0
        # 新增同网络铜不会成为该网络自己的障碍，可保留其昂贵的栅格结果。
        self._blocked_cache = {
            key: value for key, value in self._blocked_cache.items()
            if added_net is not None and key[0] == added_net
        }

    def track_width(self, net: str) -> float:
        return getattr(self, "width_override", {}).get(net, net_class(net)["track_width"])

    @staticmethod
    def clearance(net: str, other_net: str) -> float:
        """两个网络按各自网络类取较严的间距。

        不能把全板 Power 类的 0.20mm 强加给彼此都是 Default/CameraSupply
        的密脚网络；0.5mm FPC 的合法 0.15mm 逃逸口会因此被误判为封死。
        """
        return max(net_class(net)["clearance"], net_class(other_net)["clearance"])

    @staticmethod
    def via_size(net: str) -> tuple[float, float]:
        c = net_class(net)
        return c["via_diameter"], c["via_drill"]

    def blocked(self, p: tuple[float, float], net: str) -> bool:
        x, y = p
        if not (EDGE <= x <= BOARD_W - EDGE and EDGE <= y <= BOARD_H - EDGE):
            return True
        margin = CLEARANCE + TRACK_W / 2
        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                if not pad.IsOnLayer(pcbnew.F_Cu) or pad.GetNetname() == net:
                    continue
                box = pad.GetBoundingBox()
                x1, y1, x2, y2 = mm(box.GetX()), mm(box.GetY()), mm(box.GetRight()), mm(box.GetBottom())
                if x1 - margin <= x <= x2 + margin and y1 - margin <= y <= y2 + margin:
                    return True
        for item in self.board.GetTracks():
            if item.GetNetname() == net:
                continue
            if item.GetClass() == "PCB_VIA":
                q = (mm(item.GetPosition().x), mm(item.GetPosition().y))
                if math.dist(p, q) < mm(item.GetWidth(pcbnew.F_Cu)) / 2 + margin:
                    return True
            elif item.GetLayer() == pcbnew.F_Cu:
                a = (mm(item.GetStart().x), mm(item.GetStart().y))
                b = (mm(item.GetEnd().x), mm(item.GetEnd().y))
                if point_segment_distance(p, a, b) < mm(item.GetWidth()) / 2 + margin:
                    return True
        return False

    def holes(self) -> list[tuple[float, float, float]]:
        """板上所有钻孔 (x, y, 孔径)：任何网络的过孔、通孔焊盘、安装孔。"""
        if self._holes is None:
            self._holes = [(mm(t.GetPosition().x), mm(t.GetPosition().y), mm(t.GetDrillValue()))
                           for t in self.board.GetTracks() if t.GetClass() == "PCB_VIA"]
            for fp in self.board.GetFootprints():
                for pad in fp.Pads():
                    if pad.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                        size = pad.GetDrillSize()
                        self._holes.append((mm(pad.GetPosition().x), mm(pad.GetPosition().y),
                                            mm(max(size.x, size.y))))
            self._max_hole_diameter = max((d for _, _, d in self._holes), default=0.0)
            for hole in self._holes:
                key = (math.floor(hole[0] / self.HOLE_BUCKET),
                       math.floor(hole[1] / self.HOLE_BUCKET))
                self._hole_buckets.setdefault(key, []).append(hole)
        return self._holes

    def hole_clear(self, net: str, p: tuple[float, float]) -> bool:
        """新过孔与已有钻孔的孔壁距离 ≥ min_hole_to_hole。障碍栅格不看同网络过孔，孔距要单独查
        （2026-10-05：补线器在同网络过孔旁 0.42mm 处又打一个，孔壁只剩 0.02mm）。"""
        _, drill = self.via_size(net)
        limit = project_rules.RULES["min_hole_to_hole"]
        self.holes()  # 懒加载钻孔空间索引
        radius = (drill + self._max_hole_diameter) / 2 + limit
        bx, by = math.floor(p[0] / self.HOLE_BUCKET), math.floor(p[1] / self.HOLE_BUCKET)
        buckets = math.ceil(radius / self.HOLE_BUCKET)
        nearby = (hole
                  for dx in range(-buckets, buckets + 1)
                  for dy in range(-buckets, buckets + 1)
                  for hole in self._hole_buckets.get((bx + dx, by + dy), ()))
        return all(math.dist(p, (x, y)) - (drill + d) / 2 >= limit for x, y, d in nearby)

    def blocked_grid(self, net: str, layer: int, width: float | None = None) -> set[tuple[int, int]]:
        """一次性栅格化障碍物，避免 A* 每个节点遍历整块板。"""
        width = self.track_width(net) if width is None else width
        key = (net, layer, width)
        if key in self._blocked_cache:
            return self._blocked_cache[key]
        blocked: set[tuple[int, int]] = set()
        def mark_rect(x1, y1, x2, y2):
            for ix in range(math.ceil(x1 / GRID), math.floor(x2 / GRID) + 1):
                for iy in range(math.ceil(y1 / GRID), math.floor(y2 / GRID) + 1):
                    blocked.add((ix, iy))

        def mark_disk(cx, cy, radius):
            steps = math.ceil(radius / GRID)
            gx, gy = self.grid_point((cx, cy))
            for dx in range(-steps, steps + 1):
                for dy in range(-steps, steps + 1):
                    p = self.physical((gx + dx, gy + dy))
                    if math.hypot(p[0] - cx, p[1] - cy) < radius:
                        blocked.add((gx + dx, gy + dy))

        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                if not pad.IsOnLayer(layer) or pad.GetNetname() == net:
                    continue
                # 障碍是按栅格中心离散化的；再留半个栅格对角线，避免两个
                # 合法中心之间的斜线实际越过净距边界。
                margin = self.clearance(net, pad.GetNetname()) + width / 2 + GRID / math.sqrt(2)
                box = pad.GetBoundingBox()
                mark_rect(mm(box.GetX()) - margin, mm(box.GetY()) - margin,
                          mm(box.GetRight()) + margin, mm(box.GetBottom()) + margin)
            for zone in fp.Zones():
                if zone.GetIsRuleArea() and zone.GetLayerSet().Contains(layer):
                    box = zone.GetBoundingBox()
                    mark_rect(mm(box.GetX()), mm(box.GetY()), mm(box.GetRight()), mm(box.GetBottom()))
        for item in self.board.GetTracks():
            if item.GetNetname() == net:
                continue
            margin = self.clearance(net, item.GetNetname()) + width / 2 + GRID / math.sqrt(2)
            if item.GetClass() == "PCB_VIA":
                p = item.GetPosition()
                mark_disk(mm(p.x), mm(p.y), mm(item.GetWidth(layer)) / 2 + margin)
            elif item.GetLayer() == layer:
                a = (mm(item.GetStart().x), mm(item.GetStart().y))
                b = (mm(item.GetEnd().x), mm(item.GetEnd().y))
                radius = mm(item.GetWidth()) / 2 + margin
                samples = max(1, math.ceil(math.dist(a, b) / (GRID / 2)))
                for i in range(samples + 1):
                    t = i / samples
                    mark_disk(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, radius)
        self._blocked_cache[key] = blocked
        return blocked

    def find_escape_path(self, net: str, start, narrow_width: float, radius: float = 2.0):
        """用短窄颈从拥挤端点逃逸到能容纳网络类线宽的位置。"""
        source = self.grid_point(start[:2])
        narrow = self.blocked_grid(net, start[2], narrow_width)
        wide = self.blocked_grid(net, start[2])
        queue = [source]
        parent = {source: None}
        for here in queue:
            if here != source and here not in wide:
                path = []
                node = here
                while node is not None:
                    path.append((*self.physical(node), start[2]))
                    node = parent[node]
                path.reverse()
                path[0] = start
                return self.compress(path)
            for dx, dy in GRID_STEPS:
                nxt = (here[0] + dx, here[1] + dy)
                if nxt in parent or nxt in narrow or math.dist(source, nxt) * GRID > radius:
                    continue
                parent[nxt] = here
                queue.append(nxt)
        raise RuntimeError(f"{net}: {start} 周围 {radius}mm 内找不到宽线逃逸点")

    @staticmethod
    def grid_point(p: tuple[float, float]) -> tuple[int, int]:
        return round(p[0] / GRID), round(p[1] / GRID)

    @staticmethod
    def physical(p: tuple[int, int]) -> tuple[float, float]:
        return p[0] * GRID, p[1] * GRID

    def find_path(self, net: str, start, end, margin: float | None = None):
        source_xy, target_xy = self.grid_point(start[:2]), self.grid_point(end[:2])
        source = (*source_xy, start[2])
        target = (*target_xy, end[2])
        bounds = None if margin is None else (
            min(start[0], end[0]) - margin, max(start[0], end[0]) + margin,
            min(start[1], end[1]) - margin, max(start[1], end[1]) + margin,
        )
        blocked = {layer: self.blocked_grid(net, layer) for layer in (pcbnew.F_Cu, pcbnew.B_Cu)}
        queue = [(0.0, source)]
        cost = {source: 0.0}
        parent = {source: None}
        while queue:
            _, here = heapq.heappop(queue)
            if here == target:
                break
            # PCB 走线允许 45°。只走四邻域会把元件密集区里实际合法的斜向通道误判为无路；
            # 候选最终仍须通过 KiCad DRC，不能靠斜跨障碍蒙混过关。
            neighbors = [(here[0] + dx, here[1] + dy, here[2])
                         for dx, dy in GRID_STEPS]
            other = pcbnew.B_Cu if here[2] == pcbnew.F_Cu else pcbnew.F_Cu
            # 过孔直径比走线宽 0.4mm；换层点周围额外两格必须在两层都空闲。
            via_diameter, _ = self.via_size(net)
            via_cells = max(0, math.ceil(((via_diameter - self.track_width(net)) / 2) / GRID))
            if all((here[0] + dx, here[1] + dy) not in blocked[layer]
                   for layer in (pcbnew.F_Cu, pcbnew.B_Cu)
                   for dx in range(-via_cells, via_cells + 1)
                   for dy in range(-via_cells, via_cells + 1)) \
                    and self.hole_clear(net, self.physical((here[0], here[1]))):
                neighbors.append((here[0], here[1], other))
            for nxt in neighbors:
                p = self.physical((nxt[0], nxt[1]))
                if not (EDGE <= p[0] <= BOARD_W - EDGE and EDGE <= p[1] <= BOARD_H - EDGE):
                    continue
                if bounds is not None and not (bounds[0] <= p[0] <= bounds[1]
                                               and bounds[2] <= p[1] <= bounds[3]):
                    continue
                if nxt != target and (nxt[0], nxt[1]) in blocked[nxt[2]]:
                    continue
                diagonal = nxt[2] == here[2] and nxt[0] != here[0] and nxt[1] != here[1]
                new_cost = cost[here] + (20 if nxt[2] != here[2] else math.sqrt(2) if diagonal else 1)
                if new_cost >= cost.get(nxt, math.inf):
                    continue
                cost[nxt] = new_cost
                parent[nxt] = here
                estimate = abs(nxt[0] - target[0]) + abs(nxt[1] - target[1])
                heapq.heappush(queue, (new_cost + estimate, nxt))
        if target not in parent:
            raise RuntimeError(f"{net}: 找不到 {start} -> {end} 的 F.Cu 净距路径")
        path = []
        node = target
        while node is not None:
            path.append((*self.physical((node[0], node[1])), node[2]))
            node = parent[node]
        path.reverse()
        path[0], path[-1] = start, end
        return self.compress(self.straighten(path, blocked))

    def straighten(self, path, blocked):
        """视线拉直：同层两点间直线经过的格子都不被占，就跳过中间的阶梯点。"""
        def clear_line(a, b):
            if a[2] != b[2]:
                return False
            n = max(1, int(math.dist(a[:2], b[:2]) / (GRID / 2)))
            for i in range(n + 1):
                p = (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
                g = self.grid_point(p)
                if g in blocked[a[2]] and g not in (self.grid_point(path[0][:2]), self.grid_point(path[-1][:2])):
                    return False
            return True
        out, i = [path[0]], 0
        while i < len(path) - 1:
            j = len(path) - 1
            while j > i + 1 and not clear_line(path[i], path[j]):
                j -= 1
            out.append(path[j])
            i = j
        return out

    def find_layer_path(self, net: str, start, end, width: float):
        """在单层用指定窄线宽连接密脚距端点，不引入额外过孔。"""
        if start[2] != end[2]:
            raise RuntimeError(f"{net}: 单层路径的起止层不同")
        layer = start[2]
        source = self.grid_point(start[:2])
        target = self.grid_point(end[:2])
        blocked = self.blocked_grid(net, layer, width)
        queue = [(0.0, source)]
        cost = {source: 0.0}
        parent = {source: None}
        while queue:
            _, here = heapq.heappop(queue)
            if here == target:
                break
            for dx, dy in GRID_STEPS:
                nxt = (here[0] + dx, here[1] + dy)
                p = self.physical(nxt)
                if not (EDGE <= p[0] <= BOARD_W - EDGE and EDGE <= p[1] <= BOARD_H - EDGE):
                    continue
                if nxt != target and nxt in blocked:
                    continue
                new_cost = cost[here] + (math.sqrt(2) if dx and dy else 1)
                if new_cost >= cost.get(nxt, math.inf):
                    continue
                cost[nxt] = new_cost
                parent[nxt] = here
                estimate = abs(nxt[0] - target[0]) + abs(nxt[1] - target[1])
                heapq.heappush(queue, (new_cost + estimate, nxt))
        if target not in parent:
            raise RuntimeError(f"{net}: 找不到 {start} -> {end} 的 {width}mm 单层路径")
        path = []
        node = target
        while node is not None:
            path.append((*self.physical(node), layer))
            node = parent[node]
        path.reverse()
        path[0], path[-1] = start, end
        return self.compress(path)

    def find_via_path(self, net: str, start: tuple[float, float, int], radius: float = 3.0,
                      width: float | None = None, min_distance: float = 0.0):
        """从指定铜层的端点找一条短线和安全的通孔位置。"""
        source = self.grid_point(start[:2])
        source_layer = start[2]
        width = self.track_width(net) if width is None else width
        blocked = {layer: self.blocked_grid(net, layer, width)
                   for layer in (pcbnew.F_Cu, pcbnew.B_Cu)}
        queue = [source]
        parent = {source: None}
        for here in queue:
            p = self.physical(here)
            via_diameter, _ = self.via_size(net)
            via_cells = max(0, math.ceil(((via_diameter - width) / 2) / GRID))
            via_clear = all((here[0] + dx, here[1] + dy) not in blocked[layer]
                            for layer in (pcbnew.F_Cu, pcbnew.B_Cu)
                            for dx in range(-via_cells, via_cells + 1)
                            for dy in range(-via_cells, via_cells + 1))
            if math.dist(start[:2], p) >= min_distance and via_clear and self.hole_clear(net, p) \
                    and EDGE <= p[0] <= BOARD_W - EDGE and EDGE <= p[1] <= BOARD_H - EDGE:
                path = []
                node = here
                while node is not None:
                    path.append((*self.physical(node), source_layer))
                    node = parent[node]
                path.reverse()
                path[0] = start
                return self.compress(path), p
            for dx, dy in GRID_STEPS:
                nxt = (here[0] + dx, here[1] + dy)
                q = self.physical(nxt)
                if nxt in parent or math.dist(start[:2], q) > radius or nxt in blocked[source_layer]:
                    continue
                parent[nxt] = here
                queue.append(nxt)
        raise RuntimeError(f"{net}: {start} 周围 {radius}mm 内找不到安全过孔点")

    @staticmethod
    def compress(path):
        if len(path) < 3:
            return path
        result = [path[0]]
        for i in range(1, len(path) - 1):
            a, b, c = result[-1], path[i], path[i + 1]
            if a[2] == b[2] == c[2] and \
                    (b[0] - a[0]) * (c[1] - b[1]) == (b[1] - a[1]) * (c[0] - b[0]):
                continue
            result.append(b)
        result.append(path[-1])
        return result

    def add_path(self, net: str, path, width: float | None = None) -> list:
        netinfo = self.board.FindNet(net)
        added = []
        for a, b in zip(path, path[1:]):
            if a[2] != b[2]:
                diameter, drill = self.via_size(net)
                via = pcbnew.PCB_VIA(self.board)
                via.SetPosition(vec((a[0], a[1])))
                via.SetWidth(pcbnew.FromMM(diameter))
                via.SetDrill(pcbnew.FromMM(drill))
                via.SetNet(netinfo)
                self.board.Add(via)
                added.append(via)
                continue
            track = pcbnew.PCB_TRACK(self.board)
            track.SetStart(vec((a[0], a[1])))
            track.SetEnd(vec((b[0], b[1])))
            track.SetWidth(pcbnew.FromMM(self.track_width(net) if width is None else width))
            track.SetLayer(a[2])
            track.SetNet(netinfo)
            self.board.Add(track)
            added.append(track)
        if added:
            self.invalidate_obstacles(net)
        return added


def _layer(description: str) -> int:
    return pcbnew.B_Cu if "on B.Cu" in description and "F.Cu - B.Cu" not in description else pcbnew.F_Cu


def _net(description: str) -> str:
    import re
    m = re.search(r"\[([^\]]+)\]", description)
    return m.group(1)


def exact_item_point(board, description: str, pos: dict, layer: int) -> tuple[float, float, int]:
    """把 DRC JSON 的四位小数显示坐标吸附回板内对象的精确坐标。

    直接用报告坐标建线时，端点可能与原线/焊盘相差几十纳米；图上看似相交，KiCad 拓扑仍判开路。
    """
    import re
    q = (pos["x"], pos["y"])
    pad = re.search(r"Pad (\S+) .* of (\S+) on ", description)
    if pad:
        fp = board.FindFootprintByReference(pad.group(2))
        if fp:
            item = fp.FindPadByNumber(pad.group(1))
            if item:
                p = item.GetPosition()
                return mm(p.x), mm(p.y), layer
    net = _net(description)
    candidates = []
    for item in board.GetTracks():
        if item.GetNetname() != net:
            continue
        if description.startswith("Via ") and item.GetClass() == "PCB_VIA":
            p = item.GetPosition()
            candidates.append((math.dist(q, (mm(p.x), mm(p.y))), p))
        elif description.startswith("Track ") and item.GetClass() == "PCB_TRACK" and item.GetLayer() == layer:
            for p in (item.GetStart(), item.GetEnd()):
                candidates.append((math.dist(q, (mm(p.x), mm(p.y))), p))
    if candidates:
        distance, p = min(candidates, key=lambda candidate: candidate[0])
        if distance <= 0.2:
            return mm(p.x), mm(p.y), layer
    return q[0], q[1], layer


def net_points(board, net: str):
    """同网络所有铜的落点：走线端点、过孔、焊盘中心，带层信息。"""
    pts = []
    for t in board.GetTracks():
        if t.GetNetname() != net:
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            pts.append((mm(p.x), mm(p.y), pcbnew.F_Cu))
        else:
            for p in (t.GetStart(), t.GetEnd()):
                pts.append((mm(p.x), mm(p.y), t.GetLayer()))
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() == net:
                p = pad.GetPosition()
                pts.append((mm(p.x), mm(p.y), pcbnew.B_Cu if pad.IsOnLayer(pcbnew.B_Cu) and not pad.IsOnLayer(pcbnew.F_Cu) else pcbnew.F_Cu))
    return pts


def _item_key(item) -> str:
    return item.m_Uuid.AsString()


def _item_at_point(board, net: str, source):
    """找到 DRC 端点所属的铜对象，用于区分同网络的两个电气孤岛。"""
    q = vec(source[:2])
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() == net and pad.IsOnLayer(source[2]) and pad.GetBoundingBox().Contains(q):
                return pad
    for item in board.GetTracks():
        if item.GetNetname() != net:
            continue
        if item.GetClass() == "PCB_VIA":
            p = item.GetPosition()
            if math.dist(source[:2], (mm(p.x), mm(p.y))) < 1e-4:
                return item
        elif item.GetLayer() == source[2]:
            if any(math.dist(source[:2], (mm(p.x), mm(p.y))) < 1e-4
                   for p in (item.GetStart(), item.GetEnd())):
                return item
    return None


def net_point_items(board, net: str):
    points = []
    for item in board.GetTracks():
        if item.GetNetname() != net:
            continue
        if item.GetClass() == "PCB_VIA":
            p = item.GetPosition()
            points.append(((mm(p.x), mm(p.y), pcbnew.F_Cu), item))
        else:
            for p in (item.GetStart(), item.GetEnd()):
                points.append(((mm(p.x), mm(p.y), item.GetLayer()), item))
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() == net:
                p = pad.GetPosition()
                layer = pcbnew.B_Cu if pad.IsOnLayer(pcbnew.B_Cu) and not pad.IsOnLayer(pcbnew.F_Cu) else pcbnew.F_Cu
                points.append(((mm(p.x), mm(p.y), layer), pad))
    return points


def connect_to_nearest(router, board, net: str, source, tries: int = 25,
                       margin: float | None = None) -> bool:
    """孤立端点只连到另一个电气孤岛的同网络铜，避免在本孤岛上绕一圈却不减少开路。"""
    source_item = _item_at_point(board, net, source)
    connected = set()
    if source_item is not None:
        connectivity = board.GetConnectivity()
        connectivity.Build(board)
        connected = {_item_key(item) for item in connectivity.GetConnectedItems(source_item)}
    candidates = (p for p, item in net_point_items(board, net)
                  if math.dist(p[:2], source[:2]) > 0.3 and _item_key(item) not in connected)
    for target in sorted(candidates, key=lambda p: math.dist(p[:2], source[:2]))[:tries]:
        for width in fallback_widths(net):
            router.width_override = {} if width is None else {net: width}
            try:
                router.add_path(net, router.find_path(net, source, target, margin), width)
                return True
            except RuntimeError:
                continue
    return False


def close_opens(ctx) -> list[str]:
    """逐个补 DRC 报出的未连接：先按网络类线宽在 F.Cu/B.Cu 间寻路（可打孔换层），
    找不到再用 0.2mm 窄线。写候选板，重新灌铜后 DRC 无错误且未连接减少才替换正式板。
    返回补上的连接列表（登记用）。"""
    global BOARD_W, BOARD_H, GRID
    BOARD_W, BOARD_H = ctx.placement.W, ctx.placement.H
    routing_grid = getattr(ctx.placement, "ROUTING_GRID", 0.10)
    routing_margin = getattr(ctx.placement, "ROUTING_MARGIN", {})
    GRID = routing_grid if isinstance(routing_grid, (int, float)) else 0.10
    report = drc(ctx)
    if len(report["unconnected_items"]) > MAX_OPENS:
        raise RuntimeError(f"未连接 {len(report['unconnected_items'])} 个，超过 {MAX_OPENS}：板子像是还没自动布线，"
                           f"先跑 route.py，或用 --from-snapshot")
    board = pcbnew.LoadBoard(str(ctx.pcb))
    fixed, failed = [], []
    # 先收敛普通信号/电源支路；密脚 GND 可能触发全板平面搜索，放最后避免阻塞
    # 本轮其他可直接减少的开路。
    items = sorted(report["unconnected_items"], key=lambda item: _net(item["items"][0]["description"]) == "GND")
    total = len(items)
    for index, item in enumerate(items, start=1):
        a, b = item["items"]
        net = _net(a["description"])
        GRID = routing_grid.get(net, 0.10) if isinstance(routing_grid, dict) else routing_grid
        # 栅格尺寸是障碍缓存的隐含参数；逐网络新建 Router，避免细/粗栅格混用旧缓存。
        router = Router(board)
        start_layer, end_layer = _layer(a["description"]), _layer(b["description"])
        start = exact_item_point(board, a["description"], a["pos"], start_layer)
        end = exact_item_point(board, b["description"], b["pos"], end_layer)
        label = f"{net}: {a['description'][:40]} → {b['description'][:40]}"
        print(f"补线 {index}/{total}: {label}", flush=True)
        if net == "GND":
            # GND 是整层平面；在密脚区做全板点到点 A* 会遍历大量等价平面点。
            # 留给下面的专用短逃逸 ECO，不阻塞其他网络收敛。
            failed.append(label + "（需 GND 平面短逃逸）")
            continue
        for width in fallback_widths(net):
            try:
                router.width_override = {} if width is None else {net: width}
                # 同层的局部断点先不考虑换层；否则双层 A* 会在每个栅格点
                # 反复评估过孔孔距，密集区的一条短线也会退化成全板搜索。
                if start[2] == end[2]:
                    try:
                        path = router.find_layer_path(net, start, end, router.track_width(net))
                    except RuntimeError:
                        path = router.find_path(net, start, end, routing_margin.get(net))
                else:
                    path = router.find_path(net, start, end, routing_margin.get(net))
                router.add_path(net, path, width)
                fixed.append(label + ("" if width is None else "（0.2mm 窄线）"))
                break
            except RuntimeError:
                continue
        else:
            margin = routing_margin.get(net)
            if connect_to_nearest(router, board, net, start, margin=margin) \
                    or connect_to_nearest(router, board, net, end, margin=margin):
                fixed.append(label + "（改连同网络最近的铜）")
            else:
                failed.append(label)
    candidate = ctx.build / "close-opens-candidate.kicad_pcb"
    board.Save(str(candidate))
    project_rules.apply(ctx.pro)
    refill_and_save(ctx, candidate)
    after = drc(ctx, candidate)
    errors = [v for v in after["violations"] if v.get("severity") == "error"]
    print("补线后：", summary(after))
    if errors or len(after["unconnected_items"]) >= len(report["unconnected_items"]):
        raise RuntimeError(f"补线结果不接受（错误 {len(errors)}，未连接 {len(after['unconnected_items'])}），候选在 {candidate}")
    candidate.replace(ctx.pcb)
    project_rules.apply(ctx.pro)
    if failed:
        print("仍未补上：", failed)
    return fixed


def _net_graph(board, net, layer=None):
    key = lambda p: (round(p.x / 1e3), round(p.y / 1e3))     # µm 网格
    adj: dict = {}
    for t in board.GetTracks():
        if t.GetNetname() == net and t.GetClass() == "PCB_TRACK" \
                and (layer is None or t.GetLayer() == layer):
            a, b, length = key(t.GetStart()), key(t.GetEnd()), t.GetLength() / 1e6
            adj.setdefault(a, []).append((b, length))
            adj.setdefault(b, []).append((a, length))
    return adj, key


def _pad_box(board, ref, number):
    fp = next(f for f in board.GetFootprints() if f.GetReference() == ref)
    box = next(p for p in fp.Pads() if p.GetNumber() == number).GetBoundingBox()
    return lambda n: box.Contains(pcbnew.VECTOR2I(n[0] * 1000, n[1] * 1000))


def surface_path(board, net: str, a, b) -> float:
    """两个焊盘之间只沿表层线（不经内层平面）的最短长度 mm；不通为无穷大。"""
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    layer = fps[a[0]].GetLayer()
    if fps[b[0]].GetLayer() != layer:
        return float("inf")
    adj, _ = _net_graph(board, net, layer)
    in_a, in_b = _pad_box(board, *a), _pad_box(board, *b)
    queue, seen = [(0.0, n) for n in adj if in_a(n)], set()
    while queue:
        d, n = heapq.heappop(queue)
        if n in seen:
            continue
        seen.add(n)
        if in_b(n):
            return d
        for m, length in adj.get(n, []):
            heapq.heappush(queue, (d + length, m))
    return float("inf")


def stitch_hot_loops(ctx) -> list[str]:
    """按 placement.HOT_LOOPS 在表层直连开关电源热回路的两端（同层寻路，先网络类线宽再 0.3mm）。
    写候选板，重新灌铜后 DRC 无错误、无未连接才替换正式板。返回补上的连线（登记用）。"""
    global BOARD_W, BOARD_H, GRID
    BOARD_W, BOARD_H = ctx.placement.W, ctx.placement.H
    GRID = getattr(ctx.placement, "ROUTING_GRID", 0.10)
    board = pcbnew.LoadBoard(str(ctx.pcb))
    router = Router(board)
    done = []
    for net, (ra, na), (rb, nb), limit in getattr(ctx.placement, "HOT_LOOPS", []):
        if surface_path(board, net, (ra, na), (rb, nb)) <= limit:
            continue                       # Freerouting 已直连
        fps = {f.GetReference(): f for f in board.GetFootprints()}
        pa = next(p for p in fps[ra].Pads() if p.GetNumber() == na).GetPosition()
        pb = next(p for p in fps[rb].Pads() if p.GetNumber() == nb).GetPosition()
        layer = fps[ra].GetLayer()
        if fps[rb].GetLayer() != layer:
            raise RuntimeError(f"热回路两端不在同一铜层：{ra} / {rb}")
        start, end = (mm(pa.x), mm(pa.y), layer), (mm(pb.x), mm(pb.y), layer)
        for width in (router.track_width(net), 0.3):
            try:
                path = router.find_layer_path(net, start, end, width)
            except RuntimeError:
                continue
            router.add_path(net, path, width)
            done.append(f"{net}: {ra}.{na} → {rb}.{nb}（{width}mm）")
            break
        else:
            print(f"热回路直连失败：{ra}.{na} → {rb}.{nb}")
    if not done:
        return done
    candidate = ctx.build / "hot-loops-candidate.kicad_pcb"
    board.Save(str(candidate))
    project_rules.apply(ctx.pro)
    refill_and_save(ctx, candidate)
    after = drc(ctx, candidate)
    errors = [v for v in after["violations"] if v.get("severity") == "error"]
    if errors or after["unconnected_items"]:
        raise RuntimeError(f"热回路直连后 DRC 不过（错误 {len(errors)}，未连接 {len(after['unconnected_items'])}），"
                           f"候选在 {candidate}")
    candidate.replace(ctx.pcb)
    project_rules.apply(ctx.pro)
    return done


if __name__ == "__main__":
    import argparse
    import context
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True)
    parser.add_argument("--from-snapshot", action="store_true",
                        help="先用 route.py 存下的 build/routed-snapshot.kicad_pcb 覆盖当前板，再补线")
    args = parser.parse_args()
    ctx = context.load(args.variant)
    if args.from_snapshot:
        shutil.copy2(ctx.build / "routed-snapshot.kicad_pcb", ctx.pcb)
    if drc(ctx)["unconnected_items"]:
        for line in close_opens(ctx):
            print("补线：", line)
    for line in stitch_hot_loops(ctx):
        print("热回路：", line)
