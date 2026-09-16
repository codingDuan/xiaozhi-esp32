#!/usr/bin/env python3
"""把板载麦克风换成外接 J_MIC 座。

板载麦克风要求主板本身放在玩偶能「听见」的位置：塞进胸腔再包一层棉花就废了。
拆解的成品机芯是外接的，改成一样。拆掉 U_MIC / C_MIC / R_MIC_SD（声孔随 U_MIC
封装一起消失），在原位置放一个 6 脚 SH 座，把 MIC_SD / MIC_WS / MIC_SCK 接过去。

默认只生成 build/external-mic-candidate.kicad_pcb；传入 --apply 时，只有在 DRC、
未连接与原理图一致性全部通过后才覆盖正式 PCB。
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

CANDIDATE = PCB.parent / "build" / "external-mic-candidate.kicad_pcb"
LEGACY = ("U_MIC", "C_MIC", "R_MIC_SD")


def part(ref: str) -> board_spec.Part:
    return next(item for item in board_spec.PARTS if item.ref == ref)


def point(item) -> tuple[float, float]:
    pos = item.GetPosition()
    return mm(pos.x), mm(pos.y)


def endpoint(item, layer=pcbnew.F_Cu) -> tuple[float, float, int]:
    return (*point(item), layer)


def remove_onboard_mic(board: pcbnew.BOARD) -> None:
    """拆掉板载麦克风三件，并清空三条 MIC 线。

    MIC_SD / MIC_WS / MIC_SCK 只连 U1 和麦克风两端，麦克风一走，整条线都得重走；
    留着半截旧走线只会变成 track_dangling。声孔是 U_MIC 封装的一部分，随封装消失。
    """
    old = [board.FindFootprintByReference(ref) for ref in LEGACY]
    pads = {(pad.GetPosition().x, pad.GetPosition().y)
            for fp in old if fp is not None for pad in fp.Pads()}
    signals = {"MIC_SD", "MIC_WS", "MIC_SCK"}
    orphans: set[tuple[int, int]] = set()
    for item in list(board.GetTracks()):
        start = (item.GetStart().x, item.GetStart().y)
        end = (item.GetEnd().x, item.GetEnd().y)
        if item.GetNetname() in signals or start in pads or end in pads:
            if item.GetClass() != "PCB_VIA":
                orphans |= {start, end}
            board.Delete(item)
    for fp in old:
        if fp is not None:
            board.Delete(fp)
    # 只删被删走线留下的孤立过孔；GND 缝合孔本来就独立存在，不能一起扫掉。
    live = {(item.GetStart().x, item.GetStart().y) for item in board.GetTracks()
            if item.GetClass() != "PCB_VIA"}
    live |= {(item.GetEnd().x, item.GetEnd().y) for item in board.GetTracks()
             if item.GetClass() != "PCB_VIA"}
    for item in list(board.GetTracks()):
        if item.GetClass() != "PCB_VIA":
            continue
        here = (item.GetPosition().x, item.GetPosition().y)
        if here in orphans and here not in live:
            board.Delete(item)


def add_connector(board: pcbnew.BOARD) -> pcbnew.FOOTPRINT:
    spec = part("J_MIC")
    x, y, angle = placement.ANCHORS["J_MIC"]
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


def nearest_pad(board: pcbnew.BOARD, net: str, origin: tuple[float, float],
                skip: str) -> pcbnew.PAD:
    """该网络上离 origin 最近的对端焊盘。

    skip 用位号而不是封装对象：pcbnew 的 SWIG 每次 GetFootprints() 都返回新的代理
    对象，`fp is connector` 永远为假，结果会把座子自己的焊盘当成对端，走线绕回自身。
    """
    candidates = []
    for fp in board.GetFootprints():
        if fp.GetReference() == skip:
            continue
        for pad in fp.Pads():
            if pad.GetNetname() == net:
                here = point(pad)
                candidates.append(((here[0] - origin[0]) ** 2
                                   + (here[1] - origin[1]) ** 2, pad))
    if not candidates:
        raise RuntimeError(f"找不到 {net} 的对端焊盘")
    return min(candidates, key=lambda item: item[0])[1]


def escape_direction(connector: pcbnew.FOOTPRINT) -> tuple[float, float]:
    """焊盘排背离座体的方向。

    SH 是 1.0mm 脚距，相邻焊盘只隔 0.4mm，走线从焊盘旁边挤不过去（实测 DRC 报
    solder_mask_bridge 和 shorting_items）。所以每根线先垂直逃出焊盘排再拐弯。
    """
    origin = point(connector)
    pads = [point(pad) for pad in connector.Pads() if pad.GetNumber().isdigit()]
    dx = sum(p[0] for p in pads) / len(pads) - origin[0]
    dy = sum(p[1] for p in pads) / len(pads) - origin[1]
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    return dx / length, dy / length


def route_connector(board: pcbnew.BOARD, connector: pcbnew.FOOTPRINT) -> None:
    router = Router(board)
    ux, uy = escape_direction(connector)

    def escape(pad) -> tuple[float, float]:
        """焊盘外 1.6mm 处的逃逸点，对齐到路由器栅格。"""
        here = point(pad)
        return router.physical(router.grid_point((here[0] + ux * 1.6, here[1] + uy * 1.6)))

    # 逃逸段和 A* 段拼成一条折线一次加进去：分两次加，两段的接点会因为
    # A* 起点被吸附到栅格而对不上，DRC 报 track_dangling。
    for number, net in (("3", "MIC_SD"), ("4", "MIC_WS"), ("5", "MIC_SCK")):
        pad = connector.FindPadByNumber(number)
        start = escape(pad)
        target = nearest_pad(board, net, start, connector.GetReference())
        path = router.find_path(net, (*start, pcbnew.F_Cu), endpoint(target))
        router.add_path(net, [(*point(pad), pcbnew.F_Cu), *path], 0.2)
        router.invalidate_obstacles(net)

    # 电源与地就近打孔接内层覆铜。两个 GND 脚各打各的，不互相借道。
    for number, net in (("1", "+3V3"), ("2", "GND"), ("6", "GND")):
        pad = connector.FindPadByNumber(number)
        start = escape(pad)
        path, via_at = router.find_via_path(net, start, radius=4.0, width=0.3)
        router.add_path(net, [(*point(pad), pcbnew.F_Cu), *path], 0.3)
        router.add_via(net, via_at)
        router.invalidate_obstacles(net)


def validate(report: dict) -> None:
    violations = report.get("violations", [])
    unexpected = [item for item in violations
                  if item.get("type") != "silk_edge_clearance" or
                  not any(child.get("description") == "Segment of U1 on F.Silkscreen"
                          for child in item.get("items", []))]
    if unexpected:
        raise RuntimeError(f"外接麦克风 ECO 出现非预期违规：{unexpected}")
    if report.get("unconnected_items"):
        raise RuntimeError(f"外接麦克风 ECO 仍有未连接：{report['unconnected_items'][:5]}")
    if report.get("schematic_parity"):
        raise RuntimeError(f"外接麦克风 ECO 与原理图不一致：{report['schematic_parity'][:5]}")


def main(apply: bool = False) -> Path:
    board = pcbnew.LoadBoard(str(PCB))
    remove_onboard_mic(board)
    connector = add_connector(board)
    route_connector(board, connector)
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
