"""用 KiCad 自带 Python 运行：导出 Specctra DSN → Freerouting 自动布线 → 导回 SES → 重铺铜 → 保存。

Freerouting 2.4.1 需要 Java 25 及以上（class file 69），用 Homebrew 的 openjdk。
jar 放在 hardware/plush-toy-mainboard/tools/（二期经软链接共用），不进 git（体积 64MB）。
用法：route.py --variant A [轮数]
"""
import subprocess
import sys
from pathlib import Path

import pcbnew

import context
import project_rules

ROOT = Path(__file__).resolve().parents[1]
JAR = ROOT / "tools" / "freerouting-2.4.1.jar"      # tools 是指向一期目录的软链接，jar 不进 git
JAVA = "/opt/homebrew/opt/openjdk/bin/java"


def normalize_imported_tracks(board: pcbnew.BOARD) -> int:
    """Freerouting/Specctra 会把最窄逃逸线量化成 0.120 mm；提升到工程制造下限。"""
    minimum = pcbnew.FromMM(project_rules.RULES["min_track_width"])
    changed = 0
    for item in board.GetTracks():
        if item.GetClass() == "PCB_TRACK" and item.GetWidth() < minimum:
            item.SetWidth(minimum)
            changed += 1
    return changed


def is_non_regressing(baseline: dict, candidate: dict) -> bool:
    """只晋升未增加开路、未引入新 error、且未改变一致性缺陷的结果。"""
    def fingerprint(finding: dict) -> tuple:
        items = tuple(sorted(
            (item.get("uuid", ""), item.get("description", ""))
            for item in finding.get("items", [])
        ))
        return finding.get("type", ""), finding.get("severity", ""), items

    if len(candidate.get("unconnected_items", [])) > len(baseline.get("unconnected_items", [])):
        return False
    # 只比较错误：警告（字高、悬空过孔等）数量随走线变化，算进来会误拒更好的结果
    baseline_errors = {fingerprint(item) for item in baseline.get("violations", [])
                       if item.get("severity") == "error"}
    candidate_errors = {fingerprint(item) for item in candidate.get("violations", [])
                        if item.get("severity") == "error"}
    if not candidate_errors.issubset(baseline_errors):
        return False
    baseline_parity = {fingerprint(item) for item in baseline.get("schematic_parity", [])}
    candidate_parity = {fingerprint(item) for item in candidate.get("schematic_parity", [])}
    if not candidate_parity.issubset(baseline_parity):
        return False
    # “持平”不是路由进展，不能覆盖快照并打印“布线完成”。
    return (len(candidate.get("unconnected_items", [])) < len(baseline.get("unconnected_items", []))
            or len(candidate_errors) < len(baseline_errors)
            or len(candidate_parity) < len(baseline_parity))


def discard_stale_output(path: Path) -> None:
    """Freerouting 必须产生本次运行的新 SES，不能误导入旧会话。"""
    path.unlink(missing_ok=True)


def apply_routing_ecos(ctx, board: pcbnew.BOARD) -> int:
    """应用布局文件登记的、经 DRC 验证的微小路由修正。"""
    changed = 0
    tolerance = pcbnew.FromMM(0.01)
    for net, old_mm, new_mm in getattr(ctx.placement, "ROUTING_ECO_VIA_MOVES", []):
        old = pcbnew.VECTOR2I(pcbnew.FromMM(old_mm[0]), pcbnew.FromMM(old_mm[1]))
        new = pcbnew.VECTOR2I(pcbnew.FromMM(new_mm[0]), pcbnew.FromMM(new_mm[1]))
        matched = []
        for item in board.GetTracks():
            if item.GetNetname() != net or item.GetClass() != "PCB_VIA":
                continue
            p = item.GetPosition()
            if abs(p.x - old.x) <= tolerance and abs(p.y - old.y) <= tolerance:
                matched.append(item)
        if not matched:
            already = [item for item in board.GetTracks()
                       if item.GetNetname() == net and item.GetClass() == "PCB_VIA"
                       and abs(item.GetPosition().x - new.x) <= tolerance
                       and abs(item.GetPosition().y - new.y) <= tolerance]
            if len(already) == 1:
                continue
        if len(matched) != 1:
            raise RuntimeError(f"路由 ECO {net}@{old_mm} 应匹配 1 个过孔，实际 {len(matched)} 个")
        matched[0].SetPosition(new)
        for item in board.GetTracks():
            if item.GetNetname() != net or item.GetClass() != "PCB_TRACK":
                continue
            if item.GetStart() == old:
                item.SetStart(new)
            if item.GetEnd() == old:
                item.SetEnd(new)
        changed += 1
    return changed


def main(ctx, passes: int = 30) -> None:
    import post_route

    PCB, BUILD = ctx.pcb, ctx.build
    BUILD.mkdir(exist_ok=True)
    dsn, ses = BUILD / "board.dsn", BUILD / "board.ses"
    candidate = BUILD / "freerouting-candidate.kicad_pcb"
    baseline_report = post_route.drc(ctx)
    board = pcbnew.LoadBoard(str(PCB))
    if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
        raise RuntimeError("导出 DSN 失败")
    discard_stale_output(ses)
    # Freerouting 2.4.1 明确警告多线程优化会产生间距违规；在含铜区的双面板上还会
    # 偶发在保存 SES 前触发 search-tree NPE，留下 0 字节结果。制造输出必须可复现，
    # 因此固定单线程优化。
    # 强制 AWT headless：命令行路由不需要 GUI；否则 macOS 的后台渲染线程会在含重叠优先级
    # 电源区时触发 search-tree NPE，并在日志已经显示 Saving 后留下 0 字节 SES。
    cmd = [JAVA, "-Djava.awt.headless=true", "-jar", str(JAR), "-de", str(dsn), "-do", str(ses),
           "-mp", str(passes), "-mt", "1"]
    print("运行：", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    log = result.stdout + result.stderr
    (BUILD / "freerouting.log").write_text(log, encoding="utf-8")
    tail = "\n".join(log.splitlines()[-15:])
    print(tail)
    if result.returncode != 0 or not ses.exists() or ses.stat().st_size == 0:
        raise RuntimeError(f"Freerouting 失败，退出码 {result.returncode}")
    board = pcbnew.LoadBoard(str(PCB))
    if not pcbnew.ImportSpecctraSES(board, str(ses)):
        raise RuntimeError("导入 SES 失败")
    normalized = normalize_imported_tracks(board)
    if normalized:
        print(f"导入后将 {normalized} 段走线提升到工程最小线宽")
    ecos = apply_routing_ecos(ctx, board)
    if ecos:
        print(f"应用 {ecos} 项已登记路由 ECO")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(candidate))
    # board.Save 会用默认规则覆盖 .kicad_pro，重新写回工程规则（见 gen_pcb.py 同处注释）
    project_rules.apply(ctx.pro)
    candidate_report = post_route.drc(ctx, candidate)
    if not is_non_regressing(baseline_report, candidate_report):
        counts = lambda report: tuple(len(report[key]) for key in
                                      ("violations", "unconnected_items", "schematic_parity"))
        raise RuntimeError(f"拒绝回退的 Freerouting 结果：{counts(baseline_report)} -> "
                           f"{counts(candidate_report)}；候选保留在 {candidate}")
    candidate.replace(PCB)
    project_rules.apply(ctx.pro)
    # 快照：之后只改补线（post_route）时从这里开始，不必重跑 Freerouting（它每次剩下的开路都不同）
    import shutil
    shutil.copy2(PCB, BUILD / "routed-snapshot.kicad_pcb")
    print("布线完成并通过非回退检查：", PCB, post_route.summary(candidate_report))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True)
    parser.add_argument("passes", nargs="?", type=int, default=30)
    args = parser.parse_args()
    main(context.load(args.variant), args.passes)
