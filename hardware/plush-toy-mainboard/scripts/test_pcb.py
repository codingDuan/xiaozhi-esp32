"""PCB 外框、叠层、放置与网络核对。用 KiCad 自带 Python 运行：KICAD_PYTHON -m unittest test_pcb"""
import re
import heapq
import math
import unittest
from pathlib import Path

import pcbnew

import board_spec

PCB = Path(__file__).resolve().parents[1] / "plush-toy-mainboard.kicad_pcb"
MM = 1e6
W, H = 90.0, 60.0          # 设计方案 11 节：原 70×50 放不下，委托方确认改为 90×60 单面贴片


def mm(v: int) -> float:
    return v / MM


class PcbTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PCB.exists():
            raise AssertionError(f"{PCB} 不存在，先运行 gen_pcb.py")
        cls.board = pcbnew.LoadBoard(str(PCB))
        cls.fps = {fp.GetReference(): fp for fp in cls.board.GetFootprints()}

    def test_outline_is_90_by_60(self):
        box = self.board.GetBoardEdgesBoundingBox()
        self.assertAlmostEqual(mm(box.GetWidth()), W, delta=0.2)
        self.assertAlmostEqual(mm(box.GetHeight()), H, delta=0.2)

    def test_four_copper_layers(self):
        self.assertEqual(self.board.GetCopperLayerCount(), 4)

    def _pad_distance(self, ref_a, pad_a, ref_b, pad_b):
        a = self.fps[ref_a].FindPadByNumber(pad_a).GetPosition()
        b = self.fps[ref_b].FindPadByNumber(pad_b).GetPosition()
        return ((mm(a.x - b.x) ** 2) + (mm(a.y - b.y) ** 2)) ** 0.5

    def _footprint_distance(self, ref_a, ref_b):
        a = self.fps[ref_a].GetPosition()
        b = self.fps[ref_b].GetPosition()
        return ((mm(a.x - b.x) ** 2) + (mm(a.y - b.y) ** 2)) ** 0.5

    def _tracks(self, net):
        return [item for item in self.board.GetTracks()
                if item.GetClass() == "PCB_TRACK" and item.GetNetname() == net]

    def _vias(self, net):
        return [item for item in self.board.GetTracks()
                if item.GetClass() == "PCB_VIA" and item.GetNetname() == net]

    def _shortest_top_path(self, net, start, end):
        graph = {}
        for track in self._tracks(net):
            if track.GetLayer() != pcbnew.F_Cu:
                continue
            a = (track.GetStart().x, track.GetStart().y)
            b = (track.GetEnd().x, track.GetEnd().y)
            length = mm(track.GetLength())
            graph.setdefault(a, []).append((b, length))
            graph.setdefault(b, []).append((a, length))
        source = (start.x, start.y)
        target = (end.x, end.y)
        queue = [(0.0, source)]
        seen = {}
        while queue:
            distance, node = heapq.heappop(queue)
            if node == target:
                return distance
            if distance >= seen.get(node, math.inf):
                continue
            seen[node] = distance
            for neighbor, length in graph.get(node, []):
                heapq.heappush(queue, (distance + length, neighbor))
        return math.inf

    def test_revised_parts_are_placed(self):
        required = {"U_EFUSE", "C_EFUSE_IN", "C_EFUSE_DVDT", "R_EFUSE_ILM", "C_BUCK_HF",
                    "J_TOUCH", "R_SIOC", "R_SIOD", "Q_LCD_BL", "R_LCD_BL_GATE",
                    "R_LCD_BL_OFF"}
        self.assertEqual(required - self.fps.keys(), set())

    def test_eye_connectors_have_routed_backlight_pin(self):
        for ref in ("J_LCD_L", "J_LCD_R"):
            with self.subTest(ref=ref):
                pads = {pad.GetNumber(): pad.GetNetname() for pad in self.fps[ref].Pads()}
                self.assertEqual(pads.get("8"), "LCD_BL")
                pin = self.fps[ref].FindPadByNumber("8").GetPosition()
                self.assertTrue(any(track.GetStart() == pin or track.GetEnd() == pin
                                    for track in self._tracks("LCD_BL")))
        self.assertTrue(self._tracks("LCD_BL"))
        self.assertTrue(all(mm(track.GetWidth()) >= 0.5 for track in self._tracks("LCD_BL")))

    def test_usb_shield_uses_solid_plane_connection(self):
        shields = [pad for pad in self.fps["J_USB"].Pads() if pad.GetNumber() == "SH"]
        self.assertTrue(shields)
        self.assertTrue(all(pad.GetLocalZoneConnection() == pcbnew.ZONE_CONNECTION_FULL
                            for pad in shields))

    def test_buck_and_esp32_local_parts_are_close(self):
        self.assertLessEqual(self._pad_distance("U_BUCK", "4", "C_BUCK_HF", "1"), 2.5)
        self.assertLessEqual(self._pad_distance("U_BUCK", "2", "C_BUCK_HF", "2"), 2.5)
        self.assertLessEqual(self._footprint_distance("U_BUCK", "C_BUCK_IN"), 3.0)
        for ref in ("C_U1", "C_U1_BULK"):
            with self.subTest(ref=ref):
                self.assertLessEqual(self._pad_distance("U1", "2", ref, "1"), 4.0)
        for ref, pad in (("R_EN", "2"), ("C_EN", "1")):
            with self.subTest(ref=ref):
                self.assertLessEqual(self._pad_distance("U1", "3", ref, pad), 5.0)

    def test_stackup_matches_jlc04161h_7628(self):
        text = PCB.read_text(encoding="utf-8")
        layers = re.findall(r'\(layer "(F\.Cu|In1\.Cu|In2\.Cu|B\.Cu|dielectric [123])"\s+'
                            r'\(type "?([^"()]+)"?\)\s+\(thickness ([0-9.]+)\)', text)
        self.assertEqual(layers, [
            ("F.Cu", "copper", "0.035"),
            ("dielectric 1", "prepreg", "0.2104"),
            ("In1.Cu", "copper", "0.0152"),
            ("dielectric 2", "core", "1.065"),
            ("In2.Cu", "copper", "0.0152"),
            ("dielectric 3", "prepreg", "0.2104"),
            ("B.Cu", "copper", "0.035"),
        ])

    def test_buck_sw_is_short_top_only_and_vialess(self):
        tracks = self._tracks("BUCK_SW")
        self.assertTrue(tracks)
        self.assertEqual(self._vias("BUCK_SW"), [])
        self.assertEqual({track.GetLayer() for track in tracks}, {pcbnew.F_Cu})
        self.assertLessEqual(sum(mm(track.GetLength()) for track in tracks), 3.0)

    def test_critical_ground_pads_have_via_within_one_mm(self):
        vias = [via.GetPosition() for via in self._vias("GND")]
        self.assertTrue(vias)
        for ref, number in (("U_BUCK", "2"), ("C_BUCK_HF", "2"), ("C_BUCK_IN", "2"),
                            ("C_U1", "2"), ("C_U1_BULK", "2")):
            pad = self.fps[ref].FindPadByNumber(number).GetPosition()
            nearest = min(math.hypot(mm(pad.x - via.x), mm(pad.y - via.y)) for via in vias)
            with self.subTest(ref=ref, pad=number):
                self.assertLessEqual(nearest, 1.0)

    def test_sensitive_ground_islands_have_deterministic_vias(self):
        vias = {(via.GetPosition().x, via.GetPosition().y) for via in self._vias("GND")}
        for ref, number in (("C_EN", "2"), ("U_AMP", "17")):
            pad = self.fps[ref].FindPadByNumber(number).GetPosition()
            attached = [track for track in self._tracks("GND")
                        if track.GetStart() == pad or track.GetEnd() == pad]
            with self.subTest(ref=ref, pad=number):
                self.assertTrue((pad.x, pad.y) in vias or
                                any((track.GetStart().x, track.GetStart().y) in vias or
                                    (track.GetEnd().x, track.GetEnd().y) in vias
                                    for track in attached))

    def test_u1_en_rc_has_short_top_layer_paths(self):
        source = self.fps["U1"].FindPadByNumber("3").GetPosition()
        for ref, number in (("R_EN", "2"), ("C_EN", "1")):
            target = self.fps[ref].FindPadByNumber(number).GetPosition()
            with self.subTest(ref=ref):
                self.assertLessEqual(self._shortest_top_path("EN", source, target), 10.0)
        # 远端复位按键允许换层；本约束只要求 U1 到就近 RC 不经过该长支路。

    def test_touch_e8_has_locked_top_layer_path(self):
        source = self.fps["U_TOUCH"].FindPadByNumber("16").GetPosition()
        target = self.fps["TP_E8"].FindPadByNumber("1").GetPosition()
        # 两焊盘直线距离已是 12.28mm；给正交逃逸和净距拐点保留约 1.7mm。
        self.assertLessEqual(self._shortest_top_path("TOUCH_E8", source, target), 14.0)

    def test_touch_top_signals_have_locked_paths_or_escapes(self):
        for number, net, target in (("17", "TOUCH_E9", "TP_E9"),
                                    ("19", "TOUCH_E11", "TP_E11")):
            source = self.fps["U_TOUCH"].FindPadByNumber(number).GetPosition()
            end = self.fps[target].FindPadByNumber("1").GetPosition()
            with self.subTest(net=net):
                self.assertLessEqual(self._shortest_top_path(net, source, end), 13.0)

        sda = self.fps["U_TOUCH"].FindPadByNumber("3")
        pos = sda.GetPosition()
        self.assertTrue(any(track.GetStart() == pos or track.GetEnd() == pos
                            for track in self._tracks("I2C_SDA")))

        pwm = self.fps["U_PWM"].FindPadByNumber("28")
        pos = pwm.GetPosition()
        self.assertTrue(any(track.GetStart() == pos or track.GetEnd() == pos
                            for track in self._tracks("+3V3")))
        self.assertTrue(any(mm(via.GetPosition().x) < 62.0 for via in self._vias("+3V3")))

        vreg = self.fps["U_TOUCH"].FindPadByNumber("5").GetPosition()
        cap = self.fps["C_TOUCH_VREG"].FindPadByNumber("1").GetPosition()
        vreg_tracks = self._tracks("TOUCH_VREG")
        self.assertTrue(any(track.GetStart() == vreg or track.GetEnd() == vreg
                            for track in vreg_tracks))
        self.assertTrue(any(track.GetStart() == cap or track.GetEnd() == cap
                            for track in vreg_tracks))
        self.assertGreaterEqual(len(self._vias("TOUCH_VREG")), 2)

    def test_efuse_output_has_outward_escape(self):
        pad = self.fps["U_EFUSE"].FindPadByNumber("5")
        pos = pad.GetPosition()
        attached = [track for track in self._tracks("VBUS")
                    if track.GetStart() == pos or track.GetEnd() == pos]
        self.assertTrue(any(max(mm(track.GetStart().x), mm(track.GetEnd().x)) >= mm(pos.x) + 0.7
                            for track in attached))

    def test_efuse_current_limit_exits_away_from_vbus(self):
        ilm = self.fps["U_EFUSE"].FindPadByNumber("7").GetPosition()
        resistor = self.fps["R_EFUSE_ILM"].FindPadByNumber("1").GetPosition()
        vbus = self.fps["U_EFUSE"].FindPadByNumber("5").GetPosition()
        self.assertGreater(mm(resistor.x), mm(ilm.x) + 1.0)
        self.assertAlmostEqual(mm(resistor.y), mm(ilm.y), delta=0.1)
        self.assertLessEqual(self._shortest_top_path("EFUSE_ILM", ilm, resistor), 2.0)
        self.assertGreaterEqual(abs(mm(vbus.y - resistor.y)), 0.9)

    @staticmethod
    def _parallel_guard_coverage(signal, guard):
        sx = mm(signal.GetEnd().x - signal.GetStart().x)
        sy = mm(signal.GetEnd().y - signal.GetStart().y)
        gx = mm(guard.GetEnd().x - guard.GetStart().x)
        gy = mm(guard.GetEnd().y - guard.GetStart().y)
        slen = math.hypot(sx, sy)
        glen = math.hypot(gx, gy)
        if slen == 0 or glen == 0 or abs(sx * gy - sy * gx) > 1e-3 * slen * glen:
            return None
        ux, uy = sx / slen, sy / slen
        ax = mm(guard.GetStart().x - signal.GetStart().x)
        ay = mm(guard.GetStart().y - signal.GetStart().y)
        bx = mm(guard.GetEnd().x - signal.GetStart().x)
        by = mm(guard.GetEnd().y - signal.GetStart().y)
        side = ux * ay - uy * ax
        distance = abs(side)
        lo, hi = sorted((ux * ax + uy * ay, ux * bx + uy * by))
        overlap = max(0.0, min(slen, hi) - max(0.0, lo))
        return side, distance, overlap

    def test_camera_xclk_is_top_only_vialess_and_guarded(self):
        xclk = self._tracks("CAM_XCLK")
        self.assertTrue(xclk)
        self.assertEqual(self._vias("CAM_XCLK"), [])
        self.assertEqual({track.GetLayer() for track in xclk}, {pcbnew.F_Cu})
        guards = self._tracks("GND")
        for signal in (track for track in xclk if mm(track.GetLength()) > 3.0):
            matches = [self._parallel_guard_coverage(signal, guard) for guard in guards]
            matches = [match for match in matches if match is not None and 0.5 <= match[1] <= 0.8]
            required = max(1.0, mm(signal.GetLength()) - 2.5)
            with self.subTest(start=signal.GetStart(), end=signal.GetEnd()):
                self.assertTrue(any(side > 0 and overlap >= required for side, _, overlap in matches))
                self.assertTrue(any(side < 0 and overlap >= required for side, _, overlap in matches))

    def test_xclk_guard_vias_are_stitched_at_three_mm_pitch(self):
        vias = [(mm(via.GetPosition().x), mm(via.GetPosition().y)) for via in self._vias("GND")]
        guards = self._tracks("GND")
        for signal in (track for track in self._tracks("CAM_XCLK") if mm(track.GetLength()) > 3.0):
            matches = [guard for guard in guards
                       if (coverage := self._parallel_guard_coverage(signal, guard)) is not None
                       and 0.5 <= coverage[1] <= 0.8 and coverage[2] >= mm(signal.GetLength()) - 2.5]
            for guard in matches:
                length = mm(guard.GetLength())
                count = max(1, math.ceil(length / 3.0))
                for index in range(count + 1):
                    ratio = index / count
                    x = mm(guard.GetStart().x) + ratio * mm(guard.GetEnd().x - guard.GetStart().x)
                    y = mm(guard.GetStart().y) + ratio * mm(guard.GetEnd().y - guard.GetStart().y)
                    with self.subTest(x=round(x, 3), y=round(y, 3)):
                        self.assertTrue(any(math.hypot(x - vx, y - vy) <= 0.15 for vx, vy in vias))

    def test_xclk_has_no_long_close_parallel_signal(self):
        offenders = []
        for signal in self._tracks("CAM_XCLK"):
            for other in self.board.GetTracks():
                if other.GetClass() != "PCB_TRACK" or other.GetNetname() in ("CAM_XCLK", "GND"):
                    continue
                match = self._parallel_guard_coverage(signal, other)
                if match is not None and match[1] < 0.7 and match[2] > 3.0:
                    offenders.append((other.GetNetname(), round(match[1], 3), round(match[2], 3)))
        self.assertEqual(offenders, [])

    def test_every_fitted_part_placed_inside_outline(self):
        box = self.board.GetBoardEdgesBoundingBox()
        for part in board_spec.PARTS:
            if not part.fitted:
                continue
            with self.subTest(ref=part.ref):
                self.assertIn(part.ref, self.fps)
                court = self.fps[part.ref].GetCourtyard(pcbnew.F_CrtYd if not self.fps[part.ref].IsFlipped()
                                                         else pcbnew.B_CrtYd).BBox()
                # 天线允许伸出板边（设计方案 6.2 节），其余器件的焊盘必须在板内
                pads = self.fps[part.ref].GetBoundingBox(False)
                if part.ref != "U1":
                    self.assertTrue(box.Contains(pads.GetOrigin()) and box.Contains(pads.GetEnd()),
                                    f"{part.ref} 超出板框")
                self.assertGreater(court.GetWidth(), 0)

    def test_pad_nets_match_spec(self):
        for part in board_spec.PARTS:
            if not part.fitted:
                continue
            for pad in self.fps[part.ref].Pads():
                expected = part.pins.get(pad.GetNumber())
                if expected and not expected.startswith("NC_"):
                    with self.subTest(ref=part.ref, pad=pad.GetNumber()):
                        self.assertEqual(pad.GetNetname(), expected)

    def test_no_courtyard_overlap_on_same_side(self):
        # 用真实多边形求交，不用包围盒：U1 的庭院层是 L 形（本体 + 天线净空区），
        # 包围盒会把净空区两侧大片空白也算进去，误报它周围所有器件重叠
        items = []
        for ref, fp in self.fps.items():
            layer = pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd
            poly = fp.GetCourtyard(layer)
            if poly.OutlineCount():
                items.append((ref, fp.IsFlipped(), poly))
        overlaps = []
        for i, (ra, fa, pa) in enumerate(items):
            for rb, fb, pb in items[i + 1:]:
                if fa != fb or not pa.BBox().Intersects(pb.BBox()):
                    continue
                common = pcbnew.SHAPE_POLY_SET(pa)
                common.BooleanIntersection(pb)
                if common.OutlineCount() and common.Area() > 0:
                    overlaps.append((ra, rb))
        self.assertEqual(overlaps, [])

    def test_antenna_at_left_edge_and_power_at_right_edge(self):
        # 天线在 x=0 一端，功率区在另一端（设计方案第 7 节）
        u1 = mm(self.fps["U1"].GetPosition().x)
        self.assertLess(u1, 20.0)
        for ref in ("Q_HEAT", "J_HEAT", "J_VMOT", "C_VMOT_BULK"):
            with self.subTest(ref=ref):
                self.assertGreater(mm(self.fps[ref].GetPosition().x), W * 0.6)

    def test_hc6_heater_silkscreen_readable(self):
        # 硬约束 HC-6：加热插座旁必须印「串 KSD9700」。KiCad 内置笔画字体没有 ℃ 字形，
        # 印出来是方框（2026-09-14 渲染图实测），所以温度单位只能写成「度」
        texts = [t.GetText() for t in self.board.GetDrawings()
                 if isinstance(t, pcbnew.PCB_TEXT) and t.GetLayer() == pcbnew.F_SilkS]
        heater = [t for t in texts if "KSD9700" in t]
        self.assertEqual(len(heater), 1, f"F.SilkS 上应有且仅有一条 KSD9700 丝印，实际：{texts}")
        self.assertNotIn("℃", heater[0])
        self.assertIn("65", heater[0])
        self.assertIn("常闭", heater[0])

    def test_required_safety_silkscreen_is_present(self):
        texts = {t.GetText() for t in self.board.GetDrawings()
                 if isinstance(t, pcbnew.PCB_TEXT) and t.GetLayer() == pcbnew.F_SilkS}
        required = {"电机/加热专用", "+", "-", "CH0 左", "CH1 右",
                    "必须串 KSD9700 65度 常闭", "VMOT 仅限 5V", "头部触摸\nE0 / GND"}
        self.assertEqual(required - texts, set())

    def _board_text(self, text):
        matches = [t for t in self.board.GetDrawings()
                   if isinstance(t, pcbnew.PCB_TEXT) and t.GetLayer() == pcbnew.F_SilkS
                   and t.GetText() == text]
        self.assertEqual(len(matches), 1, text)
        return matches[0]

    @staticmethod
    def _box_gap(a, b):
        dx = max(mm(b.GetX() - a.GetRight()), mm(a.GetX() - b.GetRight()), 0.0)
        dy = max(mm(b.GetY() - a.GetBottom()), mm(a.GetY() - b.GetBottom()), 0.0)
        return math.hypot(dx, dy)

    def test_power_input_labels_sit_at_vmot_terminal(self):
        # 2026-09-14 评审：两行 5V 标签排在圆屏排针末端，容易被读成屏幕座是 5V/电机电源。
        # 标签必须贴着 J_VMOT，并远离两排 3.3V 屏幕排针。屏排针加到 8 针后 8 脚右移
        # 2.54mm，第二行去掉重复的「5V」才放得下这 7mm 间距。
        terminal = self.fps["J_VMOT"].GetCourtyard(pcbnew.F_CrtYd).BBox()
        lcd_pads = [pad.GetBoundingBox() for ref in ("J_LCD_L", "J_LCD_R")
                    for pad in self.fps[ref].Pads()]
        for text in ("电机/加热专用", "VMOT 仅限 5V"):
            box = self._board_text(text).GetBoundingBox()
            with self.subTest(text=text):
                self.assertLessEqual(self._box_gap(box, terminal), 4.0)
                self.assertGreaterEqual(min(self._box_gap(box, pad) for pad in lcd_pads), 7.0)

    def test_touch_label_sits_beside_touch_connector(self):
        # 标签在 J_TOUCH 左侧、与 1 脚同高，读序 E0 / GND 与针序一致。
        box = self._board_text("头部触摸\nE0 / GND").GetBoundingBox()
        connector = self.fps["J_TOUCH"].GetCourtyard(pcbnew.F_CrtYd).BBox()
        pin1 = self.fps["J_TOUCH"].FindPadByNumber("1").GetPosition()
        self.assertLessEqual(self._box_gap(box, connector), 2.0)
        self.assertLess(box.GetRight(), pin1.x)
        self.assertTrue(box.GetY() <= pin1.y <= box.GetBottom())

    def test_buck_input_bulk_capacitor_faces_ic(self):
        # C_BUCK_IN 的 VBUS 焊盘朝 U_BUCK.4、GND 焊盘朝 U_BUCK.2；反向时 VIN 预布线要绕 10.9mm。
        self.assertLess(self._pad_distance("U_BUCK", "4", "C_BUCK_IN", "1"),
                        self._pad_distance("U_BUCK", "4", "C_BUCK_IN", "2"))
        self.assertLess(self._pad_distance("U_BUCK", "2", "C_BUCK_IN", "2"),
                        self._pad_distance("U_BUCK", "2", "C_BUCK_IN", "1"))
        vin = self.fps["U_BUCK"].FindPadByNumber("4").GetPosition()
        bulk = self.fps["C_BUCK_IN"].FindPadByNumber("1").GetPosition()
        self.assertLessEqual(self._shortest_top_path("VBUS", vin, bulk), 7.0)

    def test_high_current_nets_have_no_long_necks(self):
        # 逐段 2mm 的豁免会放过「几段短窄线首尾相接」和「宽焊盘出口的窄线」。
        # 大电流主干上相连的窄线合并成一条链：只允许在比线宽还窄的焊盘出口处，总长 ≤ 2mm。
        # 只接电阻或测试点的偏置/测试支路电流为 µA 级，不受此约束。
        required = {"VBUS_IN": 0.5, "VBUS_FUSED": 0.5, "VBUS": 0.5,
                    "VMOT_IN": 1.0, "VMOT": 1.0, "PGND": 1.0, "HEAT_LOW": 1.0}
        narrow = [t for t in self.board.GetTracks()
                  if t.GetClass() == "PCB_TRACK" and t.GetNetname() in required
                  and mm(t.GetWidth()) < required[t.GetNetname()] - 1e-6]
        parent = {}

        def root(node):
            while parent.setdefault(node, node) != node:
                node = parent[node]
            return node

        def node(track, point):
            return track.GetNetname(), track.GetLayer(), point.x, point.y

        for track in narrow:
            parent[root(node(track, track.GetStart()))] = root(node(track, track.GetEnd()))
        chains = {}
        for track in narrow:
            chains.setdefault(root(node(track, track.GetStart())), []).append(track)
        pads = [(ref, pad) for ref, fp in self.fps.items() for pad in fp.Pads()]
        offenders = []
        for tracks in chains.values():
            net = tracks[0].GetNetname()
            points = [p for t in tracks for p in (t.GetStart(), t.GetEnd())]
            touched = {(ref, pad.GetNumber()): min(mm(pad.GetSizeX()), mm(pad.GetSizeY()))
                       for ref, pad in pads if pad.GetNetname() == net
                       and any(pad.HitTest(p) for p in points)}
            if touched and all(ref.startswith(("R_", "TP_")) for ref, _ in touched):
                continue
            length = sum(mm(t.GetLength()) for t in tracks)
            forced = any(size < required[net] for size in touched.values())
            if not forced or length > 2.0 + 1e-6:
                start = points[0]
                offenders.append((net, round(length, 2), sorted(touched),
                                  (round(mm(start.x), 2), round(mm(start.y), 2))))
        self.assertEqual(offenders, [])

    def test_pads_of_different_parts_do_not_touch(self):
        # 庭院层不重叠不等于焊盘不重叠：第三方封装的庭院层可能比焊盘小。
        # 2026-09-14 首版 C_VMOT_HF 的 PGND 焊盘压在 C_VMOT_BULK 的 VMOT 焊盘上
        pads = [(ref, p.GetNumber(), p.GetNetname(), p.GetBoundingBox())
                for ref, fp in self.fps.items() for p in fp.Pads() if p.IsOnLayer(pcbnew.F_Cu)]
        touching = []
        for i, (ra, na, neta, ba) in enumerate(pads):
            for rb, nb, netb, bb in pads[i + 1:]:
                if ra != rb and ba.Intersects(bb):
                    touching.append((f"{ra}.{na}[{neta}]", f"{rb}.{nb}[{netb}]"))
        self.assertEqual(touching, [])

    def _visible_silk_texts(self):
        """(说明, 包围盒) 列表：F.SilkS 上所有可见文字，含位号、取值与板上独立文字。"""
        items = []
        for ref, fp in self.fps.items():
            for field in (fp.Reference(), fp.Value()):
                if field.IsVisible() and field.GetLayer() == pcbnew.F_SilkS:
                    items.append((f"{ref}:{field.GetText()}", field.GetBoundingBox()))
        for drawing in self.board.GetDrawings():
            if isinstance(drawing, pcbnew.PCB_TEXT) and drawing.GetLayer() == pcbnew.F_SilkS:
                items.append((f"board:{drawing.GetText()}", drawing.GetBoundingBox()))
        return items

    def test_silkscreen_texts_do_not_overlap(self):
        # 委托方 2026-09-14 反馈丝印太乱：可见文字之间不得互相压住
        items = self._visible_silk_texts()
        clashes = [(a, b) for i, (a, ba) in enumerate(items) for b, bb in items[i + 1:] if ba.Intersects(bb)]
        self.assertEqual(clashes, [])

    def test_silkscreen_texts_clear_of_pads(self):
        # 丝印压在焊盘上会被阻焊开窗切掉，而且挡住目检。
        # 嘉立创建议丝印距焊盘 ≥ 0.25mm（字符设计规范），焊盘框外扩 0.25mm 再判断
        pads = []
        for ref, fp in self.fps.items():
            for p in fp.Pads():
                if p.IsOnLayer(pcbnew.F_Cu):
                    box = p.GetBoundingBox()
                    box.Inflate(pcbnew.FromMM(0.25))
                    pads.append((f"{ref}.{p.GetNumber()}", box))
        clashes = [(t, p) for t, bt in self._visible_silk_texts() for p, bp in pads if bt.Intersects(bp)]
        self.assertEqual(clashes, [])

    def test_silkscreen_text_size_meets_jlcpcb(self):
        # 嘉立创：字高绝对下限 0.8mm、建议 ≥ 1.0mm；线宽下限 0.15mm。
        # 本板统一取 1.0mm / 0.15mm。2026-09-14 首版位号用 0.12mm 线宽，低于下限
        undersized = []
        for ref, fp in self.fps.items():
            field = fp.Reference()
            if field.IsVisible() and field.GetLayer() == pcbnew.F_SilkS:
                h, w = field.GetTextHeight() / MM, field.GetTextThickness() / MM
                if h < 1.0 - 1e-6 or w < 0.15 - 1e-6:
                    undersized.append((ref, round(h, 3), round(w, 3)))
        for drawing in self.board.GetDrawings():
            if isinstance(drawing, pcbnew.PCB_TEXT) and drawing.GetLayer() == pcbnew.F_SilkS:
                h, w = drawing.GetTextHeight() / MM, drawing.GetTextThickness() / MM
                if h < 1.0 - 1e-6 or w < 0.15 - 1e-6:
                    undersized.append((drawing.GetText(), round(h, 3), round(w, 3)))
        self.assertEqual(undersized, [])

    def test_connectors_and_ics_keep_visible_reference(self):
        # 阻容可以不印位号，但接插件和芯片必须印：接线时要分得清左右舵机、加热、电源座，
        # 返修时要找得到芯片。2026-09-14 首版整理曾因找不到空位把 J_SERVO_L/R 隐藏掉
        hidden = sorted(ref for ref, fp in self.fps.items()
                        if ref.startswith(("J_", "U")) and not fp.Reference().IsVisible())
        self.assertEqual(hidden, [])

    def test_inner_planes_carry_no_tracks(self):
        # 设计方案 6.1 节：L2 整层 GND、L3 电源平面，禁止走线。DRC 不会报这个——线走在平面层上
        # 电气上合法，但会切断高速信号的回流参考。2026-09-14 首次自动布线把 MIC、I2S 线走在了内层
        tracks = sorted({t.GetNetname() for t in self.board.GetTracks()
                         if t.GetClass() == "PCB_TRACK" and t.GetLayer() in (pcbnew.In1_Cu, pcbnew.In2_Cu)})
        self.assertEqual(tracks, [])

    def test_inner_layers_typed_as_power_planes(self):
        # 布线器依据层类型判断能否走线：只有 power 类型的内层才会被当作平面
        for layer in (pcbnew.In1_Cu, pcbnew.In2_Cu):
            with self.subTest(layer=pcbnew.LayerName(layer)):
                self.assertEqual(self.board.GetLayerType(layer), pcbnew.LT_POWER)

    def test_plane_nets_fanned_out_to_vias(self):
        # 顶层 GND / +3V3 贴片焊盘必须就近有同网络过孔下平面（+3V3 平面只覆盖 x < 62）。
        # 2026-09-14 第二次布线后这两个网络仍有 41 条未连接：Freerouting 不会主动打过孔接平面
        # 同网络过孔或通孔焊盘都算：U1.41 用模组封装自带的散热过孔下平面；
        # 细间距引脚的过孔要打到引脚排外侧，或经走线连到散热焊盘的焊盘内过孔，放宽到 3.5mm
        vias = [(t.GetNetname(), t.GetPosition().x / MM, t.GetPosition().y / MM)
                for t in self.board.GetTracks() if t.GetClass() == "PCB_VIA"]
        vias += [(p.GetNetname(), p.GetPosition().x / MM, p.GetPosition().y / MM)
                 for fp in self.fps.values() for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
        lonely = []
        for ref, fp in self.fps.items():
            for pad in fp.Pads():
                net = pad.GetNetname()
                if pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD or net not in ("GND", "+3V3"):
                    continue
                px, py = pad.GetPosition().x / MM, pad.GetPosition().y / MM
                if net == "+3V3" and px > 61.5:
                    continue
                if not any(n == net and ((vx - px) ** 2 + (vy - py) ** 2) ** 0.5 <= 3.5 for n, vx, vy in vias):
                    lonely.append(f"{ref}.{pad.GetNumber()}[{net}]")
        self.assertEqual(lonely, [])

    def test_camera_fpc_has_bottom_fanout_corridor(self):
        # 0.5mm FPC 的密集焊盘需要在排线插入侧留出走线/过孔空间；原布局仅余 1.27mm，
        # +1V5 等引脚被板边和内侧相机线共同封死。要求信号焊盘到板边至少 3.5mm。
        signal_pads = [pad for pad in self.fps["J_CAM"].Pads() if pad.GetNumber().isdigit()
                       and int(pad.GetNumber()) <= 24]
        bottommost = max(mm(pad.GetBoundingBox().GetBottom()) for pad in signal_pads)
        self.assertGreaterEqual(H - bottommost, 3.5)

    def test_camera_y5_escape_is_locked_for_autorouter(self):
        pad = self.fps["J_CAM"].FindPadByNumber("20")
        pos = pad.GetPosition()
        tracks = [track for track in self._tracks("CAM_Y5")
                  if track.GetStart() == pos or track.GetEnd() == pos]
        self.assertTrue(tracks)
        self.assertTrue(all(track.IsLocked() for track in tracks))
        other_ends = [track.GetEnd() if track.GetStart() == pos else track.GetStart() for track in tracks]
        vias = self._vias("CAM_Y5")
        self.assertTrue(any(via.IsLocked() and via.GetPosition() in other_ends for via in vias))

    def test_camera_fpc_bottom_fanout_corridor_is_unobstructed(self):
        pads = [pad for pad in self.fps["J_CAM"].Pads() if pad.GetNumber().isdigit()
                and int(pad.GetNumber()) <= 24]
        x1 = min(mm(pad.GetBoundingBox().GetX()) for pad in pads) - 0.2
        x2 = max(mm(pad.GetBoundingBox().GetRight()) for pad in pads) + 0.2
        y1 = max(mm(pad.GetBoundingBox().GetBottom()) for pad in pads)
        offenders = []
        for ref, fp in self.fps.items():
            if ref == "J_CAM":
                continue
            box = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
            bx1, by1 = mm(box.GetX()), mm(box.GetY())
            bx2, by2 = mm(box.GetRight()), mm(box.GetBottom())
            if bx2 > x1 and bx1 < x2 and by2 > y1 and by1 < H - 0.5:
                offenders.append(ref)
        self.assertEqual(sorted(offenders), [])

    def test_imu_plane_pads_escape_away_from_center_keepout(self):
        tracks = list(self.board.GetTracks())
        missing = []
        for number in ("8", "9", "11"):
            pad = self.fps["U_IMU"].FindPadByNumber(number)
            center = pad.GetPosition()
            if not any(track.GetClass() == "PCB_TRACK" and track.GetNetname() == pad.GetNetname() and
                       (track.GetStart() == center or track.GetEnd() == center) and
                       max(mm(track.GetStart().y), mm(track.GetEnd().y)) >
                       mm(pad.GetBoundingBox().GetBottom()) + 0.2 for track in tracks):
                missing.append(f"U_IMU.{number}[{pad.GetNetname()}]")
        self.assertEqual(missing, [])

    def test_touch_ground_pad_has_outward_via(self):
        pad = self.fps["U_TOUCH"].FindPadByNumber("4")
        pos = pad.GetPosition()
        distances = [self._shortest_top_path("GND", pos, via.GetPosition())
                     for via in self._vias("GND")]
        # 密脚距区域允许用数段短折线避开 SDA/VREG；仍须在 3mm 内下到地平面。
        self.assertLessEqual(min(distances, default=math.inf), 3.0)

    def test_amp_speaker_pad_has_outward_escape(self):
        fp = self.fps["U_AMP"]
        pad = fp.FindPadByNumber("10")
        center = pad.GetPosition()
        right = mm(pad.GetBoundingBox().GetRight())
        escaped = any(track.GetClass() == "PCB_TRACK" and track.GetNetname() == "SPK_N" and
                      (track.GetStart() == center or track.GetEnd() == center) and
                      max(mm(track.GetStart().x), mm(track.GetEnd().x)) >= right + 0.8
                      for track in self.board.GetTracks())
        self.assertTrue(escaped)

    def test_camera_dvdd_has_deterministic_bottom_layer_escape(self):
        vias = [item for item in self.board.GetTracks()
                if item.GetClass() == "PCB_VIA" and item.GetNetname() == "+1V5"]
        bottom_tracks = [item for item in self.board.GetTracks()
                         if item.GetClass() == "PCB_TRACK" and item.GetNetname() == "+1V5" and
                         item.GetLayer() == pcbnew.B_Cu]
        self.assertGreaterEqual(len(vias), 2)
        self.assertTrue(bottom_tracks)

    def test_servo_left_pgnd_pad_has_bottom_layer_anchor(self):
        pad = self.fps["J_SERVO_L"].FindPadByNumber("3")
        pos = pad.GetPosition()
        anchored = any(item.GetClass() == "PCB_TRACK" and item.GetNetname() == "PGND" and
                       item.GetLayer() == pcbnew.B_Cu and
                       (item.GetStart() == pos or item.GetEnd() == pos) for item in self.board.GetTracks())
        self.assertTrue(anchored)

    def test_power_tracks_only_use_short_neckdowns_below_netclass_width(self):
        # 细间距焊盘附近允许最多 2mm 的窄颈；长距离供电/扬声器走线必须达到网络类线宽。
        required = {
            "VMOT": 1.0, "VMOT_IN": 1.0, "PGND": 1.0, "HEAT_LOW": 1.0,
            "VBUS": 0.5, "VBUS_IN": 0.5, "VBUS_FUSED": 0.5,
            "+3V3": 0.5, "GND": 0.5,
            "BUCK_SW": 0.5, "SPK_P": 0.5, "SPK_N": 0.5, "LCD_BL": 0.5,
            "+2V8": 0.5, "+1V5": 0.3,
        }
        vias = {(item.GetNetname(), item.GetPosition().x, item.GetPosition().y)
                for item in self.board.GetTracks() if item.GetClass() == "PCB_VIA"}
        offenders = []
        for item in self.board.GetTracks():
            if item.GetClass() != "PCB_TRACK" or item.GetNetname() not in required:
                continue
            width, length = mm(item.GetWidth()), mm(item.GetLength())
            # 平面地的细间距焊盘允许用短线直接扇出到过孔；电流随后由整层 GND 承担。
            endpoints = ((item.GetNetname(), item.GetStart().x, item.GetStart().y),
                         (item.GetNetname(), item.GetEnd().x, item.GetEnd().y))
            if item.GetNetname() == "GND" and length <= 3.0 and any(p in vias for p in endpoints):
                continue
            if width < required[item.GetNetname()] - 1e-6 and length > 2.0 + 1e-6:
                offenders.append((item.GetNetname(), round(width, 4), round(length, 3)))
        self.assertEqual(offenders, [])

    def test_single_sided_assembly(self):
        flipped = sorted(ref for ref, fp in self.fps.items() if fp.IsFlipped())
        self.assertEqual(flipped, [])
        parts = {part.ref: part for part in board_spec.PARTS if part.fitted}
        mismatches = sorted(ref for ref, fp in self.fps.items()
                            if fp.IsExcludedFromBOM() == parts[ref].assembly or
                            fp.IsExcludedFromPosFiles() == parts[ref].assembly)
        self.assertEqual(mismatches, [])


if __name__ == "__main__":
    unittest.main()
