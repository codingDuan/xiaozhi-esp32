"""用 KiCad 自带 Python 运行：导出 Specctra DSN → Freerouting 自动布线 → 导回 SES → 重铺铜 → 保存。

Freerouting 2.4.1 需要 Java 25 及以上（class file 69），用 Homebrew 的 openjdk。
jar 放在 hardware/plush-toy-mainboard/tools/，不进 git（体积 64MB）。
"""
import subprocess
import sys
from pathlib import Path

import pcbnew

import project_rules

ROOT = Path(__file__).resolve().parents[1]
PCB = ROOT / "plush-toy-mainboard.kicad_pcb"
BUILD = ROOT / "build"
JAR = ROOT / "tools" / "freerouting-2.4.1.jar"
JAVA = "/opt/homebrew/opt/openjdk/bin/java"


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
    if len(candidate.get("violations", [])) > len(baseline.get("violations", [])):
        return False
    baseline_errors = {fingerprint(item) for item in baseline.get("violations", [])
                       if item.get("severity") == "error"}
    candidate_errors = {fingerprint(item) for item in candidate.get("violations", [])
                        if item.get("severity") == "error"}
    if not candidate_errors.issubset(baseline_errors):
        return False
    baseline_parity = {fingerprint(item) for item in baseline.get("schematic_parity", [])}
    candidate_parity = {fingerprint(item) for item in candidate.get("schematic_parity", [])}
    return candidate_parity.issubset(baseline_parity)


def discard_stale_output(path: Path) -> None:
    """Freerouting 必须产生本次运行的新 SES，不能误导入旧会话。"""
    path.unlink(missing_ok=True)


def main(passes: int = 30) -> None:
    import post_route

    BUILD.mkdir(exist_ok=True)
    dsn, ses = BUILD / "board.dsn", BUILD / "board.ses"
    candidate = BUILD / "freerouting-candidate.kicad_pcb"
    baseline_report = post_route.drc(PCB)
    board = pcbnew.LoadBoard(str(PCB))
    if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
        raise RuntimeError("导出 DSN 失败")
    discard_stale_output(ses)
    cmd = [JAVA, "-jar", str(JAR), "-de", str(dsn), "-do", str(ses), "-mp", str(passes)]
    print("运行：", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    tail = "\n".join((result.stdout + result.stderr).splitlines()[-15:])
    print(tail)
    if result.returncode != 0 or not ses.exists():
        raise RuntimeError(f"Freerouting 失败，退出码 {result.returncode}")
    board = pcbnew.LoadBoard(str(PCB))
    if not pcbnew.ImportSpecctraSES(board, str(ses)):
        raise RuntimeError("导入 SES 失败")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(candidate))
    # board.Save 会用默认规则覆盖 .kicad_pro，重新写回工程规则（见 gen_pcb.py 同处注释）
    project_rules.apply()
    candidate_report = post_route.drc(candidate)
    if not is_non_regressing(baseline_report, candidate_report):
        counts = lambda report: tuple(len(report[key]) for key in
                                      ("violations", "unconnected_items", "schematic_parity"))
        raise RuntimeError(f"拒绝回退的 Freerouting 结果：{counts(baseline_report)} -> "
                           f"{counts(candidate_report)}；候选保留在 {candidate}")
    candidate.replace(PCB)
    project_rules.apply()
    print("布线完成并通过非回退检查：", PCB)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
