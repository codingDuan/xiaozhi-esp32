"""把已收敛的正式 PCB 局部升级为 GPIO48 控制的双屏背光。

默认只生成 build/backlight-eco-candidate.kicad_pcb；传入 --apply 时，只有在
DRC、未连接与原理图一致性全部通过后才覆盖正式 PCB。整板重新自动布线目前会在
U_TOUCH/J_CAM 密集区失去已收敛路径，因此本 ECO 只做局部改动：拆掉板载 RGB 灯、
把双屏排针换成 8 针，并在排针下方空区新增 GPIO48 驱动的背光高边开关。
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pcbnew

import board_spec
import gen_pcb
import placement
import project_rules
from post_route import PCB, Router, drc, mm, retidy_silkscreen


CANDIDATE = PCB.parent / "build" / "backlight-eco-candidate.kicad_pcb"


def part(ref: str) -> board_spec.Part:
    return next(item for item in board_spec.PARTS if item.ref == ref)


def point(item) -> tuple[float, float]:
    pos = item.GetPosition()
    return mm(pos.x), mm(pos.y)


def endpoint(item, layer=pcbnew.F_Cu) -> tuple[float, float, int]:
    return (*point(item), layer)


def add_missing_nets(board: pcbnew.BOARD) -> None:
    for name in ("LCD_BL_PWM", "LCD_BL_GATE", "LCD_BL"):
        if board.FindNet(name) is None:
            board.Add(pcbnew.NETINFO_ITEM(board, name))


def remove_legacy_led(board: pcbnew.BOARD) -> None:
    old = [board.FindFootprintByReference(ref) for ref in ("D_LED", "C_LED")]
    pad_positions = {(pad.GetPosition().x, pad.GetPosition().y)
                     for fp in old if fp is not None for pad in fp.Pads()}
    orphan_candidates: set[tuple[int, int]] = set()
    for item in list(board.GetTracks()):
        start = (item.GetStart().x, item.GetStart().y)
        end = (item.GetEnd().x, item.GetEnd().y)
        if item.GetNetname() == "LED_RGB" or start in pad_positions or end in pad_positions:
            if item.GetClass() != "PCB_VIA":
                orphan_candidates |= {start, end}
            board.Delete(item)
    for fp in old:
        if fp is not None:
            board.Delete(fp)
    remove_orphan_vias(board, orphan_candidates)


def remove_orphan_vias(board: pcbnew.BOARD, candidates: set[tuple[int, int]]) -> None:
    """删掉只为被删走线服务的过孔。

    只看被删走线的端点，不扫全板：GND 缝合孔和 XCLK 护线孔本来就独立于走线存在，
    按「没有走线接它」的通用规则会把它们一并删掉。
    """
    live = {(item.GetStart().x, item.GetStart().y) for item in board.GetTracks()
            if item.GetClass() != "PCB_VIA"}
    live |= {(item.GetEnd().x, item.GetEnd().y) for item in board.GetTracks()
             if item.GetClass() != "PCB_VIA"}
    for item in list(board.GetTracks()):
        if item.GetClass() != "PCB_VIA":
            continue
        here = (item.GetPosition().x, item.GetPosition().y)
        if here in candidates and here not in live:
            board.Delete(item)


def configure_footprint(board: pcbnew.BOARD, ref: str, position, angle: float):
    spec = part(ref)
    fp = gen_pcb.load(spec)
    fp.SetPosition(position)
    fp.SetOrientationDegrees(angle)
    fp.Value().SetVisible(False)
    if ref.startswith("R_"):
        fp.Reference().SetVisible(False)
    board.Add(fp)
    for pad in fp.Pads():
        net = spec.pins.get(pad.GetNumber())
        if net and not net.startswith("NC_"):
            pad.SetNet(board.FindNet(net))
    return fp


def replace_eye_connector(board: pcbnew.BOARD, ref: str):
    old = board.FindFootprintByReference(ref)
    if old is None:
        raise RuntimeError(f"找不到 {ref}")
    position = old.GetPosition()
    angle = old.GetOrientationDegrees()
    reference_position = old.Reference().GetPosition()
    reference_angle = old.Reference().GetTextAngleDegrees()
    board.Delete(old)
    fp = configure_footprint(board, ref, position, angle)
    fp.Reference().SetPosition(reference_position)
    fp.Reference().SetTextAngleDegrees(reference_angle)
    fp.Reference().SetVisible(True)
    return fp


def replace_safety_silkscreen(board: pcbnew.BOARD) -> None:
    """按 placement.safety_silk 重放安全丝印。

    屏排针从 7 针加到 8 针后，8 脚焊盘右移 2.54mm，原来的两行 5V 标签离屏排针
    只剩 5.5mm，又会被读成「屏幕座是 5V」——正是 2026-09-14 评审要消除的误读。
    """
    wanted = placement.safety_silk({fp.GetReference(): fp for fp in board.GetFootprints()})
    # 板级 F.SilkS 文字只可能来自 safety_silk，整批清掉再重放，改文案时不会留下旧字。
    for item in list(board.GetDrawings()):
        if isinstance(item, pcbnew.PCB_TEXT) and item.GetLayer() == pcbnew.F_SilkS:
            board.Delete(item)
    for text, x, y, justify in wanted:
        gen_pcb.add_silk_text(board, text, x, y, justify)


def add_backlight_parts(board: pcbnew.BOARD):
    result = {}
    for ref in ("Q_LCD_BL", "R_LCD_BL_GATE", "R_LCD_BL_OFF"):
        x, y, angle = placement.ANCHORS[ref]
        result[ref] = configure_footprint(board, ref, gen_pcb.v(x, y), angle)
    result["Q_LCD_BL"].Reference().SetVisible(False)
    return result


def route_backlight(board: pcbnew.BOARD, fps: dict[str, pcbnew.FOOTPRINT]) -> None:
    u1 = board.FindFootprintByReference("U1")
    gpio = u1.FindPadByNumber("25")
    gpio.SetNet(board.FindNet("LCD_BL_PWM"))

    gate_resistor = fps["R_LCD_BL_GATE"]
    off_resistor = fps["R_LCD_BL_OFF"]
    switch = fps["Q_LCD_BL"]
    router = Router(board)

    # GPIO48 → 100Ω → 栅极；100k 上拉把栅极钉在 +3V3，上电默认关背光。
    paths = (
        ("LCD_BL_PWM", gpio, gate_resistor.FindPadByNumber("1"), 0.2),
        ("LCD_BL_GATE", gate_resistor.FindPadByNumber("2"), switch.FindPadByNumber("1"), 0.2),
        ("LCD_BL_GATE", off_resistor.FindPadByNumber("2"), switch.FindPadByNumber("1"), 0.2),
    )
    for net, start, end, width in paths:
        path = router.find_path(net, endpoint(start), endpoint(end))
        router.add_path(net, path, width)
        router.invalidate_obstacles(net)

    # 源极与上拉各自就近打孔接 In2.Cu 的 +3V3 覆铜（该覆铜止于 x=62，两颗都在其内）。
    for pad, width in ((switch.FindPadByNumber("2"), 0.5),
                       (off_resistor.FindPadByNumber("1"), 0.2)):
        path, via_at = router.find_via_path("+3V3", point(pad), radius=3.0, width=width)
        router.add_path("+3V3", path, width)
        router.add_via("+3V3", via_at)
        router.invalidate_obstacles("+3V3")

    # 漏极先接下排屏，再沿排针右侧竖直上行接上排屏。
    left = board.FindFootprintByReference("J_LCD_L").FindPadByNumber("8")
    right = board.FindFootprintByReference("J_LCD_R").FindPadByNumber("8")
    drain = switch.FindPadByNumber("3")
    for start, end in ((drain, right), (right, left)):
        path = router.find_path("LCD_BL", endpoint(start), endpoint(end))
        router.add_path("LCD_BL", path, 0.5)
        router.invalidate_obstacles("LCD_BL")


def validate(report: dict) -> None:
    violations = report.get("violations", [])
    unexpected = [item for item in violations
                  if item.get("type") != "silk_edge_clearance" or
                  not any(child.get("description") == "Segment of U1 on F.Silkscreen"
                          for child in item.get("items", []))]
    if unexpected or len(violations) != 2:
        raise RuntimeError(f"背光 ECO DRC 出现非预期违规：{unexpected or violations}")
    if report.get("unconnected_items"):
        raise RuntimeError(f"背光 ECO 仍有未连接：{report['unconnected_items'][:5]}")
    if report.get("schematic_parity"):
        raise RuntimeError(f"背光 ECO 与原理图不一致：{report['schematic_parity'][:5]}")


def main(apply: bool = False) -> Path:
    board = pcbnew.LoadBoard(str(PCB))
    add_missing_nets(board)
    remove_legacy_led(board)
    replace_eye_connector(board, "J_LCD_L")
    replace_eye_connector(board, "J_LCD_R")
    fps = add_backlight_parts(board)
    route_backlight(board, fps)
    # 排针加长到 8 针、又多了三颗新器件，安全丝印和位号都要整体重排。
    replace_safety_silkscreen(board)
    retidy_silkscreen(board)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    CANDIDATE.parent.mkdir(exist_ok=True)
    board.Save(str(CANDIDATE))
    project_rules.apply()
    report = drc(CANDIDATE)
    validate(report)
    if apply:
        shutil.copy2(CANDIDATE, PCB)
        return PCB
    return CANDIDATE


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(main(args.apply))
