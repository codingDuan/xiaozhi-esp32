import csv
import tempfile
import unittest
from pathlib import Path

import context
import export_bom
import fab_tools

ctx = context.load("A")


class ExportA(unittest.TestCase):
    def test_bom_covers_every_assembly_part_once(self):
        rows = export_bom.rows(ctx)
        refs = [r for row in rows for r in row["Designator"].split(",")]
        expected = {p.ref for p in ctx.parts if p.assembly and p.fitted}
        self.assertEqual(sorted(refs), sorted(expected))

    def test_bom_has_no_missing_lcsc(self):
        for row in export_bom.rows(ctx):
            self.assertRegex(row["LCSC Part #"], r"^C\d+$", row["Designator"])

    def test_positions_match_bom(self):
        pos = ctx.dir / "fab" / "positions.csv"
        if not pos.exists():
            self.skipTest("先运行 export_fab.sh A")
        with pos.open(encoding="utf-8-sig") as f:
            pos_refs = {r["Designator"] for r in csv.DictReader(f)}
        self.assertEqual(pos_refs, {p.ref for p in ctx.parts if p.assembly and p.fitted})

    def test_wiring_lists_every_connector(self):
        text = (ctx.dir / "WIRING.md").read_text(encoding="utf-8")
        for ref in ("J_LCD", "J_MIC", "J_SPK", "J_ARM_L", "J_ARM_R", "J_HEAT", "J_NTC",
                    "J_TOUCH", "J_KEY", "J_BAT", "J_USB"):
            self.assertIn(ref, text)


class ExportVariantConfiguration(unittest.TestCase):
    def test_paste_layers_follow_assembly_side_count(self):
        # 若双面版本漏导 B.Paste，或单面版本多交一张空钢网，本测试必须失败。
        for name, expected in {
                "A": ("F.Paste",), "B": ("F.Paste", "B.Paste"),
                "C": ("F.Paste",), "D": ("F.Paste", "B.Paste")}.items():
            with self.subTest(name=name):
                layers = fab_tools.gerber_layers(context.load(name))
                self.assertEqual(tuple(layer for layer in layers if layer.endswith(".Paste")), expected)

    def test_position_export_side_follows_assembly_side_count(self):
        for name, expected in {"A": "front", "B": "both", "C": "front", "D": "both"}.items():
            with self.subTest(name=name):
                self.assertEqual(fab_tools.position_side(context.load(name)), expected)

    def test_double_sided_raw_positions_keep_top_and_bottom_rows(self):
        # 若坐标过滤器仍假设只有正面，背面 U_CHG 会从 CPL 消失。
        ctx_b = context.load("B")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "raw.csv"
            destination = Path(directory) / "positions.csv"
            source.write_text(
                "Ref,Val,Package,PosX,PosY,Rot,Side\n"
                "U1,ESP32,module,10,11,90,top\n"
                "U_CHG,IP5306,qfn,20,21,180,bottom\n",
                encoding="utf-8",
            )
            fab_tools.filter_positions(ctx_b, source, destination)
            with destination.open(encoding="utf-8-sig") as stream:
                rows = list(csv.DictReader(stream))
        self.assertEqual(rows, [
            {"Designator": "U1", "Mid X": "10", "Mid Y": "11", "Layer": "Top", "Rotation": "90"},
            {"Designator": "U_CHG", "Mid X": "20", "Mid Y": "21", "Layer": "Bottom", "Rotation": "180"},
        ])

    def test_expected_gerber_count_includes_second_stencil(self):
        self.assertEqual(fab_tools.expected_gerber_file_count(context.load("A")), 15)
        self.assertEqual(fab_tools.expected_gerber_file_count(context.load("B")), 16)


if __name__ == "__main__":
    unittest.main()
