"""用 KiCad 自带 Python 运行：给贴在顶层的 GND / +3V3 焊盘接到内层平面。

为什么要这一步：Freerouting 不会主动往 power 类型的内层平面打过孔，GND 与 +3V3 焊盘
在 2026-09-14 第二次布线后仍有 41 条未连接。这些网络本来就该就近下平面，先扇出，
布线器只剩真正的信号线要走。

规则：
- GND 平面在 In1，覆盖整板；+3V3 平面在 In2，只覆盖逻辑区（x < 62，gen_pcb.add_zone）
- 只处理 F.Cu 贴片焊盘；附近已有同网络通孔焊盘（如 U1.41 模组自带的散热过孔）视为已接
- 大焊盘（散热焊盘）直接在焊盘内打过孔
- 小焊盘先试着连到同器件、同网络的散热焊盘上；不行再在焊盘外找过孔位置，
  优先朝器件中心的反方向，由近到远最多 2mm
- 间距取工程规则 Default 类的 0.15mm；非金属化孔按孔间距规则 0.25mm 再加余量取 0.3mm。
  线宽取 0.4mm 与焊盘短边中较小者，细间距引脚才挤得出去
  （首版统一 0.4mm 线宽、0.2mm 间距，0.5mm 间距的 QFN 引脚全部找不到位置）
"""
import math
from pathlib import Path

import pcbnew

import placement as pl
import project_rules

ROOT = Path(__file__).resolve().parents[1]
PCB = ROOT / "plush-toy-mainboard.kicad_pcb"
TO_MM = 1e-6

PLANES = {"GND": (0.0, pl.W), "+3V3": (0.0, 61.5)}     # 网络 → 平面在 x 方向的覆盖范围
VIA_D, VIA_DRILL = 0.6, 0.3
CLEARANCE = 0.15
HOLE_CLEARANCE = 0.3
EDGE = 0.6
MAX_TRACK_W = 0.4
BIG_PAD_AREA = 1.0          # mm²，超过视为散热焊盘，焊盘内打过孔
ALREADY_CONNECTED = 2.0     # mm，同网络通孔焊盘在此距离内视为已接平面
STEPS = (0.0, 0.3, 0.6, 1.0, 1.5, 2.0)


def v(x: float, y: float) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def box_mm(b):
    return b.GetX() * TO_MM, b.GetY() * TO_MM, b.GetRight() * TO_MM, b.GetBottom() * TO_MM


def circle_hits_box(cx, cy, r, box) -> bool:
    nx = min(max(cx, box[0]), box[2])
    ny = min(max(cy, box[1]), box[3])
    return (cx - nx) ** 2 + (cy - ny) ** 2 < r * r


def segment_hits_box(x1, y1, x2, y2, half_w, box) -> bool:
    # 线段短（< 5mm），每 0.05mm 取一点，按「线宽一半 + 间距」为半径判断
    n = max(2, int(math.hypot(x2 - x1, y2 - y1) / 0.05))
    return any(circle_hits_box(x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n, half_w, box) for i in range(n + 1))


class Fanout:
    def __init__(self, board: pcbnew.BOARD):
        self.board = board
        self.pads = [p for fp in board.GetFootprints() for p in fp.Pads()]
        # (网络, 包围盒, 是否非金属化孔)
        self.obstacles = [(p.GetNetname(), box_mm(p.GetBoundingBox()),
                           p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH) for p in self.pads]
        self.vias: list[tuple[str, float, float]] = []

    def clear(self, net, check) -> bool:
        return not any(n != net and check(ob, HOLE_CLEARANCE if npth else CLEARANCE)
                       for n, ob, npth in self.obstacles)

    def add_layer_track(self, net_item, start, end, width, layer) -> None:
        t = pcbnew.PCB_TRACK(self.board)
        t.SetStart(start)
        t.SetEnd(end)
        t.SetWidth(pcbnew.FromMM(width))
        t.SetLayer(layer)
        t.SetNet(net_item)
        self.board.Add(t)
        if layer == pcbnew.F_Cu:
            x1, x2 = sorted((start.x * TO_MM, end.x * TO_MM))
            y1, y2 = sorted((start.y * TO_MM, end.y * TO_MM))
            self.obstacles.append((net_item.GetNetname(),
                                   (x1 - width / 2, y1 - width / 2,
                                    x2 + width / 2, y2 + width / 2), False))

    def add_track(self, net_item, start, end, width) -> None:
        self.add_layer_track(net_item, start, end, width, pcbnew.F_Cu)

    def add_via(self, net_item, net, x, y, diameter=VIA_D, drill=VIA_DRILL) -> None:
        via = pcbnew.PCB_VIA(self.board)
        via.SetPosition(v(x, y))
        via.SetWidth(pcbnew.FromMM(diameter))
        via.SetDrill(pcbnew.FromMM(drill))
        via.SetNet(net_item)
        self.board.Add(via)
        self.vias.append((net, x, y))
        self.obstacles.append((net, (x - diameter / 2, y - diameter / 2,
                                     x + diameter / 2, y + diameter / 2), False))

    def via_ok(self, net, x, y, plane) -> bool:
        if not (EDGE <= x <= pl.W - EDGE and EDGE <= y <= pl.H - EDGE and plane[0] <= x <= plane[1]):
            return False
        if any(math.hypot(x - ox, y - oy) < VIA_D + CLEARANCE for _, ox, oy in self.vias):
            return False
        return self.clear(net, lambda ob, c: circle_hits_box(x, y, VIA_D / 2 + c, ob))

    def pad(self, ref: str, number: str):
        return self.board.FindFootprintByReference(ref).FindPadByNumber(number)

    def route_usb_efuse(self) -> int:
        """先并联 eFuse 的三个输入脚，长电源干线和支持元件留给自动布线。"""
        added = 0
        # 三个 IN 焊盘先在芯片侧并成一体；这段短铜也为远端保险丝提供单一入口。
        pins = [self.pad("U_EFUSE", number) for number in ("2", "3", "4")]
        for first, second in zip(pins, pins[1:]):
            self.add_track(first.GetNet(), first.GetPosition(), second.GetPosition(), 0.2)

        cap = self.pad("C_EFUSE_IN", "1")
        self.add_track(pins[1].GetNet(), pins[1].GetPosition(), cap.GetPosition(), 0.5)
        output = self.pad("U_EFUSE", "5")
        self.add_track(output.GetNet(), output.GetPosition(), v(36.50, 19.75), 0.2)

        return added

    def route_buck_hot_loop(self) -> int:
        """固定降压高 di/dt 回路：SW 全程顶层、输入去耦与地回流都在芯片旁。"""
        sw = self.pad("U_BUCK", "3")
        inductor = self.pad("L_BUCK", "1")
        sw_path = [sw.GetPosition(), v(37.15, 14.95), inductor.GetPosition()]
        for a, b in zip(sw_path, sw_path[1:]):
            self.add_track(sw.GetNet(), a, b, 0.5)

        vin = self.pad("U_BUCK", "4")
        hf_vin = self.pad("C_BUCK_HF", "1")
        bulk_vin = self.pad("C_BUCK_IN", "1")
        self.add_track(vin.GetNet(), vin.GetPosition(), hf_vin.GetPosition(), 0.5)
        bulk_path = [vin.GetPosition(), v(42.25, 14.95), v(42.25, 9.70),
                     v(39.05, 9.70), bulk_vin.GetPosition()]
        for a, b in zip(bulk_path, bulk_path[1:]):
            self.add_track(vin.GetNet(), a, b, 0.5)

        # 不在小贴片焊盘里打孔，避免回流焊吸锡；每个焊盘用极短支线接平面。
        ground_vias = [
            (self.pad("U_BUCK", "2"), (39.70, 14.00)),
            (self.pad("C_BUCK_HF", "2"), (38.72, 17.24)),
            (self.pad("C_BUCK_IN", "2"), (41.00, 11.75)),
        ]
        for pad, (x, y) in ground_vias:
            self.add_track(pad.GetNet(), pad.GetPosition(), v(x, y), 0.4)
            self.add_via(pad.GetNet(), "GND", x, y)
        return len(ground_vias)

    def route_u1_power_and_en(self) -> int:
        """先锁定 ESP32 就地去耦与 EN RC，按键的长支路仍交给自动布线。"""
        v3 = self.pad("U1", "2")
        local_v3 = self.pad("C_U1", "1")
        bulk_v3 = self.pad("C_U1_BULK", "1")
        self.add_track(v3.GetNet(), v3.GetPosition(), local_v3.GetPosition(), 0.5)
        self.add_track(v3.GetNet(), local_v3.GetPosition(), bulk_v3.GetPosition(), 0.5)

        ground_vias = [
            (self.pad("C_U1", "2"), (3.00, 43.23)),
            (self.pad("C_U1_BULK", "2"), (1.30, 44.025)),
        ]
        for pad, (x, y) in ground_vias:
            self.add_track(pad.GetNet(), pad.GetPosition(), v(x, y), 0.4)
            self.add_via(pad.GetNet(), "GND", x, y)

        en = self.pad("U1", "3")
        resistor = self.pad("R_EN", "2")
        capacitor = self.pad("C_EN", "1")
        en_path = [en.GetPosition(), resistor.GetPosition(), capacitor.GetPosition()]
        for a, b in zip(en_path, en_path[1:]):
            self.add_track(en.GetNet(), a, b, 0.2)
        return len(ground_vias)

    def route_sensitive_ground_islands(self) -> int:
        """固定三个自动扇出难以安全处理的地脚，并避开麦克风声孔。"""
        for ref, number, x, y, width in (
                ("C_EN", "2", 6.75, 41.52, 0.4),
                ("U_MIC", "5", 16.80, 50.00, 0.2)):
            pad = self.pad(ref, number)
            self.add_track(pad.GetNet(), pad.GetPosition(), v(x, y), width)
            self.add_via(pad.GetNet(), "GND", x, y)

        amp_ep = self.pad("U_AMP", "17")
        x, y = amp_ep.GetPosition().x * TO_MM, amp_ep.GetPosition().y * TO_MM
        self.add_via(amp_ep.GetNet(), "GND", x, y)
        return 3

    def route_touch_e8(self) -> int:
        """锁定触摸芯片顶边 E8 到测试点，避免 XCLK 护线封住后续出口。"""
        source = self.pad("U_TOUCH", "16")
        target = self.pad("TP_E8", "1")
        path = [source.GetPosition(), v(30.80, 43.25), v(28.25, 43.25), target.GetPosition()]
        for a, b in zip(path, path[1:]):
            self.add_track(source.GetNet(), a, b, 0.2)
        return 0

    def route_camera_xclk_guards(self) -> int:
        """在 F.Cu 独立走 XCLK，并给所有长直段加 0.65mm 双侧接地护线。"""
        source = self.pad("U1", "8")
        target = self.pad("J_CAM", "13")
        points = [
            source.GetPosition(), v(10.38, 41.50), v(19.50, 41.50),
            v(19.50, 45.50), v(25.80, 45.50), v(25.80, 49.50),
            v(39.75, 49.50), v(39.75, 52.50), target.GetPosition(),
        ]
        for a, b in zip(points, points[1:]):
            self.add_track(source.GetNet(), a, b, 0.2)

        guard_net = self.board.FindNet("GND")
        via_points: set[tuple[float, float]] = set()
        for a, b in zip(points, points[1:]):
            ax, ay = a.x * TO_MM, a.y * TO_MM
            bx, by = b.x * TO_MM, b.y * TO_MM
            length = math.hypot(bx - ax, by - ay)
            if length <= 3.0:
                continue
            nx, ny = -(by - ay) / length, (bx - ax) / length
            for side in (-1.0, 1.0):
                ux, uy = (bx - ax) / length, (by - ay) / length
                trim = 0.70
                start = (ax + trim * ux + side * 0.65 * nx,
                         ay + trim * uy + side * 0.65 * ny)
                end = (bx - trim * ux + side * 0.65 * nx,
                       by - trim * uy + side * 0.65 * ny)
                self.add_track(guard_net, v(*start), v(*end), 0.5)
                count = max(1, math.ceil((length - 2 * trim) / 3.0))
                for index in range(count + 1):
                    ratio = index / count
                    via_points.add((round(start[0] + (end[0] - start[0]) * ratio, 3),
                                    round(start[1] + (end[1] - start[1]) * ratio, 3)))
        stitched = []
        for x, y in sorted(via_points):
            if any(math.hypot(x - ox, y - oy) < HOLE_CLEARANCE for ox, oy in stitched):
                continue
            self.add_via(guard_net, "GND", x, y)
            stitched.append((x, y))
        return len(stitched)

    def escape_camera_fpc(self) -> int:
        """先把 0.5mm 间距相机焊盘引到连接器外，避免自动布线封住出口。"""
        fp = self.board.FindFootprintByReference("J_CAM")
        if fp is None:
            return 0
        added = 0
        for pad in fp.Pads():
            number = pad.GetNumber()
            net = pad.GetNetname()
            if not number.isdigit() or int(number) > 24 or not net or net.startswith("unconnected-"):
                continue
            if net == "CAM_XCLK":
                continue
            start = pad.GetPosition()
            x, y = start.x * TO_MM, start.y * TO_MM
            number_value = int(number)
            end_y = box_mm(pad.GetBoundingBox())[3] + (1.1 if number_value % 2 == 0 else 2.2)
            end = v(x, end_y)
            if any(t.GetClass() == "PCB_TRACK" and t.GetNetname() == net and
                   (t.GetStart() == start or t.GetEnd() == start) for t in self.board.GetTracks()):
                continue
            self.add_track(pad.GetNet(), start, end, 0.2)
            self.add_via(pad.GetNet(), net, x, end_y, diameter=0.45, drill=0.2)
            self.obstacles.append((net, (x - 0.1, y, x + 0.1, end_y), False))
            added += 1
        return added

    def escape_imu_plane_pads(self) -> int:
        """在自动布线前绕开 IMU 中央禁布区，固定三个底边电源脚的出口。"""
        fp = self.board.FindFootprintByReference("U_IMU")
        p8, p9, p11 = (fp.FindPadByNumber(number) for number in ("8", "9", "11"))
        bottom = max(box_mm(p.GetBoundingBox())[3] for p in (p8, p9, p11))
        escape_y, via_y = bottom + 0.35, bottom + 1.125
        x8, x9, x11 = (p.GetPosition().x * TO_MM for p in (p8, p9, p11))

        self.add_track(p9.GetNet(), p9.GetPosition(), v(x9, escape_y), 0.2)
        gnd_via_x = x9 - 0.75
        self.add_track(p9.GetNet(), v(x9, escape_y), v(gnd_via_x, via_y), 0.2)
        self.add_via(p9.GetNet(), "GND", gnd_via_x, via_y)

        gnd_cap = self.board.FindFootprintByReference("C_IMU_VLOGIC").FindPadByNumber("2")
        cap_x, cap_y = gnd_cap.GetPosition().x * TO_MM, gnd_cap.GetPosition().y * TO_MM
        self.add_track(p11.GetNet(), p11.GetPosition(), v(x11, escape_y), 0.2)
        self.add_track(p11.GetNet(), v(x11, escape_y), v(cap_x, escape_y), 0.2)
        self.add_track(p11.GetNet(), v(cap_x, escape_y), v(cap_x, cap_y), 0.2)

        v3_via_x = x8 - 1.45
        self.add_track(p8.GetNet(), p8.GetPosition(), v(x8, escape_y), 0.2)
        self.add_track(p8.GetNet(), v(x8, escape_y), v(v3_via_x, via_y), 0.2)
        self.add_via(p8.GetNet(), "+3V3", v3_via_x, via_y)
        return 2

    def escape_dense_sensor_signals(self) -> int:
        """给 IMU/触摸芯片外围信号脚加径向短线，保留细间距引脚出口。"""
        added = 0
        for ref in ("U_IMU", "U_TOUCH"):
            fp = self.board.FindFootprintByReference(ref)
            center = fp.GetPosition()
            for pad in fp.Pads():
                net = pad.GetNetname()
                if not net or net in PLANES or net.startswith("unconnected-"):
                    continue
                pos = pad.GetPosition()
                dx, dy = (pos.x - center.x) * TO_MM, (pos.y - center.y) * TO_MM
                if math.hypot(dx, dy) < 1.0:
                    continue
                box = box_mm(pad.GetBoundingBox())
                x, y = pos.x * TO_MM, pos.y * TO_MM
                if abs(dx) > abs(dy):
                    end = v((box[2] + 0.9) if dx > 0 else (box[0] - 0.9), y)
                else:
                    end = v(x, (box[3] + 0.9) if dy > 0 else (box[1] - 0.9))
                half = 0.1 + CLEARANCE
                if not self.clear(net, lambda ob, c: segment_hits_box(x, y, end.x * TO_MM,
                                                                       end.y * TO_MM, half, ob)):
                    continue
                self.add_track(pad.GetNet(), pos, end, 0.2)
                added += 1

        fp = self.board.FindFootprintByReference("U_AMP")
        pad = fp.FindPadByNumber("10")
        pos = pad.GetPosition()
        box = box_mm(pad.GetBoundingBox())
        self.add_track(pad.GetNet(), pos, v(box[2] + 0.9, pos.y * TO_MM), 0.2)
        added += 1
        return added

    def route_imu_regout(self) -> int:
        pad = self.board.FindFootprintByReference("U_IMU").FindPadByNumber("10")
        cap = self.board.FindFootprintByReference("C_IMU_REG").FindPadByNumber("1")
        px, py = pad.GetPosition().x * TO_MM, pad.GetPosition().y * TO_MM
        cx, cy = cap.GetPosition().x * TO_MM, cap.GetPosition().y * TO_MM
        escape_y = box_mm(pad.GetBoundingBox())[3] + 0.9
        self.add_track(pad.GetNet(), pad.GetPosition(), v(px, escape_y), 0.2)
        self.add_track(pad.GetNet(), v(px, escape_y), v(cx, escape_y), 0.2)
        self.add_track(pad.GetNet(), v(cx, escape_y), v(cx, cy), 0.2)
        return 0

    def escape_touch_ground(self) -> int:
        pad = self.board.FindFootprintByReference("U_TOUCH").FindPadByNumber("4")
        pos = pad.GetPosition()
        via_x, via_y = 27.3, pos.y * TO_MM
        self.add_track(pad.GetNet(), pos, v(via_x, via_y), 0.2)
        self.add_via(pad.GetNet(), "GND", via_x, via_y)
        return 1

    def escape_usb_esd_ground(self) -> int:
        """给 USB ESD 阵列地脚固定短回路，避免两颗器件竞争同一狭窄过孔位置。"""
        pad = self.pad("D_USB_DP", "2")
        via_x, via_y = 27.60, 11.00
        self.add_track(pad.GetNet(), pad.GetPosition(), v(via_x, via_y), 0.2)
        self.add_via(pad.GetNet(), "GND", via_x, via_y)
        return 1

    def route_camera_dvdd(self) -> int:
        """用底层固定连接 J_CAM.10 与去耦端，避免密脚距区被后续走线封闭。"""
        jcam = self.board.FindFootprintByReference("J_CAM").FindPadByNumber("10")
        cap = self.board.FindFootprintByReference("C_CAM_DVDD").FindPadByNumber("1")
        jx = jcam.GetPosition().x * TO_MM
        jy = box_mm(jcam.GetBoundingBox())[3] + 1.1
        cx, cy = cap.GetPosition().x * TO_MM, cap.GetPosition().y * TO_MM - 1.0
        net_item = jcam.GetNet()

        # J_CAM 侧复用 escape_camera_fpc 已放置的交错过孔。
        self.add_track(net_item, cap.GetPosition(), v(cx, cy), 0.2)
        self.add_via(net_item, "+1V5", cx, cy)
        detour_x, inner_y = 33.4, 56.2
        self.add_layer_track(net_item, v(jx, jy), v(jx, inner_y), 0.2, pcbnew.B_Cu)
        self.add_layer_track(net_item, v(jx, inner_y), v(detour_x, inner_y), 0.2, pcbnew.B_Cu)
        self.add_layer_track(net_item, v(detour_x, inner_y), v(detour_x, cy), 0.2, pcbnew.B_Cu)
        self.add_layer_track(net_item, v(detour_x, cy), v(cx, cy), 0.2, pcbnew.B_Cu)
        return 2

    def anchor_servo_pgnd(self) -> int:
        """把热焊盘被孤立的舵机 PGND 脚直接伸入 B.Cu 的 PGND 实心区。"""
        pad = self.board.FindFootprintByReference("J_SERVO_L").FindPadByNumber("3")
        pos = pad.GetPosition()
        self.add_layer_track(pad.GetNet(), pos,
                             v(pos.x * TO_MM - 3.0, pos.y * TO_MM), 0.8, pcbnew.B_Cu)
        return 0

    def run(self) -> tuple[int, list[str]]:
        added = self.route_usb_efuse()
        added += self.route_buck_hot_loop()
        added += self.route_u1_power_and_en()
        added += self.route_sensitive_ground_islands()
        added += self.route_touch_e8()
        added += self.route_camera_xclk_guards()
        added += self.escape_camera_fpc()
        added += self.escape_touch_ground()
        added += self.escape_dense_sensor_signals()
        added += self.route_imu_regout()
        added += self.escape_imu_plane_pads()
        added += self.escape_usb_esd_ground()
        added += self.route_camera_dvdd()
        added += self.anchor_servo_pgnd()
        skipped = []
        pth = [(p.GetNetname(), p.GetPosition().x * TO_MM, p.GetPosition().y * TO_MM) for p in self.pads
               if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
        # 大焊盘先处理：小引脚要连到它们的过孔上
        targets = [p for p in self.pads
                   if p.GetNetname() in PLANES and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and p.IsOnLayer(pcbnew.F_Cu)]
        targets.sort(key=lambda p: -(p.GetSizeX() * p.GetSizeY()))
        ep_vias: dict[tuple[str, str], tuple[float, float]] = {}

        for pad in targets:
            net = pad.GetNetname()
            fp = pad.GetParentFootprint()
            ref = fp.GetReference()
            px, py = pad.GetPosition().x * TO_MM, pad.GetPosition().y * TO_MM
            plane = PLANES[net]
            if not (plane[0] <= px <= plane[1]):
                continue
            if any(n == net and math.hypot(x - px, y - py) <= ALREADY_CONNECTED for n, x, y in pth):
                continue
            if any(n == net and math.hypot(x - px, y - py) <= VIA_D for n, x, y in self.vias):
                continue
            if (ref == "U_IMU" and pad.GetNumber() in ("8", "9", "11")) or \
                    (ref == "U_TOUCH" and pad.GetNumber() == "4") or \
                    (ref == "D_USB_DP" and pad.GetNumber() == "2") or \
                    (ref == "U_TOUCH" and pad.GetNumber() == "16") or \
                    (ref, pad.GetNumber()) in {("C_EN", "2"), ("U_MIC", "5"), ("U_AMP", "17")}:
                continue
            b = box_mm(pad.GetBoundingBox())
            w, h = b[2] - b[0], b[3] - b[1]

            if w * h >= BIG_PAD_AREA and self.via_ok(net, px, py, plane):
                self.add_via(pad.GetNet(), net, px, py)          # 散热焊盘内打过孔
                ep_vias[(ref, net)] = (px, py)
                added += 1
                continue

            width = min(MAX_TRACK_W, w, h)
            half = width / 2

            # 先试连到同器件同网络散热焊盘的过孔
            if (ref, net) in ep_vias:
                ex, ey = ep_vias[(ref, net)]
                own = [o for o in self.obstacles if o[0] == net]
                if math.hypot(ex - px, ey - py) <= 3.0 and \
                        self.clear(net, lambda ob, c: segment_hits_box(px, py, ex, ey, half + c, ob)):
                    self.add_track(pad.GetNet(), pad.GetPosition(), v(ex, ey), width)
                    continue

            cx, cy = fp.GetPosition().x * TO_MM, fp.GetPosition().y * TO_MM
            out = math.atan2(py - cy, px - cx) if (px, py) != (cx, cy) else 0.0
            directions = [out, out + math.pi / 4, out - math.pi / 4, out + math.pi / 2, out - math.pi / 2,
                          out + 3 * math.pi / 4, out - 3 * math.pi / 4, out + math.pi]
            placed = False
            for step in STEPS:
                for a in directions:
                    dx, dy = math.cos(a), math.sin(a)
                    # 焊盘在该方向上的半宽
                    extent = abs(dx) * w / 2 + abs(dy) * h / 2
                    reach = extent + CLEARANCE + VIA_D / 2 + step
                    vx, vy = px + reach * dx, py + reach * dy
                    if not self.via_ok(net, vx, vy, plane):
                        continue
                    if not self.clear(net, lambda ob, c: segment_hits_box(px, py, vx, vy, half + c, ob)):
                        continue
                    self.add_via(pad.GetNet(), net, vx, vy)
                    self.add_track(pad.GetNet(), pad.GetPosition(), v(vx, vy), width)
                    added += 1
                    placed = True
                    break
                if placed:
                    break
            if not placed:
                skipped.append(f"{ref}.{pad.GetNumber()}[{net}]")
        return added, skipped


def main() -> tuple[int, list[str]]:
    board = pcbnew.LoadBoard(str(PCB))
    added, skipped = Fanout(board).run()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(PCB))
    project_rules.apply()
    return added, skipped


if __name__ == "__main__":
    added, skipped = main()
    print(f"扇出过孔 {added} 个；找不到位置 {len(skipped)} 个：{skipped}")
