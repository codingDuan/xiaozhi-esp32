"""在已收敛的布线上应用 2026-09-14 第二轮评审的三项局部修改（ECO），不重跑自动布线。

用 KiCad 自带 Python 运行，之后必须接 `post_route.py --apply` 做收尾与 DRC 把关：

    $KP apply_review_eco.py && $KP post_route.py --apply

为什么不从 gen_pcb 重跑：C_BUCK_IN 转向与 VBUS_FUSED 主干预布改变了 Freerouting 的输入，
连续两轮自动布线加收尾都在 U_TOUCH / J_CAM 密集区留下 6 条开路（TOUCH_E1/E4/E5/E6、
CAM_VSYNC、CAM_HREF），而这些区域与本次修改无关。生成脚本已写入同样的意图
（placement.py、fanout.py），供下次整板重布时使用。

修改内容：
1. 安全丝印按 placement.safety_silk 重新摆放（5V 标签贴 J_VMOT，触摸标签贴 J_TOUCH）
2. C_BUCK_IN 转 180°，VIN 与 GND 连接按 fanout.route_buck_hot_loop 的新几何重连
3. VBUS_FUSED 从 F_USB.2 到 eFuse 输入按 0.5mm 单层重走并锁定，去掉 0.2mm 窄颈
"""
import math

import pcbnew

import gen_pcb
import placement as pl
import project_rules
from post_route import PCB, Router, mm, vec

REVIEW_SILK = {"电机/加热专用 5V", "VMOT 仅限 5V", "头部触摸 E0 / GND", "头部触摸\nE0 / GND"}


def near(point, target, tolerance=0.02) -> bool:
    return math.dist(point, target) < tolerance


def xy(point) -> tuple[float, float]:
    return mm(point.x), mm(point.y)


def add_track(board, net: str, start, end, width: float, locked: bool = False):
    track = pcbnew.PCB_TRACK(board)
    track.SetStart(vec(start))
    track.SetEnd(vec(end))
    track.SetWidth(pcbnew.FromMM(width))
    track.SetLayer(pcbnew.F_Cu)
    track.SetNet(board.FindNet(net))
    track.SetLocked(locked)
    board.Add(track)


def move_review_silkscreen(board) -> None:
    for item in list(board.GetDrawings()):
        if isinstance(item, pcbnew.PCB_TEXT) and item.GetText() in REVIEW_SILK:
            board.Delete(item)
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    for text, x, y, justify in pl.safety_silk(fps):
        if text in REVIEW_SILK:
            gen_pcb.add_silk_text(board, text, x, y, justify)


def rotate_buck_input_capacitor(board) -> tuple[float, float]:
    cap = board.FindFootprintByReference("C_BUCK_IN")
    old_vbus, old_gnd = (xy(cap.FindPadByNumber(n).GetPosition()) for n in ("1", "2"))
    # 旧 VIN 绕线 (42.25,14.95)→(42.25,9.70)→(40,9.70)→(40,11)→旧 1 脚：两端都在这组点上的段删除，
    # U_BUCK.4→(42.25,14.95) 一端不在其中，保留。
    old_path = [(42.25, 14.95), (42.25, 9.70), (40.00, 9.70), (40.00, 11.00), old_vbus]
    for item in list(board.GetTracks()):
        a, b = xy(item.GetStart()), xy(item.GetEnd())
        on_old_path = all(any(near(p, q) for q in old_path) for p in (a, b))
        if item.GetNetname() == "VBUS" and item.GetClass() == "PCB_TRACK" and on_old_path:
            board.Delete(item)
        # 旧 2 脚（转向后变成 VBUS 焊盘）上的焊盘内过孔、支线与 (41.00,11.75) 地过孔
        elif item.GetNetname() == "GND" and any(near(p, q) for p in (a, b)
                                                for q in (old_gnd, (41.00, 11.75))):
            board.Delete(item)
    cap.SetOrientationDegrees(180)
    new_vbus, new_gnd = (xy(cap.FindPadByNumber(n).GetPosition()) for n in ("1", "2"))
    for a, b in (((42.25, 14.95), (42.25, 11.00)), ((42.25, 11.00), new_vbus)):
        add_track(board, "VBUS", a, b, 0.5)
    router = Router(board)
    path, via_at = router.find_via_path("GND", new_gnd, radius=1.0, width=0.4)
    router.add_path("GND", path, 0.4)
    router.add_via("GND", via_at)
    return via_at


def reroute_fused_trunk(board) -> int:
    efuse = board.FindFootprintByReference("U_EFUSE")
    cap = board.FindFootprintByReference("C_EFUSE_IN").FindPadByNumber("1")
    pins = [xy(efuse.FindPadByNumber(n).GetPosition()) for n in ("2", "3", "4")]
    for item in list(board.GetTracks()):
        if item.GetNetname() == "VBUS_FUSED":
            board.Delete(item)
    # 与 fanout.route_usb_efuse 相同：三个 IN 焊盘并联，3 脚 0.5mm 接输入电容
    for a, b in zip(pins, pins[1:]):
        add_track(board, "VBUS_FUSED", a, b, 0.2)
    add_track(board, "VBUS_FUSED", pins[1], xy(cap.GetPosition()), 0.5)
    fuse = xy(board.FindFootprintByReference("F_USB").FindPadByNumber("2").GetPosition())
    router = Router(board)
    path = router.find_layer_path("VBUS_FUSED", (*fuse, pcbnew.F_Cu), (32.50, 19.25, pcbnew.F_Cu), 0.5)
    added = router.add_path("VBUS_FUSED", path, 0.5)
    for item in added:
        item.SetLocked(True)
    return len(added)


def main() -> None:
    board = pcbnew.LoadBoard(str(PCB))
    move_review_silkscreen(board)
    via = rotate_buck_input_capacitor(board)
    trunk = reroute_fused_trunk(board)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(PCB))
    project_rules.apply()
    print(f"ECO 完成：C_BUCK_IN 地过孔 {via}，VBUS_FUSED 主干 {trunk} 段")


if __name__ == "__main__":
    main()
