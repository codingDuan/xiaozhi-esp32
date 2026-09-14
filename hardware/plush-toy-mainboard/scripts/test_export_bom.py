"""制造 BOM 必须使用 board_spec 的规范位号，而不是 KiCad 的自动注释结果。"""
import csv
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("export_bom.py")
sys.path.insert(0, str(SCRIPT.parent))

import fab_tools


class ExportBomTest(unittest.TestCase):
    def setUp(self):
        self.output = Path(tempfile.mkdtemp()) / "bom.csv"
        result = subprocess.run(["python3", str(SCRIPT), str(self.output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.output.open(newline="", encoding="utf-8-sig") as source:
            self.rows = list(csv.DictReader(source))

    def test_exports_each_of_the_74_automated_assembly_items_once(self):
        refs = [ref for row in self.rows for ref in row["Designator"].split(",")]
        self.assertEqual(len(refs), 74)
        self.assertEqual(len(set(refs)), 74)
        self.assertFalse(any("?" in ref for ref in refs))
        self.assertFalse(any(not row["LCSC Part #"] for row in self.rows))

    def test_excludes_dnp_mechanical_and_testpoint_items(self):
        refs = {ref for row in self.rows for ref in row["Designator"].split(",")}
        self.assertTrue({"R_SIOC", "R_SIOD", "H1", "H2", "H3", "H4"}.isdisjoint(refs))
        self.assertTrue({"J_HEAT", "J_LCD_L", "J_LCD_R", "J_SERVO_L", "J_SERVO_R",
                         "J_NTC", "J_SPK", "J_VMOT"}.isdisjoint(refs))
        self.assertFalse(any(ref.startswith("TP_") for ref in refs))

    def test_groups_identical_100nf_parts_with_correct_quantity(self):
        row = next(row for row in self.rows
                   if row["Comment"] == "100nF"
                   and row["Footprint"] == "Capacitor_SMD:C_0402_1005Metric"
                   and row["LCSC Part #"] == "C1525")
        expected = {
            "C_ADC", "C_AMP", "C_CAM_AVDD", "C_CAM_DVDD", "C_CAM_RST", "C_IMU",
            "C_IMU_REG", "C_LCD", "C_LED", "C_MIC", "C_NTC", "C_PWM", "C_TOUCH",
            "C_TOUCH_VREG", "C_U1", "C_VMOT_HF",
        }
        self.assertEqual(set(row["Designator"].split(",")), expected)
        self.assertEqual(row["Quantity"], "16")

    def test_position_filter_excludes_hand_installed_connectors(self):
        source = self.output.with_name("raw.csv")
        destination = self.output.with_name("positions.csv")
        source.write_text("Ref,Val,Package,PosX,PosY,Rot,Side\n"
                          "J_HEAT,Heater,JST,1,2,0,top\n"
                          "C_ADC,100nF,C0402,3,4,0,top\n")
        fab_tools.filter_positions(source, destination)
        with destination.open(newline="") as stream:
            self.assertEqual([row["Ref"] for row in csv.DictReader(stream)], ["C_ADC"])


if __name__ == "__main__":
    unittest.main()
