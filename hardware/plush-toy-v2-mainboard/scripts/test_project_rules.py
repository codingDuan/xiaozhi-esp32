import json
import tempfile
import unittest
from pathlib import Path

import project_rules


class ProjectRulesTests(unittest.TestCase):
    def test_apply_writes_kicad_10_canonical_netclass_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "fixture.kicad_pro"
            project.write_text("{}\n", encoding="utf-8")

            project_rules.apply(project)

            net_settings = json.loads(project.read_text(encoding="utf-8"))["net_settings"]
            classes = net_settings["classes"]
        self.assertEqual(net_settings["meta"], {"version": 5})
        self.assertEqual(
            [item["name"] for item in classes],
            ["Default", "Audio", "CameraSupply", "Power", "Supply"],
        )
        self.assertEqual([item["tuning_profile"] for item in classes], ["", "", "", "", ""])

    def test_apply_is_byte_stable_when_run_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "fixture.kicad_pro"
            project.write_text('{"unrelated": {"keep": true}}\n', encoding="utf-8")

            project_rules.apply(project)
            first = project.read_bytes()
            project_rules.apply(project)

            self.assertEqual(project.read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
