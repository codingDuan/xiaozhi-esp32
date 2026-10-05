"""四版本共用的布线结果检查 mixin；DRC 前强制重新灌铜并保存。"""
import heapq
import unittest

import pcbnew

import context
import post_route



class DrcVariantTestsMixin:
    VARIANT = None

    @classmethod
    def setUpClass(cls):
        cls.ctx = context.load(cls.VARIANT)
        post_route.refill_and_save(cls.ctx)
        cls.report = post_route.drc(cls.ctx)

    def test_no_unconnected_items(self):
        self.assertEqual(len(self.report.get("unconnected_items", [])), 0)

    def test_no_drc_errors(self):
        errors = [f'{v["type"]}: {v["description"]}' for v in self.report.get("violations", [])
                  if v.get("severity") == "error"]
        self.assertEqual(errors, [])

    def test_buck_output_reaches_3v3_plane_quickly(self):
        # 降压输出要尽快打孔进 3V3 平面（2026-10-05 复查：输出在 VSYS 区里绕了 16.8mm 表层线才进平面）
        board = pcbnew.LoadBoard(str(self.ctx.pcb))
        self.assertLessEqual(copper_to_plane_via(board, "L_BUCK", "+3V3"), 5.0)

    def test_hot_loops_closed_on_surface(self):
        board = pcbnew.LoadBoard(str(self.ctx.pcb))
        long = []
        for net, a, b, limit in self.ctx.placement.HOT_LOOPS:
            d = post_route.surface_path(board, net, a, b)
            if d > limit:
                long.append(f"{a[0]}.{a[1]} → {b[0]}.{b[1]} {d:.1f}mm > {limit}")
        self.assertEqual(long, [])

    def test_schematic_parity(self):
        self.assertEqual(self.report.get("schematic_parity", []), [])


def copper_to_plane_via(board, ref: str, net: str) -> float:
    """从器件 net 焊盘沿表层铜走到最近的同网络过孔（即进内层平面）的长度 mm；焊盘内有过孔为 0。"""
    key = lambda p: (round(p.x / 1e3), round(p.y / 1e3))     # µm 网格
    adj: dict = {}
    for t in board.GetTracks():
        if t.GetNetname() == net and t.GetClass() == "PCB_TRACK":
            a, b, length = key(t.GetStart()), key(t.GetEnd()), t.GetLength() / 1e6
            adj.setdefault(a, []).append((b, length))
            adj.setdefault(b, []).append((a, length))
    vias = {key(t.GetPosition()) for t in board.GetTracks()
            if t.GetClass() == "PCB_VIA" and t.GetNetname() == net}
    fp = next(f for f in board.GetFootprints() if f.GetReference() == ref)
    box = next(p for p in fp.Pads() if p.GetNetname() == net).GetBoundingBox()
    inside = lambda n: box.Contains(pcbnew.VECTOR2I(n[0] * 1000, n[1] * 1000))
    if any(inside(v) for v in vias):
        return 0.0
    queue, seen = [(0.0, n) for n in adj if inside(n)], set()
    while queue:
        d, n = heapq.heappop(queue)
        if n in seen:
            continue
        seen.add(n)
        if n in vias:
            return d
        for m, length in adj.get(n, []):
            heapq.heappush(queue, (d + length, m))
    return float("inf")
