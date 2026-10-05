"""版本 B（无摄像头、双面）PCB 验收。用 KiCad 自带 Python 运行。"""
import unittest

import pcbnew

from pcb_test_base import PcbVariantTestsMixin


class PcbBTests(PcbVariantTestsMixin, unittest.TestCase):
    VARIANT = "B"

    def test_target_dimensions(self):
        self.assertEqual((self.pl.W, self.pl.H), (50.0, 46.0))

    def test_only_module_local_decoupling_connectors_and_buttons_are_front_assembly(self):
        front = {
            part.ref for part in self.ctx.parts
            if part.fitted and part.assembly and part.ref not in self.pl.BACK_PARTS
        }
        self.assertEqual(front, {
            "U1", "C_U1", "C_U1_BULK", "SW_RST", "SW_BOOT",
            "J_USB", "J_BAT", "J_HEAT", "J_NTC", "J_LCD", "J_MIC",
            "J_SPK", "J_ARM_L", "J_ARM_R", "J_KEY", "J_TOUCH",
        })

    def test_declared_back_parts_are_assembly_parts(self):
        assembly = {part.ref for part in self.ctx.parts if part.fitted and part.assembly}
        self.assertTrue(self.pl.BACK_PARTS)
        self.assertEqual(self.pl.BACK_PARTS - assembly, set())

    def test_board_really_has_assembly_on_both_sides(self):
        layers = {
            fp.GetLayer() for fp in self.fps.values()
            if next(part for part in self.ctx.parts if part.ref == fp.GetReference()).assembly
        }
        self.assertEqual(layers, {pcbnew.F_Cu, pcbnew.B_Cu})


if __name__ == "__main__":
    unittest.main()
