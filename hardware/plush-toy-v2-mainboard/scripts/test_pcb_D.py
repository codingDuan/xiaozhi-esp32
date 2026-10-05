"""版本 D（摄像头、双面）PCB 验收。用 KiCad 自带 Python 运行。"""
import math
import unittest

import pcbnew

from pcb_test_base import PcbVariantTestsMixin

TO_MM = 1e-6


class PcbDTests(PcbVariantTestsMixin, unittest.TestCase):
    VARIANT = "D"

    def test_target_dimensions(self):
        self.assertEqual((self.pl.W, self.pl.H), (65.0, 55.0))

    def test_only_module_local_decoupling_connectors_and_buttons_are_front_assembly(self):
        front = {
            part.ref for part in self.ctx.parts
            if part.fitted and part.assembly and part.ref not in self.pl.BACK_PARTS
        }
        self.assertEqual(front, {
            "U1", "C_U1", "C_U1_BULK", "SW_RST", "SW_BOOT",
            "C_CAM_AVDD", "C_CAM_DVDD",
            "J_CAM", "J_USB", "J_BAT", "J_HEAT", "J_NTC", "J_LCD", "J_MIC",
            "J_SPK", "J_ARM_L", "J_ARM_R", "J_KEY", "J_TOUCH",
        })

    def test_every_other_assembly_part_is_declared_on_back(self):
        assembly = {part.ref for part in self.ctx.parts if part.fitted and part.assembly}
        front = assembly - self.pl.BACK_PARTS
        self.assertEqual(self.pl.BACK_PARTS, assembly - front)
        self.assertEqual(self.pl.BACK_PARTS - assembly, set())

    def test_board_really_has_assembly_on_both_sides(self):
        layers = {
            fp.GetLayer() for ref, fp in self.fps.items()
            if next(part for part in self.ctx.parts if part.ref == ref).assembly
        }
        self.assertEqual(layers, {pcbnew.F_Cu, pcbnew.B_Cu})

    def test_camera_connector_is_at_edge_with_direction_silk(self):
        self.assertIn("J_CAM", self.pl.EDGE_CONNECTORS)
        fp = self.fps["J_CAM"]
        silk_text = [
            item.GetText() for item in fp.GraphicalItems()
            if isinstance(item, pcbnew.PCB_TEXT) and item.GetLayer() == pcbnew.F_SilkS
        ]
        self.assertTrue(any("触点朝下" in text for text in silk_text), silk_text)

    def test_camera_ldos_are_close_to_connector_and_on_back(self):
        cam = self.fps["J_CAM"].GetPosition()
        for ref in ("U_LDO28", "U_LDO15"):
            fp = self.fps[ref]
            distance = math.hypot(fp.GetPosition().x - cam.x, fp.GetPosition().y - cam.y) * TO_MM
            with self.subTest(ref=ref):
                self.assertEqual(fp.GetLayer(), pcbnew.B_Cu)
                self.assertLessEqual(distance, 15.0)

    def test_camera_signal_series_resistors_are_all_or_none(self):
        signals = {
            "SIOD", "SIOC", "VSYNC", "HREF", "XCLK", "PCLK",
            "Y2", "Y3", "Y4", "Y5", "Y6", "Y7", "Y8", "Y9",
        }
        series = [part for part in self.ctx.parts if part.ref.startswith("R_CAM_SER_")]
        if series:
            self.assertEqual({part.ref.removeprefix("R_CAM_SER_") for part in series}, signals)
            self.assertEqual(len({part.value for part in series}), 1)


if __name__ == "__main__":
    unittest.main()
