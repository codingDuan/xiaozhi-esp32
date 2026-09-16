#!/usr/bin/env python3
"""把 J_EXT 调试/外接按键口加进已收敛的正式 PCB。

装进玩偶后板载的 SW_RST / SW_BOOT 按不到，必须把 EN 和 BOOT 引出来；顺带引出
TX 和一组 3V3/GND，做日志口和外接按键板的取电点。拆解的成品机芯也是这么做的。

默认只生成 build/ext-header-candidate.kicad_pcb；传入 --apply 时，只有在 DRC、
未连接与原理图一致性全部通过后才覆盖正式 PCB。和背光那次一样只做局部 ECO：
整板重新自动布线会在 U_TOUCH/J_CAM 密集区失去已收敛路径。
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

CANDIDATE = PCB.parent / "build" / "ext-header-candidate.kicad_pcb"


def part(ref: str) -> board_spec.Part:
    return next(item for item in board_spec.PARTS if item.ref == ref)


def point(item) -> tuple[float, float]:
    pos = item.GetPosition()
    return mm(pos.x), mm(pos.y)


def endpoint(item, layer=pcbnew.F_Cu) -> tuple[float, float, int]:
    return (*point(item), layer)


def add_header(board: pcbnew.BOARD) -> pcbnew.FOOTPRINT:
    spec = part("J_EXT")
    x, y, angle = placement.ANCHORS["J_EXT"]
    fp = gen_pcb.load(spec)
    fp.SetPosition(gen_pcb.v(x, y))
    fp.SetOrientationDegrees(angle)
    fp.Value().SetVisible(False)
    board.Add(fp)
    for pad in fp.Pads():
        net = spec.pins.get(pad.GetNumber())
        if net:
            pad.SetNet(board.FindNet(net))
    return fp


def nearest_pad(board: pcbnew.BOARD, refs: tuple[str, ...], net: str,
                origin: tuple[float, float]) -> pcbnew.PAD:
    """在给定器件里找该网络上离 origin 最近的焊盘，接线最短。"""
    candidates = []
    for ref in refs:
        fp = board.FindFootprintByReference(ref)
        if fp is None:
            continue
        for pad in fp.Pads():
            if pad.GetNetname() == net:
                here = point(pad)
                candidates.append((((here[0] - origin[0]) ** 2
                                    + (here[1] - origin[1]) ** 2), pad))
    if not candidates:
        raise RuntimeError(f"{refs} 上找不到 {net} 的焊盘")
    return min(candidates, key=lambda item: item[0])[1]


def route_header(board: pcbnew.BOARD, header: pcbnew.FOOTPRINT) -> None:
    router = Router(board)

    # EN 与 BOOT 就近接到两个板载按键：它们本来就在排针左边几毫米处。
    for number, net, refs in (("3", "EN", ("SW_RST",)), ("4", "BOOT", ("SW_BOOT", "R_BOOT"))):
        pad = header.FindPadByNumber(number)
        target = nearest_pad(board, refs, net, point(pad))
        path = router.find_path(net, endpoint(pad), endpoint(target))
        router.add_path(net, path, 0.2)
        router.invalidate_obstacles(net)

    # TX 走到模组的 UART_TX 脚；这一段没有别的落点可借。
    tx = header.FindPadByNumber("2")
    target = nearest_pad(board, ("U1",), "UART_TX", point(tx))
    path = router.find_path("UART_TX", endpoint(tx), endpoint(target))
    router.add_path("UART_TX", path, 0.2)
    router.invalidate_obstacles("UART_TX")

    # 3V3 与 GND 是贴片焊盘，必须各自走一小段再打孔到内层覆铜。
    for number, net in (("1", "+3V3"), ("5", "GND")):
        pad = header.FindPadByNumber(number)
        path, via_at = router.find_via_path(net, point(pad), radius=4.0, width=0.3)
        router.add_path(net, path, 0.3)
        router.add_via(net, via_at)
        router.invalidate_obstacles(net)


def validate(report: dict) -> None:
    violations = report.get("violations", [])
    unexpected = [item for item in violations
                  if item.get("type") != "silk_edge_clearance" or
                  not any(child.get("description") == "Segment of U1 on F.Silkscreen"
                          for child in item.get("items", []))]
    if unexpected:
        raise RuntimeError(f"J_EXT ECO 出现非预期违规：{unexpected}")
    if report.get("unconnected_items"):
        raise RuntimeError(f"J_EXT ECO 仍有未连接：{report['unconnected_items'][:5]}")
    if report.get("schematic_parity"):
        raise RuntimeError(f"J_EXT ECO 与原理图不一致：{report['schematic_parity'][:5]}")


def main(apply: bool = False) -> Path:
    board = pcbnew.LoadBoard(str(PCB))
    header = add_header(board)
    route_header(board, header)
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
