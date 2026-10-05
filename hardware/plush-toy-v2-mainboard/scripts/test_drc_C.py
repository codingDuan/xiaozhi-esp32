"""版本 C（摄像头、单面）布线/DRC 验收。用 KiCad 自带 Python 运行。"""
import unittest

from drc_test_base import DrcVariantTestsMixin


class DrcCTests(DrcVariantTestsMixin, unittest.TestCase):
    VARIANT = "C"


if __name__ == "__main__":
    unittest.main()
