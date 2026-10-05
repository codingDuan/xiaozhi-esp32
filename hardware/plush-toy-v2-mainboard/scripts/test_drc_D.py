"""版本 D（摄像头、双面）布线/DRC 验收。用 KiCad 自带 Python 运行。"""
import unittest

import context
import post_route

from drc_test_base import DrcVariantTestsMixin


class DrcDTests(DrcVariantTestsMixin, unittest.TestCase):
    VARIANT = "D"

    def test_per_net_routing_grid_resolves_to_number(self):
        placement = context.load(self.VARIANT).placement
        for net, *_ in placement.HOT_LOOPS:
            self.assertIsInstance(post_route.routing_grid_for(placement.ROUTING_GRID, net), (int, float))


if __name__ == "__main__":
    unittest.main()
