"""过滤贴装坐标并验证完整制造资料。"""
from __future__ import annotations

import csv
import json
import sys
import zipfile
from pathlib import Path

import context
import export_bom


CPL_FIELDS = ("Designator", "Mid X", "Mid Y", "Layer", "Rotation")
RAW_POSITION_FIELDS = {"Ref", "PosX", "PosY", "Rot", "Side"}
REQUIRED_STACKUP = (0.035, 0.2104, 0.0152, 1.065, 0.0152, 0.2104, 0.035)


# 九层（四层铜、双面阻焊、正面钢网、板框）+ 双面丝印（背面印测试点名）+ job + 两个钻孔 + 两张钻孔图
GERBER_FILE_COUNT = 15


def expected_assembly_refs(ctx) -> set[str]:
    return {part.ref for part in ctx.parts if export_bom.is_assembly_item(part)}


def normalized_rotation(value: str) -> str:
    angle = float(value) % 360
    if abs(angle) < 1e-9:
        angle = 0.0
    return f"{angle:g}"


def filter_positions(ctx, source: Path, destination: Path) -> None:
    with source.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = set(reader.fieldnames or ())
        if not fields:
            raise ValueError("坐标文件没有表头")
        missing = RAW_POSITION_FIELDS - fields
        if missing:
            raise ValueError(f"坐标文件缺少列: {sorted(missing)}")
        expected = expected_assembly_refs(ctx)
        rows = []
        for row in reader:
            if row["Ref"] not in expected:
                continue
            side = row["Side"].strip().lower()
            if side not in {"top", "bottom"}:
                raise ValueError(f"未知贴装层: {row['Side']}")
            rows.append({
                "Designator": row["Ref"],
                "Mid X": row["PosX"],
                "Mid Y": row["PosY"],
                "Layer": side.title(),
                "Rotation": normalized_rotation(row["Rot"]),
            })
    if not fields:
        raise ValueError("坐标文件没有表头")
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, CPL_FIELDS, lineterminator="\n")
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
        refs = [row["Designator"] for row in csv.DictReader(stream)]
    if len(refs) != len(set(refs)):
        raise ValueError("坐标文件位号重复")
    return set(refs)


def validate_assembly_sets(ctx, bom_refs: set[str], position_refs: set[str]) -> None:
    expected = expected_assembly_refs(ctx)
    if bom_refs != expected or position_refs != expected:
        raise ValueError(
            f"装配集合不一致: expected={len(expected)}, BOM={len(bom_refs)}, CPL={len(position_refs)}, "
            f"missing_bom={sorted(expected - bom_refs)}, extra_bom={sorted(bom_refs - expected)}, "
            f"missing_cpl={sorted(expected - position_refs)}, extra_cpl={sorted(position_refs - expected)}"
        )


def validate_stackup(job: Path) -> None:
    data = json.loads(job.read_text(encoding="utf-8"))
    stack = [float(layer["Thickness"]) for layer in data.get("MaterialStackup", [])
             if layer.get("Type") in {"Copper", "Dielectric"} and "Thickness" in layer]
    if len(stack) != len(REQUIRED_STACKUP) or any(
            abs(actual - expected) > 0.0001 for actual, expected in zip(stack, REQUIRED_STACKUP)):
        raise ValueError(f"Gerber job 叠层不符: expected={REQUIRED_STACKUP}, actual={tuple(stack)}")


def validate(ctx, fab: Path) -> None:
    bom_refs = _bom_refs(fab / "bom.csv")
    position_refs = _position_refs(fab / "positions.csv")
    validate_assembly_sets(ctx, bom_refs, position_refs)
    gerbers = sorted(path for path in (fab / "gerber").iterdir() if path.is_file())
    if len(gerbers) != GERBER_FILE_COUNT or any(path.stat().st_size == 0 for path in gerbers):
        raise ValueError(f"Gerber/钻孔文件应为 {GERBER_FILE_COUNT} 个非空文件，实际 {len(gerbers)}")
    archive = fab / "gerber.zip"
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if {item.filename for item in members} != {path.name for path in gerbers} \
                or any(item.file_size == 0 for item in members):
            raise ValueError("gerber.zip 与 gerber/ 内容不一致或包含空文件")
    jobs = [path for path in gerbers if path.name.endswith("-job.gbrjob")]
    if len(jobs) != 1:
        raise ValueError(f"Gerber job 文件应有且仅有一个，实际 {len(jobs)}")
    validate_stackup(jobs[0])


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "filter-positions":
        filter_positions(context.load(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) == 4 and sys.argv[1] == "validate":
        validate(context.load(sys.argv[2]), Path(sys.argv[3]))
    else:
        raise SystemExit("usage: fab_tools.py filter-positions VARIANT INPUT OUTPUT | validate VARIANT FAB_DIR")
