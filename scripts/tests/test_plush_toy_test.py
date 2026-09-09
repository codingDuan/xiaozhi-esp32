import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "plush_toy_test", ROOT / "tools/plush_toy_test.py"
)
plush_toy_test = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(plush_toy_test)


class PlushToyTextTestCliTests(unittest.TestCase):
    def test_wave_maps_to_device_tool(self):
        self.assertEqual(
            plush_toy_test.command_to_call(["wave", "--side", "left", "--times", "2"]),
            ("self.limbs.wave_hand", {"side": "left", "times": 2}),
        )

    def test_eye_theme_maps_to_device_tool(self):
        self.assertEqual(
            plush_toy_test.command_to_call(["eyes", "dragon-amber"]),
            ("self.eyes.change_theme", {"theme": "dragon-amber"}),
        )

    def test_regression_order_is_safe_and_deterministic(self):
        self.assertEqual(
            [tool for tool, _ in plush_toy_test.REGRESSION_CASES],
            [
                "self.eyes.change_theme",
                "self.limbs.wave_hand",
                "self.limbs.wave_hand",
                "self.limbs.wave_hand",
                "self.limbs.hug",
                "self.limbs.cheer",
                "self.limbs.get_diagnostics",
            ],
        )
