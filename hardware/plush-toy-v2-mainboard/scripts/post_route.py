"""二期布线后处理：只做重新灌铜、DRC 与非回退判定。

一期那套针对具体位号的修补不搬过来；二期遇到自动布线解决不了的开路，先改 placement，
仍不行再在本文件末尾加专门的 ECO 函数并登记位号与原因。
"""
import json
import shutil
import subprocess
import tempfile

import pcbnew

import kicad_env
import project_rules


def refill_and_save(ctx, path=None) -> None:
    path = path or ctx.pcb
    board = pcbnew.LoadBoard(str(path))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(path))
    # board.Save 会把默认规则写回 .kicad_pro（一期教训）
    project_rules.apply(ctx.pro)


def drc(ctx, path=None) -> dict:
    """在完整工程上下文（原理图、库表、库）里跑未过滤的 DRC 与原理图一致性检查。"""
    path = path or ctx.pcb
    with tempfile.TemporaryDirectory() as directory:
        work = __import__("pathlib").Path(directory) / "variants" / ctx.variant.name
        work.mkdir(parents=True)
        candidate = work / f"{ctx.project}.kicad_pcb"
        shutil.copy2(path, candidate)
        for suffix in (".kicad_pro", ".kicad_sch"):
            shutil.copy2(ctx.dir / f"{ctx.project}{suffix}", work / f"{ctx.project}{suffix}")
        for name in ("fp-lib-table", "sym-lib-table"):
            shutil.copy2(ctx.dir / name, work / name)
        shutil.copytree(ctx.dir.parent.parent / "lib", work.parent.parent / "lib")
        report = work / "drc.json"
        subprocess.run([kicad_env.KICAD_CLI, "pcb", "drc", "--format", "json", "--schematic-parity",
                        "-o", str(report), str(candidate)], check=True, capture_output=True)
        result = json.loads(report.read_text())
    missing = {"violations", "unconnected_items", "schematic_parity"} - result.keys()
    if missing:
        raise RuntimeError(f"DRC 报告缺少字段: {sorted(missing)}")
    return result


def summary(report: dict) -> str:
    errors = [v for v in report["violations"] if v.get("severity") == "error"]
    kinds = {}
    for v in errors:
        kinds[v["type"]] = kinds.get(v["type"], 0) + 1
    return (f"错误 {len(errors)} {kinds}；未连接 {len(report['unconnected_items'])}；"
            f"一致性 {len(report['schematic_parity'])}")
