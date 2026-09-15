"""工程自带库的几何核对。用 KiCad 自带 Python 运行：KICAD_PYTHON -m unittest test_project_lib

INMP441 焊盘坐标的推导见 make_inmp441_footprint.py 文件头。这里把推导结果钉死：
任何人改动生成脚本导致焊盘编号或位置变化，这条测试会拦下来。
"""
import unittest
from pathlib import Path

import pcbnew

import board_spec
import kicad_env
import test_part_pins

PRETTY = Path(__file__).resolve().parents[1] / "lib/plush.pretty"
MM = 1e6


class Inmp441FootprintTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 库目录不存在时 pcbnew.FootprintLoad 只会报 NoneType 没有 FootprintLoad，看不出原因
        if not PRETTY.is_dir():
            raise AssertionError(f"工程封装库不存在：{PRETTY}，先运行 make_inmp441_footprint.py")
        cls.fp = pcbnew.FootprintLoad(str(PRETTY), "InvenSense_INMP441_LGA-9_4.72x3.76mm")
        if cls.fp is None:
            raise AssertionError("InvenSense_INMP441_LGA-9_4.72x3.76mm 加载失败，文件缺失或格式错误")

    def pads(self):
        return {p.GetNumber(): p for p in self.fp.Pads() if p.GetNumber()}

    def test_nine_numbered_pads_and_one_sound_hole(self):
        self.assertEqual(sorted(self.pads(), key=int), [str(n) for n in range(1, 10)])
        holes = [p for p in self.fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH]
        self.assertEqual(len(holes), 1)
        # 0.4mm：铜环内径 0.96，孔到铜 (0.96-0.4)/2 = 0.28mm，满足工程规则 min_hole_clearance 0.25。
        # 原取 0.5（数据手册推荐 0.5-1）时只剩 0.23mm，DRC 报 hole_clearance。
        # 0.4 仍大于声孔下限 0.25，不影响灵敏度（DS-INMP441-00 第 17 页）
        self.assertAlmostEqual(holes[0].GetDrillSize().x / MM, 0.4, places=3)

    def test_rows_follow_mirrored_bottom_view(self):
        expected = {
            "9": (-1.86, -1.33), "8": (-0.81, -1.33), "7": (0.24, -1.33), "6": (1.29, -1.33),
            "1": (-1.86, 1.33), "2": (-0.81, 1.33), "3": (0.24, 1.33), "4": (1.29, 1.33),
        }
        pads = self.pads()
        for number, (x, y) in expected.items():
            pos = pads[number].GetPosition()
            with self.subTest(pad=number):
                self.assertAlmostEqual(pos.x / MM, x, places=2)
                self.assertAlmostEqual(pos.y / MM, y, places=2)
                self.assertAlmostEqual(pads[number].GetSize().x / MM, 0.40, places=3)
                self.assertAlmostEqual(pads[number].GetSize().y / MM, 0.60, places=3)

    def test_sound_hole_centered_in_ground_ring(self):
        hole = next(p for p in self.fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH)
        self.assertAlmostEqual(hole.GetPosition().x / MM, 1.29, places=2)
        self.assertAlmostEqual(hole.GetPosition().y / MM, 0.0, places=2)
        ring = self.pads()["5"]
        box = ring.GetBoundingBox()
        self.assertAlmostEqual(box.GetWidth() / MM, 1.56, delta=0.02)
        self.assertAlmostEqual(box.Centre().x / MM, 1.29, delta=0.02)


class RevisedPartLibraryTest(unittest.TestCase):
    def test_tps259531_symbol_and_footprint_expose_all_nine_pads(self):
        self.assertTrue(kicad_env.symbol_exists("plush", "TPS259531"),
                        "缺少按 TI 数据手册绘制的 plush:TPS259531 符号")
        expected = {str(number) for number in range(1, 10)}
        self.assertEqual(test_part_pins.symbol_pins("plush:TPS259531"), expected)
        self.assertEqual(test_part_pins.footprint_pads(
            "Package_SON:Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm_ThermalVias"), expected)

    def test_ws2812b_v6_uses_verified_pin_order_and_four_pad_footprint(self):
        led = next(part for part in board_spec.PARTS if part.ref == "D_LED")
        self.assertEqual(led.pins, {
            "1": "NC_D_LED_DOUT", "2": "GND", "3": "LED_RGB", "4": "+3V3",
        })
        self.assertEqual(test_part_pins.footprint_pads(led.footprint), {"1", "2", "3", "4"})


if __name__ == "__main__":
    unittest.main()
