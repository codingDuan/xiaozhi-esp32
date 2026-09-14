"""用 KiCad 自带 Python 运行：导出 Specctra DSN → Freerouting 自动布线 → 导回 SES → 重铺铜 → 保存。

Freerouting 2.4.1 需要 Java 25 及以上（class file 69），用 Homebrew 的 openjdk。
jar 放在 hardware/plush-toy-mainboard/tools/，不进 git（体积 64MB）。
"""
import subprocess
import sys
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parents[1]
PCB = ROOT / "plush-toy-mainboard.kicad_pcb"
BUILD = ROOT / "build"
JAR = ROOT / "tools" / "freerouting-2.4.1.jar"
JAVA = "/opt/homebrew/opt/openjdk/bin/java"


def main(passes: int = 30) -> None:
    BUILD.mkdir(exist_ok=True)
    dsn, ses = BUILD / "board.dsn", BUILD / "board.ses"
    board = pcbnew.LoadBoard(str(PCB))
    if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
        raise RuntimeError("导出 DSN 失败")
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
    board.Save(str(PCB))
    print("布线完成：", PCB)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
