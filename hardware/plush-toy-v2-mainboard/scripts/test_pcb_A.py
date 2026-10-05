"""版本 A 的 PCB 结构检查。用 KiCad 自带 Python 运行。"""
import unittest

import pcbnew

import context

ctx = context.load("A")
pl = ctx.placement
TO_MM = 1e-6


class PcbATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = pcbnew.LoadBoard(str(ctx.pcb))
        cls.fps = {f.GetReference(): f for f in cls.board.GetFootprints()}

    def test_outline_matches_placement(self):
        bb = self.board.GetBoardEdgesBoundingBox()
        self.assertAlmostEqual(bb.GetWidth() * TO_MM, pl.W, delta=0.15)
        self.assertAlmostEqual(bb.GetHeight() * TO_MM, pl.H, delta=0.15)

    def test_every_part_placed(self):
        self.assertEqual({p.ref for p in ctx.parts} - set(self.fps), set())

    def test_single_sided(self):
        back = [r for r, f in self.fps.items() if f.GetLayer() == pcbnew.B_Cu and not r.startswith("TP_")]
        self.assertEqual(back, [])

    def test_testpoints_on_back(self):
        for r, f in self.fps.items():
            if r.startswith("TP_"):
                self.assertEqual(f.GetLayer(), pcbnew.B_Cu, r)

    def test_testpoint_names_printed_on_back(self):
        # 验收清单让人按丝印名找测试点（一期委托方曾找不到测试点）
        edge = self.board.GetBoardEdgesBoundingBox()
        back_pads = [p.GetBoundingBox() for f in self.fps.values() for p in f.Pads()
                     if p.IsOnLayer(pcbnew.B_Cu)]
        for r, f in self.fps.items():
            if not r.startswith("TP_"):
                continue
            ref = f.Reference()
            self.assertTrue(ref.IsVisible(), r)
            self.assertEqual(ref.GetLayer(), pcbnew.B_SilkS, r)
            self.assertTrue(ref.IsMirrored(), r)
            bb = ref.GetBoundingBox()
            self.assertTrue(edge.Contains(bb.GetOrigin()) and edge.Contains(bb.GetEnd()), r)
            self.assertFalse(any(bb.Intersects(p) for p in back_pads), r)

    def test_decoupling_parts_close_to_their_pins(self):
        far = []
        checks = [(ref, chip, net, limit) for ref, (chip, net, limit, *rest) in pl.DECOUPLING.items()]
        checks += [(ref, chip, rest[0], limit) for ref, (chip, net, limit, *rest) in pl.DECOUPLING.items() if rest]
        for ref, chip, net, limit in checks:
            mine = [p.GetPosition() for p in self.fps[ref].Pads() if p.GetNetname() == net]
            theirs = [p.GetPosition() for p in self.fps[chip].Pads() if p.GetNetname() == net]
            self.assertTrue(mine and theirs, f"{ref}/{chip} 没有 {net} 焊盘")
            a, b = min(((a, b) for a in mine for b in theirs),
                       key=lambda ab: (ab[0].x - ab[1].x) ** 2 + (ab[0].y - ab[1].y) ** 2)
            d = ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5 * TO_MM
            if d > limit:
                far.append(f"{ref}→{chip}.{net} {d:.1f}mm > {limit}")
            # 必须在引脚那一侧：直线近但隔着芯片的，实际走线要绕过芯片（C_EFUSE_IN 首版即如此，布不通）
            c = self.fps[chip].GetPosition()
            if (b.x - c.x) * (a.x - b.x) + (b.y - c.y) * (a.y - b.y) < 0:
                far.append(f"{ref} 在 {chip}.{net} 引脚的另一侧")
        self.assertEqual(far, [])

    def test_every_edge_connector_has_function_label(self):
        self.assertEqual(set(pl.EDGE_CONNECTORS) - set(pl.CONNECTOR_LABELS), set())
        silk = {t.GetText() for t in self.board.GetDrawings()
                if isinstance(t, pcbnew.PCB_TEXT) and t.GetLayer() == pcbnew.F_SilkS}
        self.assertEqual({r for r, text in pl.CONNECTOR_LABELS.items() if text not in silk}, set())

    def test_power_nets_not_necked_down(self):
        # 补线器找不到宽线通道时会退到 0.2mm；电源网络只允许在焊盘前缩颈 ≤ 1mm（2026-10-05 复查：VSYS 出现 20mm 长 0.2mm 线）
        from post_route import net_class
        narrow = []
        for t in self.board.GetTracks():
            if t.GetClass() != "PCB_TRACK":
                continue
            width = net_class(t.GetNetname())["track_width"]
            # 只查 Power 类（≥0.6mm，安培级、走表层）；+3V3、GND 有整层平面，细线是通往上拉电阻等的支路，正常
            if width >= 0.6 and t.GetWidth() * TO_MM < width * 0.6 and t.GetLength() * TO_MM > 1.0:
                narrow.append(f"{t.GetNetname()} {t.GetWidth() * TO_MM:.2f}mm × {t.GetLength() * TO_MM:.1f}mm")
        self.assertEqual(narrow, [])

    def test_edge_connectors_horizontal_and_open_outward(self):
        # 委托方 2026-10-05：出线座一律卧式、开口朝板边，装壳后线从板边引出；不留竖向座
        horizontal = ("Horizontal", "WT", "USB_C_Receptacle", "-H-")
        problems = []
        for ref, (side, _) in pl.EDGE_CONNECTORS.items():
            fp = self.fps[ref]
            name = fp.GetFPID().GetLibItemName().wx_str()
            if not any(key in name for key in horizontal):
                problems.append(f"{ref} 不是卧式：{name}")
            pins = {n for n, net in next(p for p in ctx.parts if p.ref == ref).pins.items()
                    if not net.startswith("NC_") and n != "SH"}
            signal = [p.GetPosition() for p in fp.Pads() if p.GetNumber() in pins]
            fp.BuildCourtyardCaches()
            body = fp.GetCourtyard(pcbnew.F_CrtYd).BBox().GetCenter()
            dist = {"top": lambda q: q.y, "bottom": lambda q: pl.H / TO_MM - q.y,
                    "left": lambda q: q.x, "right": lambda q: pl.W / TO_MM - q.x}[side]
            if sum(dist(q) for q in signal) / len(signal) <= dist(body):
                problems.append(f"{ref} 开口没有朝 {side} 边")
        self.assertEqual(problems, [])

    def test_pads_of_different_parts_keep_clearance(self):
        # 布局阶段就查焊盘间距：去耦件曾按 0.05mm 占位间隙放，电感大焊盘贴着占位框边，焊盘间只剩 0.15mm（Power 类要 0.2）
        from post_route import net_class
        pads = [(f.GetReference(), p, p.GetBoundingBox()) for f in self.fps.values() for p in f.Pads()
                if p.IsOnLayer(pcbnew.F_Cu) and p.GetNetname()]
        close = []
        for i, (ra, pa, ba) in enumerate(pads):
            for rb, pb, bb in pads[i + 1:]:
                if ra == rb or pa.GetNetname() == pb.GetNetname():
                    continue
                need = max(net_class(pa.GetNetname())["clearance"], net_class(pb.GetNetname())["clearance"])
                gx = max(bb.GetX() - ba.GetRight(), ba.GetX() - bb.GetRight(), 0)
                gy = max(bb.GetY() - ba.GetBottom(), ba.GetY() - bb.GetBottom(), 0)
                if (gx * gx + gy * gy) ** 0.5 * TO_MM < need - 1e-3:
                    close.append(f"{ra}.{pa.GetNumber()}–{rb}.{pb.GetNumber()}")
        self.assertEqual(close, [])

    def test_function_labels_beside_their_own_connector(self):
        # 功能名沿板边离本座子比离同边其他座子都近、且不超过 4mm：ARM R 曾印在左臂座 S 脚旁，照丝印会插错
        import gen_pcb
        gen_pcb.pl = pl
        spans = gen_pcb.edge_spans(self.fps)
        texts = {t.GetText(): t for t in self.board.GetDrawings()
                 if isinstance(t, pcbnew.PCB_TEXT) and t.GetLayer() == pcbnew.F_SilkS}
        wrong = []
        for ref, text in pl.CONNECTOR_LABELS.items():
            c = texts[text].GetBoundingBox().GetCenter()
            along = (c.y if spans[ref][0] in ("left", "right") else c.x) * TO_MM
            if not gen_pcb.label_belongs(ref, along, spans):
                wrong.append(f"{ref} 功能名在 {along:.1f}")
        self.assertEqual(wrong, [])

    def test_pad_nets_match_spec(self):
        for part in ctx.parts:
            for pad in self.fps[part.ref].Pads():
                want = part.pins.get(pad.GetNumber())
                if want and not want.startswith("NC_"):
                    with self.subTest(ref=part.ref, pad=pad.GetNumber()):
                        self.assertEqual(pad.GetNetname(), want)

    def test_antenna_overhangs_edge(self):
        bb = self.fps["U1"].GetBoundingBox(False)
        edges = self.board.GetBoardEdgesBoundingBox()
        self.assertTrue(bb.GetLeft() < edges.GetLeft() or bb.GetTop() < edges.GetTop()
                        or bb.GetRight() > edges.GetRight() or bb.GetBottom() > edges.GetBottom())

    def test_edge_connectors_touch_their_edge(self):
        for ref, (side, _) in pl.EDGE_CONNECTORS.items():
            fp = self.fps[ref]
            fp.BuildCourtyardCaches()
            court = fp.GetCourtyard(pcbnew.F_CrtYd)
            bb = court.BBox() if court.OutlineCount() else fp.GetBoundingBox(False)
            gap = {"top": bb.GetTop() * TO_MM, "bottom": pl.H - bb.GetBottom() * TO_MM,
                   "left": bb.GetLeft() * TO_MM, "right": pl.W - bb.GetRight() * TO_MM}[side]
            with self.subTest(ref=ref):
                self.assertLessEqual(gap, 1.0)

    def test_heat_and_charger_away_from_battery_connector(self):
        def centre(ref):
            p = self.fps[ref].GetPosition()
            return p.x * TO_MM, p.y * TO_MM
        bx, by = centre("J_BAT")
        for ref in ("Q_HEAT", "U_CHG", "U_BUCK"):
            x, y = centre(ref)
            with self.subTest(ref=ref):
                self.assertGreaterEqual(((x - bx) ** 2 + (y - by) ** 2) ** 0.5, 8.0)

    def test_inner_layers_are_power_planes(self):
        for layer in (pcbnew.In1_Cu, pcbnew.In2_Cu):
            self.assertEqual(self.board.GetLayerType(layer), pcbnew.LT_POWER)

    def test_no_courtyard_overlap_on_same_side(self):
        for side, layer in ((pcbnew.F_Cu, pcbnew.F_CrtYd), (pcbnew.B_Cu, pcbnew.B_CrtYd)):
            fps = [f for f in self.fps.values() if f.GetLayer() == side]
            for f in fps:
                f.BuildCourtyardCaches()
            for i, a in enumerate(fps):
                ca = a.GetCourtyard(layer)
                for b in fps[i + 1:]:
                    cb = b.GetCourtyard(layer)
                    if ca.OutlineCount() and cb.OutlineCount():
                        with self.subTest(a=a.GetReference(), b=b.GetReference()):
                            self.assertFalse(ca.Collide(cb.Outline(0)))


if __name__ == "__main__":
    unittest.main()
