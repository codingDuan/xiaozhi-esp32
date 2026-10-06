"""导出 C/D 摄像头座 1:1 实物方向核验稿（不是生产文件）。"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import context
import kicad_env


def export(variant: str, output: Path) -> Path:
    ctx = context.load(variant)
    if not ctx.variant.camera:
        raise ValueError(f"版本 {variant} 不含摄像头")
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        kicad_env.KICAD_CLI, "pcb", "export", "pdf",
        "--layers", "F.Fab,F.Silkscreen,Edge.Cuts",
        "--black-and-white", "--sketch-pads-on-fab-layers",
        "--exclude-value", "--scale", "1", "--mode-single",
        "--output", str(output), str(ctx.pcb),
    ], check=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", required=True, choices=("C", "D"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    ctx = context.load(args.variant)
    output = args.output or ctx.dir / "CAMERA_1TO1_CHECK_ONLY.pdf"
    print(export(args.variant, output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
