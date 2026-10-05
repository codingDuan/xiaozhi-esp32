"""版本 A 的 PCB 结构检查。用 KiCad 自带 Python 运行。"""
import unittest

import pcbnew

import context

ctx = context.load("A")
pl = ctx.placement
TO_MM = 1e-6


class PcbATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = pcbnew.LoadBoard(str(ctx.pcb))
        cls.fps = {f.GetReference(): f for f in cls.board.GetFootprints()}

    def test_outline_matches_placement(self):
        bb = self.board.GetBoardEdgesBoundingBox()
        self.assertAlmostEqual(bb.GetWidth() * TO_MM, pl.W, delta=0.15)
        self.assertAlmostEqual(bb.GetHeight() * TO_MM, pl.H, delta=0.15)

    def test_every_part_placed(self):
        self.assertEqual({p.ref for p in ctx.parts} - set(self.fps), set())

    def test_single_sided(self):
        back = [r for r, f in self.fps.items() if f.GetLayer() == pcbnew.B_Cu and not r.startswith("TP_")]
        self.assertEqual(back, [])

    def test_testpoints_on_back(self):
        for r, f in self.fps.items():
            if r.startswith("TP_"):
                self.assertEqual(f.GetLayer(), pcbnew.B_Cu, r)

    def test_testpoint_names_printed_on_back(self):
        # 验收清单让人按丝印名找测试点（一期委托方曾找不到测试点）
        edge = self.board.GetBoardEdgesBoundingBox()
        back_pads = [p.GetBoundingBox() for f in self.fps.values() for p in f.Pads()
                     if p.IsOnLayer(pcbnew.B_Cu)]
        for r, f in self.fps.items():
            if not r.startswith("TP_"):
                continue
            ref = f.Reference()
            self.assertTrue(ref.IsVisible(), r)
            self.assertEqual(ref.GetLayer(), pcbnew.B_SilkS, r)
            self.assertTrue(ref.IsMirrored(), r)
            bb = ref.GetBoundingBox()
            self.assertTrue(edge.Contains(bb.GetOrigin()) and edge.Contains(bb.GetEnd()), r)
            self.assertFalse(any(bb.Intersects(p) for p in back_pads), r)

    def test_pad_nets_match_spec(self):
        for part in ctx.parts:
            for pad in self.fps[part.ref].Pads():
                want = part.pins.get(pad.GetNumber())
                if want and not want.startswith("NC_"):
                    with self.subTest(ref=part.ref, pad=pad.GetNumber()):
                        self.assertEqual(pad.GetNetname(), want)

    def test_antenna_overhangs_edge(self):
        bb = self.fps["U1"].GetBoundingBox(False)
        edges = self.board.GetBoardEdgesBoundingBox()
        self.assertTrue(bb.GetLeft() < edges.GetLeft() or bb.GetTop() < edges.GetTop()
                        or bb.GetRight() > edges.GetRight() or bb.GetBottom() > edges.GetBottom())

    def test_edge_connectors_touch_their_edge(self):
        for ref, (side, _) in pl.EDGE_CONNECTORS.items():
            fp = self.fps[ref]
            fp.BuildCourtyardCaches()
            court = fp.GetCourtyard(pcbnew.F_CrtYd)
            bb = court.BBox() if court.OutlineCount() else fp.GetBoundingBox(False)
            gap = {"top": bb.GetTop() * TO_MM, "bottom": pl.H - bb.GetBottom() * TO_MM,
                   "left": bb.GetLeft() * TO_MM, "right": pl.W - bb.GetRight() * TO_MM}[side]
            with self.subTest(ref=ref):
                self.assertLessEqual(gap, 1.0)

    def test_heat_and_charger_away_from_battery_connector(self):
        def centre(ref):
            p = self.fps[ref].GetPosition()
            return p.x * TO_MM, p.y * TO_MM
        bx, by = centre("J_BAT")
        for ref in ("Q_HEAT", "U_CHG", "U_BUCK"):
            x, y = centre(ref)
            with self.subTest(ref=ref):
                self.assertGreaterEqual(((x - bx) ** 2 + (y - by) ** 2) ** 0.5, 8.0)

    def test_inner_layers_are_power_planes(self):
        for layer in (pcbnew.In1_Cu, pcbnew.In2_Cu):
            self.assertEqual(self.board.GetLayerType(layer), pcbnew.LT_POWER)

    def test_no_courtyard_overlap_on_same_side(self):
        for side, layer in ((pcbnew.F_Cu, pcbnew.F_CrtYd), (pcbnew.B_Cu, pcbnew.B_CrtYd)):
            fps = [f for f in self.fps.values() if f.GetLayer() == side]
            for f in fps:
                f.BuildCourtyardCaches()
            for i, a in enumerate(fps):
                ca = a.GetCourtyard(layer)
                for b in fps[i + 1:]:
                    cb = b.GetCourtyard(layer)
                    if ca.OutlineCount() and cb.OutlineCount():
                        with self.subTest(a=a.GetReference(), b=b.GetReference()):
                            self.assertFalse(ca.Collide(cb.Outline(0)))


if __name__ == "__main__":
    unittest.main()
