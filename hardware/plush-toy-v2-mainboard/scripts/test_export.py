import csv
import unittest

import context
import export_bom

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


if __name__ == "__main__":
    unittest.main()
