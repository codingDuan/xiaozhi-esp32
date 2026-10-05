"""版本 C（摄像头、单面）PCB 验收。用 KiCad 自带 Python 运行。"""
import math
import unittest

import pcbnew

from pcb_test_base import PcbVariantTestsMixin

TO_MM = 1e-6


class PcbCTests(PcbVariantTestsMixin, unittest.TestCase):
    VARIANT = "C"

    def test_target_dimensions(self):
        self.assertEqual((self.pl.W, self.pl.H), (65.0, 55.0))

    def test_all_assembly_parts_are_front(self):
        back = {
            ref for ref, fp in self.fps.items()
            if fp.GetLayer() == pcbnew.B_Cu and not ref.startswith("TP_")
        }
        self.assertEqual(back, set())

    def test_camera_connector_is_at_edge_with_direction_silk(self):
        self.assertIn("J_CAM", self.pl.EDGE_CONNECTORS)
        fp = self.fps["J_CAM"]
        silk_text = [
            item.GetText() for item in fp.GraphicalItems()
            if isinstance(item, pcbnew.PCB_TEXT) and item.GetLayer() == pcbnew.F_SilkS
        ]
        self.assertTrue(any("触点朝下" in text for text in silk_text), silk_text)
        silk_lines = [
            item for item in fp.GraphicalItems()
            if isinstance(item, pcbnew.PCB_SHAPE) and item.GetLayer() == pcbnew.F_SilkS
        ]
        self.assertGreaterEqual(len(silk_lines), 3)  # 插入方向箭头

    def test_camera_ldos_are_close_to_connector(self):
        cam = self.fps["J_CAM"].GetPosition()
        for ref in ("U_LDO28", "U_LDO15"):
            p = self.fps[ref].GetPosition()
            distance = math.hypot(p.x - cam.x, p.y - cam.y) * TO_MM
            with self.subTest(ref=ref):
                self.assertLessEqual(distance, 15.0)

    def test_camera_signal_series_resistors_are_all_or_none(self):
        signals = {
            "SIOD", "SIOC", "VSYNC", "HREF", "XCLK", "PCLK",
            "Y2", "Y3", "Y4", "Y5", "Y6", "Y7", "Y8", "Y9",
        }
        series = [
            part for part in self.ctx.parts
            if part.ref.startswith("R_CAM_SER_")
        ]
        if series:
            self.assertEqual({part.ref.removeprefix("R_CAM_SER_") for part in series}, signals)
            self.assertEqual(len({part.value for part in series}), 1)


if __name__ == "__main__":
    unittest.main()
