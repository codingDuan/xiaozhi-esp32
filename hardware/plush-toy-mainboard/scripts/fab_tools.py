"""过滤贴装坐标并验证完整制造资料。"""
from __future__ import annotations

import csv
import sys
import zipfile
from pathlib import Path

from export_bom import HAND_INSTALLED_REFS


def filter_positions(source: Path, destination: Path) -> None:
    with source.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        rows = [row for row in reader if row["Ref"] not in HAND_INSTALLED_REFS]
        fields = reader.fieldnames
    if not fields:
        raise ValueError("坐标文件没有表头")
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _bom_refs(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    if any(not row["LCSC Part #"] for row in rows):
        raise ValueError("自动贴装 BOM 存在空 LCSC Part #")
    refs = [ref for row in rows for ref in row["Designator"].split(",")]
    if len(refs) != len(set(refs)):
        raise ValueError("BOM 位号重复")
    return set(refs)


def _position_refs(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        refs = [row["Ref"] for row in csv.DictReader(stream)]
    if len(refs) != len(set(refs)):
        raise ValueError("坐标文件位号重复")
    return set(refs)


def validate(fab: Path) -> None:
    bom_refs = _bom_refs(fab / "bom.csv")
    position_refs = _position_refs(fab / "positions.csv")
    if bom_refs != position_refs or len(bom_refs) != 74:
        raise ValueError(f"BOM/CPL 不一致: BOM={len(bom_refs)}, CPL={len(position_refs)}, "
                         f"only_bom={sorted(bom_refs - position_refs)}, "
                         f"only_cpl={sorted(position_refs - bom_refs)}")
    gerbers = sorted(path for path in (fab / "gerber").iterdir() if path.is_file())
    if len(gerbers) != 14 or any(path.stat().st_size == 0 for path in gerbers):
        raise ValueError(f"Gerber/钻孔文件应为 14 个非空文件，实际 {len(gerbers)}")
    archive = fab / "gerber.zip"
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if {item.filename for item in members} != {path.name for path in gerbers} \
                or any(item.file_size == 0 for item in members):
            raise ValueError("gerber.zip 与 gerber/ 内容不一致或包含空文件")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "filter-positions":
        filter_positions(Path(sys.argv[2]), Path(sys.argv[3]))
    elif len(sys.argv) == 3 and sys.argv[1] == "validate":
        validate(Path(sys.argv[2]))
    else:
        raise SystemExit("usage: fab_tools.py filter-positions INPUT OUTPUT | validate FAB_DIR")
