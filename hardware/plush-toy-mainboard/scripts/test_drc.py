"""布线完成后的 DRC：除已审阅的 U1 丝印告警外，零违规、零未连接。"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import kicad_env

PCB = Path(__file__).resolve().parents[1] / "plush-toy-mainboard.kicad_pcb"


class DrcTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PCB.exists():
            raise AssertionError(f"{PCB} 不存在")
        report = Path(tempfile.mkdtemp()) / "drc.json"
        subprocess.run([kicad_env.KICAD_CLI, "pcb", "drc", "--format", "json", "--schematic-parity",
                        "-o", str(report), str(PCB)], check=True, capture_output=True)
        cls.report = json.loads(report.read_text())
        for key in ("violations", "unconnected_items", "schematic_parity"):
            if key not in cls.report:
                raise AssertionError(f"DRC 报告缺少 {key}: {cls.report.keys()}")

    def _brief(self, items):
        return [(i.get("type"), i.get("description"), [x.get("description") for x in i.get("items", [])][:2])
                for i in items][:15]

    def test_only_reviewed_u1_silkscreen_edge_warnings(self):
        violations = self.report["violations"]
        self.assertEqual(len(violations), 2, self._brief(violations))
        seen_positions = set()
        for finding in violations:
            self.assertEqual(finding.get("type"), "silk_edge_clearance", self._brief(violations))
            self.assertEqual(finding.get("severity"), "warning", self._brief(violations))
            items = finding.get("items", [])
            edge = [item for item in items if item.get("description") == "Segment on Edge.Cuts"]
            silk = [item for item in items
                    if item.get("description") == "Segment of U1 on F.Silkscreen"]
            self.assertEqual(len(edge), 1, items)
            self.assertEqual(len(silk), 1, items)
            self.assertEqual(edge[0].get("pos"), {"x": 0.0, "y": 60.0})
            pos = silk[0].get("pos", {})
            seen_positions.add((pos.get("x"), pos.get("y")))
        self.assertEqual(seen_positions, {(-6.15, 20.8), (-6.15, 39.2)})

    def test_no_unconnected_items(self):
        unconnected = self.report.get("unconnected_items", [])
        self.assertEqual(len(unconnected), 0, self._brief(unconnected))

    def test_post_route_target_pads_have_no_open_connection(self):
        targets = {
            "Pad 4 [GND] of U_TOUCH on F.Cu", "Pad 8 [+3V3] of U_IMU on F.Cu",
            "Pad 9 [GND] of U_IMU on F.Cu", "Pad 11 [GND] of U_IMU on F.Cu",
            "Pad 28 [+3V3] of U_PWM on F.Cu", "Pad 8 [+3V3] of U_ADC on F.Cu",
            "Pad 4 [+2V8] of J_CAM on F.Cu", "Pad 10 [+1V5] of J_CAM on F.Cu",
            "Pad 1 [TOUCH_E0] of J_TOUCH on F.Cu", "Pad 20 [CAM_Y6] of U1 on F.Cu",
        }
        opens = [item for finding in self.report.get("unconnected_items", [])
                 for item in finding.get("items", [])
                 if item.get("description") in targets]
        self.assertEqual(opens, [], self._brief(self.report.get("unconnected_items", [])))

    def test_schematic_parity(self):
        self.assertEqual(self._brief(self.report.get("schematic_parity", [])), [])


if __name__ == "__main__":
    unittest.main()
