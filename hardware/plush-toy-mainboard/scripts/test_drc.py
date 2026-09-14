"""布线完成后的 DRC：零错误、零未连接、与原理图一致。

用系统 Python 运行，调用 kicad-cli。严重度只看 error：警告（如丝印压器件本体）另行人工判断。
"""
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
                        "--severity-error", "-o", str(report), str(PCB)],
                       check=False, capture_output=True)
        cls.report = json.loads(report.read_text())

    def _brief(self, items):
        return [(i.get("type"), i.get("description"), [x.get("description") for x in i.get("items", [])][:2])
                for i in items][:15]

    def test_no_drc_errors(self):
        self.assertEqual(self._brief(self.report.get("violations", [])), [])

    def test_no_unconnected_items(self):
        unconnected = self.report.get("unconnected_items", [])
        self.assertEqual(len(unconnected), 0, self._brief(unconnected))

    def test_post_route_target_pads_have_no_open_connection(self):
        targets = {
            "Pad 4 [GND] of U_TOUCH on F.Cu", "Pad 8 [+3V3] of U_IMU on F.Cu",
            "Pad 9 [GND] of U_IMU on F.Cu", "Pad 11 [GND] of U_IMU on F.Cu",
            "Pad 28 [+3V3] of U_PWM on F.Cu", "Pad 8 [+3V3] of U_ADC on F.Cu",
            "Pad 4 [+2V8] of J_CAM on F.Cu", "Pad 10 [+1V5] of J_CAM on F.Cu",
            "Pad 1 [TOUCH_E0] of TP_E0 on F.Cu", "Pad 20 [CAM_Y6] of U1 on F.Cu",
        }
        opens = [item for finding in self.report.get("unconnected_items", [])
                 for item in finding.get("items", [])
                 if item.get("description") in targets]
        self.assertEqual(opens, [], self._brief(self.report.get("unconnected_items", [])))

    def test_schematic_parity(self):
        self.assertEqual(self._brief(self.report.get("schematic_parity", [])), [])


if __name__ == "__main__":
    unittest.main()
