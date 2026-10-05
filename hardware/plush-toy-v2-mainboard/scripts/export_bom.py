"""导出嘉立创 BOM（位号保留描述性名字），并可查料号库存写 parts_report.txt。

python3 export_bom.py --variant A            # 写 variants/A/fab/bom.csv
python3 export_bom.py --variant A --report   # 查嘉立创库存，写 fab/parts_report.txt；库存不足时非零退出
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

import context

FIELDS = ("Designator", "Comment", "Footprint", "LCSC Part #", "Quantity")
MIN_STOCK = 20
JLC_SEARCH = ("https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/"
              "selectSmtComponentList")


def natural_ref(ref: str) -> tuple:
    return tuple(int(piece) if piece.isdigit() else piece for piece in re.split(r"(\d+)", ref))


def is_assembly_item(part) -> bool:
    return part.fitted and part.assembly


def rows(ctx) -> list[dict[str, str]]:
    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for part in ctx.parts:
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


def write_bom(ctx, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as destination:
        writer = csv.DictWriter(destination, FIELDS, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows(ctx))
    return output


def lookup(lcsc: str) -> dict:
    """嘉立创元件接口按料号精确查询，返回 {stock, library}；查不到返回空字典。"""
    body = json.dumps({"keyword": lcsc, "currentPage": 1, "pageSize": 10}).encode()
    request = urllib.request.Request(JLC_SEARCH, body, {"Content-Type": "application/json",
                                                        "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    for item in (data.get("data") or {}).get("componentPageInfo", {}).get("list") or []:
        if item.get("componentCode") == lcsc:
            return {"stock": int(item.get("stockCount") or 0),
                    "library": "基础" if item.get("componentLibraryType") == "base" else "扩展"}
    return {}


def report(ctx, output: Path) -> bool:
    lines, ok, extended = [], True, 0
    for row in rows(ctx):
        info = lookup(row["LCSC Part #"])
        stock = info.get("stock", 0)
        library = info.get("library", "查不到")
        extended += library == "扩展"
        need = int(row["Quantity"])
        flag = ""
        if stock < max(MIN_STOCK, need):
            ok, flag = False, "  ← 库存不足"
        lines.append(f"{row['LCSC Part #']:>10}  {library}  库存 {stock:>8}  ×{need:<2} "
                     f"{row['Comment']}  ({row['Designator']}){flag}")
    lines.append("")
    lines.append(f"料号 {len(lines) - 1} 种，其中扩展库 {extended} 种（每种每单一笔换料费）")
    lines.append("库存检查：" + ("全部 ≥ 20" if ok else "有料号库存不足，见上方标记"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    ctx = context.load(args.variant)
    if args.report:
        out = args.output or ctx.dir / "fab" / "parts_report.txt"
        ok = report(ctx, out)
        print(out.read_text(encoding="utf-8"))
        return 0 if ok else 1
    print(write_bom(ctx, args.output or ctx.dir / "fab" / "bom.csv"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
