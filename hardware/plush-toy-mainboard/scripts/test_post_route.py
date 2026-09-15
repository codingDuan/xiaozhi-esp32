"""收尾路由器的安全回归测试。用 KiCad Python 运行。"""
import unittest
import shutil
import tempfile
from pathlib import Path

import pcbnew

import post_route


class PostRouteTest(unittest.TestCase):
    def test_power_reroute_never_replaces_critical_copper(self):
        board = pcbnew.BOARD()
        net = pcbnew.NETINFO_ITEM(board, "BUCK_SW")
        board.Add(net)
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(10), pcbnew.FromMM(10)))
        track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(15), pcbnew.FromMM(10)))
        track.SetWidth(pcbnew.FromMM(0.2))
        track.SetLayer(pcbnew.F_Cu)
        track.SetNet(net)
        board.Add(track)

        changed = post_route.reroute_long_power_tracks(board, post_route.Router(board))

        self.assertEqual(changed, 0)
        self.assertIn(track, list(board.GetTracks()))

    def test_candidate_drc_uses_full_project_context_and_parity(self):
        candidate = Path(tempfile.mkdtemp()) / "arbitrary-candidate.kicad_pcb"
        shutil.copy2(post_route.PCB, candidate)
        report = post_route.drc(candidate)
        self.assertEqual(report["unconnected_items"], [])
        self.assertEqual(report["schematic_parity"], [])
        self.assertTrue(post_route.reviewed_u1_silk_warnings(report["violations"]))

    def test_pgnd_layer_change_uses_power_via_dimensions(self):
        board = pcbnew.LoadBoard(str(post_route.PCB))
        router = post_route.Router(board)
        added = router.add_path("PGND", [(80.0, 30.0, pcbnew.F_Cu),
                                          (80.0, 30.0, pcbnew.B_Cu)])
        self.assertEqual(len(added), 1)
        self.assertAlmostEqual(post_route.mm(added[0].GetWidth(pcbnew.F_Cu)), 0.8)
        self.assertAlmostEqual(post_route.mm(added[0].GetDrillValue()), 0.4)

    def test_only_known_redundant_servo_via_is_removable(self):
        known = {"type": "hole_to_hole", "items": [
            {"uuid": "pad", "description": "PTH pad 3 [PGND] of J_SERVO_L"},
            {"uuid": "via", "description": "Via [PGND] on F.Cu - B.Cu"},
        ]}
        unknown = {"type": "hole_to_hole", "items": [
            {"uuid": "pad", "description": "PTH pad 1 [GND] of J_USB"},
            {"uuid": "via2", "description": "Via [GND] on F.Cu - B.Cu"},
        ]}
        self.assertEqual(post_route.redundant_hole_via_uuid(known), "via")
        self.assertIsNone(post_route.redundant_hole_via_uuid(unknown))


if __name__ == "__main__":
    unittest.main()
