#!/usr/bin/env bash
# 导出嘉立创下单所需的制造文件：Gerber + 钻孔（打包 zip）、BOM、坐标、料号库存报告，以及渲染图。
# 用法：bash export_fab.sh A
# 先在临时目录完成测试、导出和交叉校验，全部成功后才替换现有资料。
set -euo pipefail
V="${1:?用法: export_fab.sh <版本名>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KC=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
DIR="$ROOT/variants/$V"
PCB="$DIR/plush-toy-v2-$V.kicad_pcb"
FAB="$DIR/fab"
TMP="$(mktemp -d "$DIR/.fab-export.XXXXXX")"
BACKUP="$DIR/.fab-backup.$$"
cleanup() {
    rm -rf "$TMP"
    if [[ -d "$BACKUP" && ! -d "$FAB" ]]; then mv "$BACKUP" "$FAB"; fi
}
trap cleanup EXIT
mkdir -p "$TMP/fab/gerber" "$DIR/renders"

cd "$ROOT/scripts"
python3 -m unittest test_parts_db test_gpio test_core test_variants test_netlist
"$KP" -m unittest "test_pcb_$V" "test_drc_$V"

# 四层铜 + 双面阻焊 + 双面丝印（背面印测试点名）+ 正面钢网（单面贴片）+ 板框
$KC pcb export gerbers \
    --layers "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Mask,B.Mask,F.SilkS,B.SilkS,F.Paste,Edge.Cuts" \
    --subtract-soldermask --check-zones \
    -o "$TMP/fab/gerber/" "$PCB"
$KC pcb export drill --format excellon --excellon-separate-th --generate-map --map-format gerberx2 \
    -o "$TMP/fab/gerber/" "$PCB"
(cd "$TMP/fab/gerber" && zip -q ../gerber.zip ./*)

python3 export_bom.py --variant "$V" --output "$TMP/fab/bom.csv"

# 坐标文件：KiCad 原始 CSV 转为嘉立创 Designator/Mid X/Mid Y/Layer/Rotation，单位 mm
$KC pcb export pos --format csv --units mm --side front --exclude-dnp -o "$TMP/raw-positions.csv" "$PCB"
python3 fab_tools.py filter-positions "$V" "$TMP/raw-positions.csv" "$TMP/fab/positions.csv"

python3 fab_tools.py validate "$V" "$TMP/fab"

# 料号库存：库存不足时非零退出，整次导出作废
python3 export_bom.py --variant "$V" --report --output "$TMP/fab/parts_report.txt"

$KC pcb render --side top --width 1600 --height 1100 -o "$TMP/final_top.png" "$PCB"
$KC pcb render --side bottom --width 1600 --height 1100 -o "$TMP/final_bottom.png" "$PCB"

if [[ -d "$FAB" ]]; then mv "$FAB" "$BACKUP"; fi
mv "$TMP/fab" "$FAB"
mv "$TMP/final_top.png" "$DIR/renders/final_top.png"
mv "$TMP/final_bottom.png" "$DIR/renders/final_bottom.png"
rm -rf "$BACKUP"
echo "制造文件：$FAB"
