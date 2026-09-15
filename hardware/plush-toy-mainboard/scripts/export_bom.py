"""从 board_spec 导出嘉立创 BOM，保留描述性且唯一的规范位号。"""
from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

import board_spec


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "fab" / "bom.csv"
FIELDS = ("Designator", "Comment", "Footprint", "LCSC Part #", "Quantity")
HAND_INSTALLED_REFS = {
    part.ref for part in board_spec.PARTS
    if part.fitted and not part.assembly and part.ref.startswith("J_")
}


def natural_ref(ref: str) -> tuple:
    return tuple(int(piece) if piece.isdigit() else piece for piece in re.split(r"(\d+)", ref))


def is_assembly_item(part: board_spec.Part) -> bool:
    return part.fitted and part.assembly


def rows() -> list[dict[str, str]]:
    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for part in board_spec.PARTS:
        if is_assembly_item(part):
            groups[(part.value, part.footprint, part.lcsc)].append(part.ref)
    result = []
    for (value, footprint, lcsc), refs in sorted(groups.items()):
        refs.sort(key=natural_ref)
        result.append({
            "Designator": ",".join(refs),
            "Comment": value,
            "Footprint": footprint,
            "LCSC Part #": lcsc,
            "Quantity": str(len(refs)),
        })
    return result


def main(output: Path = DEFAULT_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as destination:
        writer = csv.DictWriter(destination, FIELDS, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows())
    return output


if __name__ == "__main__":
    print(main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT))
