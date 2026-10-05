"""版本 A 布线结果检查。用 KiCad 自带 Python 运行；先重新灌铜（没有重新灌铜的 DRC 不可信）。"""
import unittest

import context
import post_route

ctx = context.load("A")


class DrcA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        post_route.refill_and_save(ctx)
        cls.report = post_route.drc(ctx)

    def test_no_unconnected_items(self):
        self.assertEqual(len(self.report.get("unconnected_items", [])), 0)

    def test_no_drc_errors(self):
        errors = [f'{v["type"]}: {v["description"]}' for v in self.report.get("violations", [])
                  if v.get("severity") == "error"]
        self.assertEqual(errors, [])

    def test_schematic_parity(self):
        self.assertEqual(self.report.get("schematic_parity", []), [])


if __name__ == "__main__":
    unittest.main()
