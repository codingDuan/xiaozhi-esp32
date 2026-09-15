"""用 DRC 断点驱动的确定性收尾路由器。

默认只生成 build/post-route-candidate.kicad_pcb；传入 --apply 才覆盖正式 PCB。
所有新增走线位于 F.Cu，并在搜索时避让不同网络的焊盘、走线、过孔和板边。
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pcbnew

import board_spec
import gen_pcb
import kicad_env
import project_rules

ROOT = Path(__file__).resolve().parents[1]
PCB = ROOT / "plush-toy-mainboard.kicad_pcb"
CANDIDATE = ROOT / "build" / "post-route-candidate.kicad_pcb"
GRID = 0.10
TRACK_W = 0.20
CLEARANCE = 0.15
EDGE = 0.60
MIC_HOLE = (15.29, 50.00)
MIC_EXCLUSION = 0.20 + 0.25 + 0.30
POWER_WIDTHS = {
    "VMOT": 1.0, "VMOT_IN": 1.0, "PGND": 1.0, "HEAT_LOW": 1.0,
    "VBUS": 0.5, "VBUS_IN": 0.5, "+3V3": 0.5, "GND": 0.5,
    "BUCK_SW": 0.5, "SPK_P": 0.5, "SPK_N": 0.5, "+2V8": 0.5, "+1V5": 0.3,
}
CRITICAL_NETS = {"BUCK_SW", "CAM_XCLK"}


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
    def __init__(self, board: pcbnew.BOARD):
        self.board = board
        self._blocked_cache: dict[tuple[str, int, float], set[tuple[int, int]]] = {}

    def invalidate_obstacles(self, added_net: str | None = None) -> None:
        # 新增同网络铜不会成为该网络自己的障碍，可保留其昂贵的栅格结果。
        self._blocked_cache = {
            key: value for key, value in self._blocked_cache.items()
            if added_net is not None and key[0] == added_net
        }

    @staticmethod
    def track_width(net: str) -> float:
        return POWER_WIDTHS.get(net, TRACK_W)

    @staticmethod
    def clearance(net: str) -> float:
        return 0.20 if net == "PGND" else CLEARANCE

    @staticmethod
    def via_size(net: str) -> tuple[float, float]:
        return (0.8, 0.4) if net == "PGND" else (0.6, 0.3)

    def remove_microphone_via(self) -> int:
        removed = 0
        for item in list(self.board.GetTracks()):
            if item.GetClass() != "PCB_VIA" or item.GetNetname() != "GND":
                continue
            p = (mm(item.GetPosition().x), mm(item.GetPosition().y))
            if math.dist(p, MIC_HOLE) < MIC_EXCLUSION:
                self.board.Remove(item)
                removed += 1
        if removed:
            self.invalidate_obstacles()
        return removed

    def blocked(self, p: tuple[float, float], net: str) -> bool:
        x, y = p
        if not (EDGE <= x <= 90.0 - EDGE and EDGE <= y <= 60.0 - EDGE):
            return True
        if math.dist(p, MIC_HOLE) < 0.20 + 0.25 + TRACK_W / 2:
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

    def blocked_grid(self, net: str, layer: int, width: float | None = None) -> set[tuple[int, int]]:
        """一次性栅格化障碍物，避免 A* 每个节点遍历整块板。"""
        width = self.track_width(net) if width is None else width
        key = (net, layer, width)
        if key in self._blocked_cache:
            return self._blocked_cache[key]
        blocked: set[tuple[int, int]] = set()
        margin = self.clearance(net) + width / 2

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
        mark_disk(MIC_HOLE[0], MIC_HOLE[1], 0.20 + 0.25 + TRACK_W / 2)
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
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
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

    def find_path(self, net: str, start, end):
        source_xy, target_xy = self.grid_point(start[:2]), self.grid_point(end[:2])
        source = (*source_xy, start[2])
        target = (*target_xy, end[2])
        blocked = {layer: self.blocked_grid(net, layer) for layer in (pcbnew.F_Cu, pcbnew.B_Cu)}
        queue = [(0.0, source)]
        cost = {source: 0.0}
        parent = {source: None}
        while queue:
            _, here = heapq.heappop(queue)
            if here == target:
                break
            neighbors = [(here[0] + dx, here[1] + dy, here[2])
                         for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
            other = pcbnew.B_Cu if here[2] == pcbnew.F_Cu else pcbnew.F_Cu
            # 过孔直径比走线宽 0.4mm；换层点周围额外两格必须在两层都空闲。
            via_diameter, _ = self.via_size(net)
            via_cells = max(0, math.ceil(((via_diameter - self.track_width(net)) / 2) / GRID))
            if all((here[0] + dx, here[1] + dy) not in blocked[layer]
                   for layer in (pcbnew.F_Cu, pcbnew.B_Cu)
                   for dx in range(-via_cells, via_cells + 1)
                   for dy in range(-via_cells, via_cells + 1)):
                neighbors.append((here[0], here[1], other))
            for nxt in neighbors:
                p = self.physical((nxt[0], nxt[1]))
                if not (EDGE <= p[0] <= 90.0 - EDGE and EDGE <= p[1] <= 60.0 - EDGE):
                    continue
                if nxt != target and (nxt[0], nxt[1]) in blocked[nxt[2]]:
                    continue
                new_cost = cost[here] + (20 if nxt[2] != here[2] else 1)
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
        return self.compress(path)

    def find_via_path(self, net: str, start: tuple[float, float], radius: float = 3.0):
        source = self.grid_point(start)
        blocked = {layer: self.blocked_grid(net, layer) for layer in (pcbnew.F_Cu, pcbnew.B_Cu)}
        queue = [source]
        parent = {source: None}
        for here in queue:
            p = self.physical(here)
            via_diameter, _ = self.via_size(net)
            via_cells = max(0, math.ceil(((via_diameter - self.track_width(net)) / 2) / GRID))
            via_clear = all((here[0] + dx, here[1] + dy) not in blocked[layer]
                            for layer in (pcbnew.F_Cu, pcbnew.B_Cu)
                            for dx in range(-via_cells, via_cells + 1)
                            for dy in range(-via_cells, via_cells + 1))
            if here != source and via_clear and EDGE <= p[0] <= 90 - EDGE and EDGE <= p[1] <= 60 - EDGE:
                path = []
                node = here
                while node is not None:
                    path.append((*self.physical(node), pcbnew.F_Cu))
                    node = parent[node]
                path.reverse()
                path[0] = (*start, pcbnew.F_Cu)
                return self.compress(path), p
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (here[0] + dx, here[1] + dy)
                q = self.physical(nxt)
                if nxt in parent or math.dist(start, q) > radius or nxt in blocked[pcbnew.F_Cu]:
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

    def add_via(self, net: str, p: tuple[float, float]) -> None:
        diameter, drill = self.via_size(net)
        via = pcbnew.PCB_VIA(self.board)
        via.SetPosition(vec(p))
        via.SetWidth(pcbnew.FromMM(diameter))
        via.SetDrill(pcbnew.FromMM(drill))
        via.SetNet(self.board.FindNet(net))
        self.board.Add(via)
        self.invalidate_obstacles(net)


def drc(path: Path) -> dict:
    """在完整工程上下文中运行未过滤的 DRC 与原理图一致性检查。"""
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        stem = PCB.stem
        candidate = work / f"{stem}.kicad_pcb"
        shutil.copy2(path, candidate)
        for suffix in (".kicad_pro", ".kicad_sch"):
            shutil.copy2(ROOT / f"{stem}{suffix}", work / f"{stem}{suffix}")
        for name in ("fp-lib-table", "sym-lib-table"):
            shutil.copy2(ROOT / name, work / name)
        shutil.copytree(ROOT / "lib", work / "lib")
        report = work / "drc.json"
        command = [kicad_env.KICAD_CLI, "pcb", "drc", "--format", "json",
                   "--schematic-parity", "-o", str(report), str(candidate)]
        subprocess.run(command, check=True, capture_output=True)
        result = json.loads(report.read_text())
    missing = {"violations", "unconnected_items", "schematic_parity"} - result.keys()
    if missing:
        raise RuntimeError(f"DRC 报告缺少字段: {sorted(missing)}")
    return result


def reviewed_u1_silk_warnings(violations: list[dict]) -> bool:
    if len(violations) != 2:
        return False
    for finding in violations:
        descriptions = [item.get("description", "") for item in finding.get("items", [])]
        if finding.get("type") != "silk_edge_clearance" \
                or not any("Segment of U1 on F.Silkscreen" in text for text in descriptions) \
                or not any("Edge.Cuts" in text for text in descriptions):
            return False
    return True


def redundant_hole_via_uuid(finding: dict) -> str | None:
    """只识别已人工确认的 J_SERVO_L.3 紧邻冗余 PGND 过孔。"""
    items = finding.get("items", [])
    if finding.get("type") != "hole_to_hole" or len(items) != 2:
        return None
    descriptions = [item.get("description", "") for item in items]
    if not any(text.startswith("PTH pad 3 [PGND] of J_SERVO_L") for text in descriptions):
        return None
    vias = [item.get("uuid") for item in items
            if item.get("description", "").startswith("Via [PGND]")]
    return vias[0] if len(vias) == 1 else None


def clean_drc_warnings(board: pcbnew.BOARD, path: Path) -> tuple[pcbnew.BOARD, dict[str, int]]:
    """移除不承载连接的残余铜，并隐藏/裁掉违规丝印。

    Freerouting 与确定性扇出组合后可能留下已被另一条路径替代的短 stub。KiCad 把它们
    标为 dangling；在未连接数已经为零时逐段删除是安全的。孔间距告警中的过孔同理：
    通孔焊盘本身已经贯穿所有铜层，不需要紧贴它再打一颗过孔。
    """
    totals = {"copper": 0, "references": 0}
    for _ in range(20):
        board.Save(str(path))
        project_rules.apply()
        report = drc(path)
        tracks = {item.m_Uuid.AsString(): item for item in board.GetTracks()}
        footprints = {fp.GetReference(): fp for fp in board.GetFootprints()}
        copper_uuids: set[str] = set()
        reference_names: set[str] = set()
        for finding in report.get("violations", []):
            kind = finding.get("type")
            items = finding.get("items", [])
            if kind in ("via_dangling", "track_dangling"):
                candidates = [item.get("uuid") for item in items]
            elif kind == "hole_to_hole":
                candidate = redundant_hole_via_uuid(finding)
                candidates = [candidate] if candidate else []
            else:
                candidates = []
            for item_uuid in candidates:
                if item_uuid in tracks:
                    copper_uuids.add(item_uuid)
            if kind == "silk_overlap":
                for item in items:
                    match = re.match(r"Reference field of (\S+)", item.get("description", ""))
                    if match and match.group(1) in footprints \
                            and not match.group(1).startswith(("J_", "U")):
                        reference_names.add(match.group(1))
        changed = bool(copper_uuids or reference_names)
        # KiCad 的 SWIG 包装在 Remove() 后会使之前取得的兄弟对象 proxy 失效，
        # 因此先改字段，再删板级铜对象。
        for ref in reference_names:
            footprints[ref].Reference().SetVisible(False)
            totals["references"] += 1
        for item_uuid in copper_uuids:
            board.Delete(tracks[item_uuid])
            totals["copper"] += 1
        if not changed:
            return board, totals
        board.Save(str(path))
        project_rules.apply()
        # Delete() 同时释放对象；Remove() 会留下失效的 SWIG proxy 并在下一轮崩溃。
    raise RuntimeError("清理 DRC warning 超过 20 轮仍未收敛")


def restore_u1_library_graphics(board: pcbnew.BOARD) -> None:
    """恢复 ESP32 模组的标准库图形，避免收尾脚本把封装变成私有变体。"""
    target = next(fp for fp in board.GetFootprints() if fp.GetReference() == "U1")
    source = pcbnew.FootprintLoad(str(kicad_env.footprint_dir("RF_Module")), "ESP32-S3-WROOM-1")
    if source is None:
        raise RuntimeError("无法加载 RF_Module:ESP32-S3-WROOM-1")
    source.SetPosition(target.GetPosition())
    source.SetOrientation(target.GetOrientation())
    for item in list(target.GraphicalItems()):
        target.Delete(item)
    for item in source.GraphicalItems():
        target.Add(item.Duplicate())


def retidy_silkscreen(board: pcbnew.BOARD) -> int:
    """按完整丝印图形重新放位号，确保接插件和 IC 位号保持可见。"""
    fitted = [part for part in board_spec.PARTS if part.fitted]
    footprints = {fp.GetReference(): fp for fp in board.GetFootprints()}
    reserved = [item.GetBoundingBox() for item in board.GetDrawings()
                if isinstance(item, pcbnew.PCB_TEXT) and item.GetLayer() == pcbnew.F_SilkS]
    return gen_pcb.tidy_silkscreen(fitted, footprints, reserved)


def sync_footprint_metadata(board: pcbnew.BOARD) -> None:
    """把 board_spec 的装配字段同步到已布线 PCB，不重建或移动封装。"""
    parts = {part.ref: part for part in board_spec.PARTS if part.fitted}
    for fp in board.GetFootprints():
        part = parts.get(fp.GetReference())
        if part is not None and part.lcsc:
            fp.SetField("LCSC", part.lcsc)
            fp.GetField("LCSC").SetVisible(False)


def sync_schematic_unconnected_nets(board: pcbnew.BOARD, report: dict) -> int:
    """让 PCB 的明确 NC 焊盘采用 KiCad 原理图生成的 unconnected-* 网络名。"""
    pads = {pad.m_Uuid.AsString(): pad for fp in board.GetFootprints() for pad in fp.Pads()}
    changed = 0
    for finding in report.get("schematic_parity", []):
        match = re.fullmatch(r"Pad missing net given by schematic \((unconnected-.+)\)",
                             finding.get("description", ""))
        if not match:
            continue
        name = match.group(1)
        net = board.FindNet(name)
        if net is None:
            net = pcbnew.NETINFO_ITEM(board, name)
            board.Add(net)
        for item in finding.get("items", []):
            pad = pads.get(item.get("uuid"))
            if pad is not None and not pad.GetNetname():
                pad.SetNet(net)
                changed += 1
    return changed


def reroute_long_power_tracks(board: pcbnew.BOARD, router: Router) -> int:
    """按网络类宽度重走超过 2mm 的窄线；原路径找不到替代时恢复，不留下半成品。"""
    changed = 0
    candidates = []
    vias = {(item.GetNetname(), item.GetPosition().x, item.GetPosition().y)
            for item in board.GetTracks() if item.GetClass() == "PCB_VIA"}
    for item in list(board.GetTracks()):
        if item.GetClass() != "PCB_TRACK":
            continue
        if item.GetNetname() in CRITICAL_NETS:
            continue
        width = POWER_WIDTHS.get(item.GetNetname())
        endpoints = ((item.GetNetname(), item.GetStart().x, item.GetStart().y),
                     (item.GetNetname(), item.GetEnd().x, item.GetEnd().y))
        plane_fanout = item.GetNetname() == "GND" and mm(item.GetLength()) <= 3.0 \
            and any(point in vias for point in endpoints)
        if width is not None and not plane_fanout \
                and mm(item.GetLength()) > 2.0 and mm(item.GetWidth()) < width:
            candidates.append(item)
    for item in candidates:
        net = item.GetNetname()
        start = (mm(item.GetStart().x), mm(item.GetStart().y), item.GetLayer())
        end = (mm(item.GetEnd().x), mm(item.GetEnd().y), item.GetLayer())
        backup = item.Duplicate()
        narrow_width = mm(backup.GetWidth())
        board.Delete(item)
        router.invalidate_obstacles()
        added = []
        try:
            start_escape = router.find_escape_path(net, start, narrow_width)
            end_escape = router.find_escape_path(net, end, narrow_width)
            added += router.add_path(net, start_escape, narrow_width)
            added += router.add_path(net, end_escape, narrow_width)
            added += router.add_path(net, router.find_path(net, start_escape[-1], end_escape[-1]))
        except RuntimeError:
            for track in added:
                board.Delete(track)
            board.Add(backup)
            continue
        changed += 1
    return changed


def open_pairs(report: dict, board: pcbnew.BOARD):
    objects = {item.m_Uuid.AsString(): item for item in board.GetTracks()}
    objects.update({pad.m_Uuid.AsString(): pad for fp in board.GetFootprints() for pad in fp.Pads()})

    def endpoints(report_item):
        item = objects.get(report_item.get("uuid"))
        if item is None:
            point = report_item["pos"]
            layer = pcbnew.B_Cu if "on B.Cu" in report_item.get("description", "") else pcbnew.F_Cu
            return [(point["x"], point["y"], layer)]
        if item.GetClass() == "PCB_TRACK":
            return [(mm(p.x), mm(p.y), item.GetLayer()) for p in (item.GetStart(), item.GetEnd())]
        if item.GetClass() == "PCB_VIA":
            p = item.GetPosition()
            return [(mm(p.x), mm(p.y), pcbnew.F_Cu), (mm(p.x), mm(p.y), pcbnew.B_Cu)]
        p = item.GetPosition()
        attached = []
        for track in board.GetTracks():
            if track.GetClass() != "PCB_TRACK" or track.GetNetname() != item.GetNetname():
                continue
            if track.GetStart() == p:
                other = track.GetEnd()
            elif track.GetEnd() == p:
                other = track.GetStart()
            else:
                continue
            attached.append((mm(other.x), mm(other.y), track.GetLayer()))
        if attached:
            return attached
        layers = [layer for layer in (pcbnew.F_Cu, pcbnew.B_Cu) if item.IsOnLayer(layer)]
        return [(mm(p.x), mm(p.y), layer) for layer in layers]

    pairs = []
    for finding in report.get("unconnected_items", []):
        items = finding.get("items", [])
        if len(items) != 2:
            continue
        match = re.search(r"\[([^]]+)]", items[0].get("description", ""))
        if not match:
            continue
        if match.group(1) in CRITICAL_NETS:
            continue
        candidates = [(a, b) for a in endpoints(items[0]) for b in endpoints(items[1])]
        if candidates:
            start, end = min(candidates, key=lambda pair: math.dist(pair[0][:2], pair[1][:2]))
            pairs.append((match.group(1), start, end))
    return pairs


def main(apply: bool) -> None:
    CANDIDATE.parent.mkdir(exist_ok=True)
    board = pcbnew.LoadBoard(str(PCB))
    initial_report = drc(PCB)
    pairs = open_pairs(initial_report, board)
    router = Router(board)
    restore_u1_library_graphics(board)
    retidy_silkscreen(board)
    sync_footprint_metadata(board)
    synced_nc = sync_schematic_unconnected_nets(board, initial_report)
    widened = reroute_long_power_tracks(board, router)

    def connect_pair(net, start, end):
        try:
            path = router.find_path(net, start, end)
            router.add_path(net, path)
            print(f"{net}: {start} -> {end}，{len(path) - 1} 段")
            return
        except RuntimeError:
            pass
        # 密脚距器件的焊盘中心可能被相邻焊盘的净距栅格夹住。先沿焊盘长轴
        # 逃逸到器件外，再从开阔区完成跨层搜索。
        for distance in (1.5, 2.5):
            for dx, dy in ((0, distance), (0, -distance), (distance, 0), (-distance, 0)):
                escape = (start[0] + dx, start[1] + dy, start[2])
                try:
                    first = router.find_path(net, start, escape)
                    second = router.find_path(net, escape, end)
                except RuntimeError:
                    continue
                router.add_path(net, first)
                router.add_path(net, second)
                print(f"{net}: {start} 经 {escape} -> {end}")
                return
        vias = []
        for endpoint in (start, end):
            try:
                via_path, via_at = router.find_via_path(net, endpoint[:2], radius=8.0)
            except RuntimeError as exc:
                print(f"跳过 {net}: {exc}")
                return False
            router.add_path(net, via_path)
            if via_at not in vias:
                router.add_via(net, via_at)
            vias.append(via_at)
            print(f"{net}: 端点 {endpoint} 扇出到过孔 {via_at}")
        if vias[0] != vias[1]:
            path = router.find_path(net, (*vias[0], pcbnew.B_Cu), (*vias[1], pcbnew.B_Cu))
            router.add_path(net, path)
        return True

    for net, start, end in pairs:
        connect_pair(net, start, end)
    removed = router.remove_microphone_via()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(CANDIDATE))
    project_rules.apply()
    board, cleaned = clean_drc_warnings(board, CANDIDATE)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(CANDIDATE))
    project_rules.apply()
    del router
    del board
    report = drc(CANDIDATE)
    errors = report["violations"]
    opens = report.get("unconnected_items", [])
    parity = report["schematic_parity"]
    reviewed = reviewed_u1_silk_warnings(errors)
    print(f"候选结果：{len(errors)} 个 DRC 告警（U1 已审阅={reviewed}），{len(opens)} 条未连接，"
          f"{len(parity)} 条原理图一致性问题；"
          f"移除声孔过孔 {removed} 个，同步 NC 焊盘 {synced_nc} 个，"
          f"重走电源线 {widened} 条，清理 {cleaned}")
    if not reviewed or opens or parity:
        raise SystemExit(1)
    if apply:
        CANDIDATE.replace(PCB)
        project_rules.apply()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    main(parser.parse_args().apply)
