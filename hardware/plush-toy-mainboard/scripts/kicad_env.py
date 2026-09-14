"""定位本机 KiCad 10 安装，并提供库查询。只读，不修改 KiCad 任何文件。"""
import re
from pathlib import Path

APP = Path("/Applications/KiCad/KiCad.app")
KICAD_CLI = str(APP / "Contents/MacOS/kicad-cli")
KICAD_PYTHON = str(APP / "Contents/Frameworks/Python.framework/Versions/Current/bin/python3")
SHARED = APP / "Contents/SharedSupport"
SYMBOL_DIR = SHARED / "symbols"
FOOTPRINT_DIR = SHARED / "footprints"

# 工程自带库，放在 hardware/plush-toy-mainboard/lib/，与工程目录下的
# sym-lib-table / fp-lib-table 保持一致：
#   plush  按原厂数据手册手工绘制（INMP441）
#   lcsc   easyeda2kicad 从 LCSC 转出的第三方封装，布局阶段须逐颗人工复核
PROJECT_DIR = Path(__file__).resolve().parents[1]
PROJECT_LIBS = {"plush", "lcsc"}


def symbol_file(lib: str) -> Path:
    if lib in PROJECT_LIBS:
        return PROJECT_DIR / "lib" / f"{lib}.kicad_sym"
    return SYMBOL_DIR / f"{lib}.kicad_sym"


def footprint_dir(lib: str) -> Path:
    if lib in PROJECT_LIBS:
        return PROJECT_DIR / "lib" / f"{lib}.pretty"
    return FOOTPRINT_DIR / f"{lib}.pretty"


def symbol_exists(lib: str, name: str) -> bool:
    path = symbol_file(lib)
    if not path.exists():
        return False
    return f'(symbol "{name}"' in path.read_text(encoding="utf-8")


def footprint_exists(lib: str, name: str) -> bool:
    return (footprint_dir(lib) / f"{name}.kicad_mod").exists()


def _read_sch_version() -> int:
    # 不猜文件格式版本号：取 KiCad 自带工程里的实际值，保证生成的原理图能被这个版本打开。
    # demos 目录在 dmg 里与 KiCad.app 并列，不一定被装上；template 在 app 包内，一定存在。
    for folder in (SHARED / "template", APP.parent / "demos"):
        for sch in sorted(folder.rglob("*.kicad_sch")):
            m = re.search(r"\(version (\d+)\)", sch.read_text(encoding="utf-8", errors="ignore"))
            if m:
                return int(m.group(1))
    raise RuntimeError("KiCad 自带 template 与 demos 中都找不到 .kicad_sch，无法确定文件格式版本")


SCH_FILE_VERSION = _read_sch_version()
