"""制造 BOM 必须使用 board_spec 的规范位号，而不是 KiCad 的自动注释结果。"""
import csv
import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("export_bom.py")
sys.path.insert(0, str(SCRIPT.parent))

import fab_tools
import board_spec
import export_bom


class ExportBomTest(unittest.TestCase):
    def setUp(self):
        self.output = Path(tempfile.mkdtemp()) / "bom.csv"
        result = subprocess.run(["python3", str(SCRIPT), str(self.output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.output.open(newline="", encoding="utf-8-sig") as source:
            self.rows = list(csv.DictReader(source))

    def test_exports_each_automated_assembly_item_once(self):
        refs = [ref for row in self.rows for ref in row["Designator"].split(",")]
        expected = {part.ref for part in board_spec.PARTS
                    if part.fitted and getattr(part, "assembly", True)}
        self.assertEqual(set(refs), expected)
        self.assertEqual(len(refs), len(set(refs)))
        self.assertFalse(any("?" in ref for ref in refs))
        self.assertFalse(any(not row["LCSC Part #"] for row in self.rows))

    def test_excludes_dnp_mechanical_and_testpoint_items(self):
        refs = {ref for row in self.rows for ref in row["Designator"].split(",")}
        self.assertTrue({"R_SIOC", "R_SIOD"} <= refs)
        self.assertTrue({"H1", "H2", "H3", "H4"}.isdisjoint(refs))
        self.assertTrue({"J_HEAT", "J_LCD_L", "J_LCD_R", "J_SERVO_L", "J_SERVO_R",
                         "J_NTC", "J_SPK", "J_VMOT", "J_TOUCH"}.isdisjoint(refs))
        self.assertFalse(any(ref.startswith("TP_") for ref in refs))

    def test_assembly_classifier_uses_board_spec_attribute(self):
        for ref in ("J_TOUCH", "J_VMOT", "TP_3V3", "H1"):
            with self.subTest(ref=ref):
                matches = [part for part in board_spec.PARTS if part.ref == ref]
                self.assertEqual(len(matches), 1, f"{ref} 应有且仅有一个定义")
                item = matches[0]
                self.assertFalse(export_bom.is_assembly_item(item))

    def test_groups_identical_100nf_parts_with_correct_quantity(self):
        row = next(row for row in self.rows
                   if row["Comment"] == "100nF"
                   and row["Footprint"] == "Capacitor_SMD:C_0402_1005Metric"
                   and row["LCSC Part #"] == "C1525")
        expected = {
            "C_ADC", "C_AMP", "C_BUCK_HF", "C_CAM_AVDD", "C_CAM_DVDD", "C_CAM_RST", "C_EFUSE_IN", "C_IMU",
            "C_IMU_REG", "C_LCD", "C_LED", "C_MIC", "C_NTC", "C_PWM", "C_TOUCH",
            "C_TOUCH_VREG", "C_U1", "C_VMOT_HF",
        }
        self.assertEqual(set(row["Designator"].split(",")), expected)
        self.assertEqual(row["Quantity"], "18")

    def test_position_filter_excludes_hand_installed_connectors(self):
        source = self.output.with_name("raw.csv")
        destination = self.output.with_name("positions.csv")
        source.write_text("Ref,Val,Package,PosX,PosY,Rot,Side\n"
                          "J_HEAT,Heater,JST,1,2,0,top\n"
                          "C_ADC,100nF,C0402,3,4,0,top\n")
        fab_tools.filter_positions(source, destination)
        with destination.open(newline="") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames,
                             ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
            self.assertEqual(list(reader), [{
                "Designator": "C_ADC", "Mid X": "3", "Mid Y": "4",
                "Layer": "Top", "Rotation": "0",
            }])

    def test_position_filter_maps_layers_and_normalizes_rotation(self):
        source = self.output.with_name("raw.csv")
        destination = self.output.with_name("positions.csv")
        source.write_text("Ref,Val,Package,PosX,PosY,Rot,Side\n"
                          "C_ADC,100nF,C0402,3,4,-90,bottom\n"
                          "R_EN,10k,R0402,5,6,450,top\n")
        fab_tools.filter_positions(source, destination)
        with destination.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["Layer"], "Bottom")
        self.assertEqual(rows[0]["Rotation"], "270")
        self.assertEqual(rows[1]["Layer"], "Top")
        self.assertEqual(rows[1]["Rotation"], "90")

    def test_position_filter_rejects_missing_raw_columns(self):
        source = self.output.with_name("raw.csv")
        source.write_text("Ref,PosX,PosY,Rot\nC_ADC,3,4,0\n")
        with self.assertRaisesRegex(ValueError, "缺少列"):
            fab_tools.filter_positions(source, self.output.with_name("positions.csv"))

    def test_expected_assembly_refs_uses_board_spec(self):
        expected = {part.ref for part in board_spec.PARTS if export_bom.is_assembly_item(part)}
        self.assertEqual(fab_tools.expected_assembly_refs(), expected)

    def test_position_refs_reject_duplicate_designators(self):
        positions = self.output.with_name("positions.csv")
        positions.write_text("Designator,Mid X,Mid Y,Layer,Rotation\n"
                             "C_ADC,1,2,Top,0\nC_ADC,3,4,Top,0\n")
        with self.assertRaisesRegex(ValueError, "位号重复"):
            fab_tools._position_refs(positions)

    def test_assembly_sets_must_match_board_spec(self):
        with self.assertRaisesRegex(ValueError, "装配集合不一致"):
            fab_tools.validate_assembly_sets({"C_ADC"}, {"C_ADC"})

    def test_stackup_rejects_wrong_dielectric_thickness(self):
        job = self.output.with_name("board-job.gbrjob")
        thicknesses = [0.035, 0.2104, 0.0152, 0.48, 0.0152, 0.2104, 0.035]
        types = ["Copper", "Dielectric", "Copper", "Dielectric", "Copper", "Dielectric", "Copper"]
        job.write_text(json.dumps({"MaterialStackup": [
            {"Type": kind, "Thickness": thickness}
            for kind, thickness in zip(types, thicknesses)
        ]}))
        with self.assertRaisesRegex(ValueError, "叠层"):
            fab_tools.validate_stackup(job)


if __name__ == "__main__":
    unittest.main()
