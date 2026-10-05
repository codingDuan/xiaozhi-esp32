"""版本 B（无摄像头、双面）布线/DRC 验收。用 KiCad 自带 Python 运行。"""
import unittest

from drc_test_base import DrcVariantTestsMixin


class DrcBTests(DrcVariantTestsMixin, unittest.TestCase):
    VARIANT = "B"


if __name__ == "__main__":
    unittest.main()
