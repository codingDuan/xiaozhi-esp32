"""PCB 外框、叠层、放置与网络核对。用 KiCad 自带 Python 运行：KICAD_PYTHON -m unittest test_pcb"""
import unittest
from pathlib import Path

import pcbnew

import board_spec

PCB = Path(__file__).resolve().parents[1] / "plush-toy-mainboard.kicad_pcb"
MM = 1e6
W, H = 90.0, 60.0          # 设计方案 11 节：原 70×50 放不下，委托方确认改为 90×60 单面贴片


def mm(v: int) -> float:
    return v / MM


class PcbTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PCB.exists():
            raise AssertionError(f"{PCB} 不存在，先运行 gen_pcb.py")
        cls.board = pcbnew.LoadBoard(str(PCB))
        cls.fps = {fp.GetReference(): fp for fp in cls.board.GetFootprints()}

    def test_outline_is_90_by_60(self):
        box = self.board.GetBoardEdgesBoundingBox()
        self.assertAlmostEqual(mm(box.GetWidth()), W, delta=0.2)
        self.assertAlmostEqual(mm(box.GetHeight()), H, delta=0.2)

    def test_four_copper_layers(self):
        self.assertEqual(self.board.GetCopperLayerCount(), 4)

    def test_every_fitted_part_placed_inside_outline(self):
        box = self.board.GetBoardEdgesBoundingBox()
        for part in board_spec.PARTS:
            if not part.fitted:
                continue
            with self.subTest(ref=part.ref):
                self.assertIn(part.ref, self.fps)
                court = self.fps[part.ref].GetCourtyard(pcbnew.F_CrtYd if not self.fps[part.ref].IsFlipped()
                                                         else pcbnew.B_CrtYd).BBox()
                # 天线允许伸出板边（设计方案 6.2 节），其余器件的焊盘必须在板内
                pads = self.fps[part.ref].GetBoundingBox(False)
                if part.ref != "U1":
                    self.assertTrue(box.Contains(pads.GetOrigin()) and box.Contains(pads.GetEnd()),
                                    f"{part.ref} 超出板框")
                self.assertGreater(court.GetWidth(), 0)

    def test_pad_nets_match_spec(self):
        for part in board_spec.PARTS:
            if not part.fitted:
                continue
            for pad in self.fps[part.ref].Pads():
                expected = part.pins.get(pad.GetNumber())
                if expected and not expected.startswith("NC_"):
                    with self.subTest(ref=part.ref, pad=pad.GetNumber()):
                        self.assertEqual(pad.GetNetname(), expected)

    def test_no_courtyard_overlap_on_same_side(self):
        # 用真实多边形求交，不用包围盒：U1 的庭院层是 L 形（本体 + 天线净空区），
        # 包围盒会把净空区两侧大片空白也算进去，误报它周围所有器件重叠
        items = []
        for ref, fp in self.fps.items():
            layer = pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd
            poly = fp.GetCourtyard(layer)
            if poly.OutlineCount():
                items.append((ref, fp.IsFlipped(), poly))
        overlaps = []
        for i, (ra, fa, pa) in enumerate(items):
            for rb, fb, pb in items[i + 1:]:
                if fa != fb or not pa.BBox().Intersects(pb.BBox()):
                    continue
                common = pcbnew.SHAPE_POLY_SET(pa)
                common.BooleanIntersection(pb)
                if common.OutlineCount() and common.Area() > 0:
                    overlaps.append((ra, rb))
        self.assertEqual(overlaps, [])

    def test_antenna_at_left_edge_and_power_at_right_edge(self):
        # 天线在 x=0 一端，功率区在另一端（设计方案第 7 节）
        u1 = mm(self.fps["U1"].GetPosition().x)
        self.assertLess(u1, 20.0)
        for ref in ("Q_HEAT", "J_HEAT", "J_VMOT", "C_VMOT_BULK"):
            with self.subTest(ref=ref):
                self.assertGreater(mm(self.fps[ref].GetPosition().x), W * 0.6)

    def test_hc6_heater_silkscreen_readable(self):
        # 硬约束 HC-6：加热插座旁必须印「串 KSD9700」。KiCad 内置笔画字体没有 ℃ 字形，
        # 印出来是方框（2026-09-14 渲染图实测），所以温度单位只能写成「度」
        texts = [t.GetText() for t in self.board.GetDrawings()
                 if isinstance(t, pcbnew.PCB_TEXT) and t.GetLayer() == pcbnew.F_SilkS]
        heater = [t for t in texts if "KSD9700" in t]
        self.assertEqual(len(heater), 1, f"F.SilkS 上应有且仅有一条 KSD9700 丝印，实际：{texts}")
        self.assertNotIn("℃", heater[0])
        self.assertIn("65", heater[0])
        self.assertIn("常闭", heater[0])

    def test_single_sided_assembly(self):
        flipped = sorted(ref for ref, fp in self.fps.items() if fp.IsFlipped())
        self.assertEqual(flipped, [])


if __name__ == "__main__":
    unittest.main()
