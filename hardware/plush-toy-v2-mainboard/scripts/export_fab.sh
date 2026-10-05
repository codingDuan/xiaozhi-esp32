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
LAYERS="$(python3 fab_tools.py gerber-layers "$V")"
POSITION_SIDE="$(python3 fab_tools.py position-side "$V")"

# 四层铜 + 双面阻焊/丝印 + 单面或双面钢网 + 板框
$KC pcb export gerbers \
    --layers "$LAYERS" \
    --subtract-soldermask --check-zones \
    -o "$TMP/fab/gerber/" "$PCB"
$KC pcb export drill --format excellon --excellon-separate-th --generate-map --map-format gerberx2 \
    -o "$TMP/fab/gerber/" "$PCB"
(cd "$TMP/fab/gerber" && zip -q ../gerber.zip ./*)

python3 export_bom.py --variant "$V" --output "$TMP/fab/bom.csv"

# 坐标文件：单面版本仅 front，双面版本 both；再转为嘉立创字段，单位 mm
$KC pcb export pos --format csv --units mm --side "$POSITION_SIDE" --exclude-dnp -o "$TMP/raw-positions.csv" "$PCB"
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
