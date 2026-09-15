"""收尾路由器的安全回归测试。用 KiCad Python 运行。"""
import unittest
import shutil
import tempfile
from pathlib import Path

import pcbnew

import post_route
import route


class PostRouteTest(unittest.TestCase):
    def test_freerouting_result_with_more_opens_is_rejected(self):
        baseline = {
            "violations": [{"severity": "warning"}] * 2,
            "unconnected_items": [{}, {}],
            "schematic_parity": [],
        }
        regressed = {
            "violations": [{"severity": "warning"}] * 2,
            "unconnected_items": [{}] * 17,
            "schematic_parity": [],
        }

        self.assertFalse(route.is_non_regressing(baseline, regressed))

    def test_freerouting_result_cannot_replace_warning_with_new_error(self):
        baseline = {
            "violations": [{"severity": "warning", "type": "track_dangling", "items": []}],
            "unconnected_items": [],
            "schematic_parity": [],
        }
        regressed = {
            "violations": [{"severity": "error", "type": "shorting_items", "items": []}],
            "unconnected_items": [],
            "schematic_parity": [],
        }

        self.assertFalse(route.is_non_regressing(baseline, regressed))

    def test_freerouting_result_cannot_substitute_parity_defect(self):
        baseline = {
            "violations": [], "unconnected_items": [],
            "schematic_parity": [{"type": "missing_net", "items": [{"uuid": "old"}]}],
        }
        regressed = {
            "violations": [], "unconnected_items": [],
            "schematic_parity": [{"type": "extra_net", "items": [{"uuid": "new"}]}],
        }

        self.assertFalse(route.is_non_regressing(baseline, regressed))

    def test_stale_freerouting_session_is_discarded(self):
        session = Path(tempfile.mkdtemp()) / "board.ses"
        session.write_text("stale")

        route.discard_stale_output(session)

        self.assertFalse(session.exists())

    def test_router_reuses_unchanged_obstacle_grid(self):
        board = pcbnew.LoadBoard(str(post_route.PCB))
        router = post_route.Router(board)
        first = router.blocked_grid("CAM_VSYNC", pcbnew.F_Cu)
        second = router.blocked_grid("CAM_VSYNC", pcbnew.F_Cu)
        self.assertIs(first, second)

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

    def test_reviewed_u1_warning_rejects_shifted_geometry(self):
        valid = [
            {"type": "silk_edge_clearance", "severity": "warning", "items": [
                {"description": "Segment on Edge.Cuts", "pos": {"x": 0.0, "y": 60.0}},
                {"description": "Segment of U1 on F.Silkscreen", "pos": {"x": -6.15, "y": y}},
            ]}
            for y in (20.8, 39.2)
        ]
        shifted = [dict(finding) for finding in valid]
        shifted[0] = {**valid[0], "items": [dict(item) for item in valid[0]["items"]]}
        shifted[0]["items"][1] = {
            **shifted[0]["items"][1], "pos": {"x": -6.15, "y": 21.0},
        }

        self.assertTrue(post_route.reviewed_u1_silk_warnings(valid))
        self.assertFalse(post_route.reviewed_u1_silk_warnings(shifted))

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

    def test_close_same_net_via_without_bottom_track_is_removable(self):
        board = pcbnew.BOARD()
        net = pcbnew.NETINFO_ITEM(board, "CAM_SIOC")
        board.Add(net)
        vias = []
        for x in (10.0, 10.1):
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(10.0)))
            via.SetNet(net)
            board.Add(via)
            vias.append(via)
        bottom = pcbnew.PCB_TRACK(board)
        bottom.SetStart(vias[0].GetPosition())
        bottom.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(11.0), pcbnew.FromMM(10.0)))
        bottom.SetLayer(pcbnew.B_Cu)
        bottom.SetNet(net)
        board.Add(bottom)
        finding = {"type": "hole_to_hole", "items": [
            {"uuid": vias[0].m_Uuid.AsString()}, {"uuid": vias[1].m_Uuid.AsString()},
        ]}
        self.assertEqual(post_route.redundant_same_net_via_uuid(finding, board),
                         vias[1].m_Uuid.AsString())


if __name__ == "__main__":
    unittest.main()
