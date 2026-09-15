#!/usr/bin/env bash
# 导出嘉立创下单所需的制造文件：Gerber + 钻孔（打包 zip）、BOM、坐标文件，以及最终渲染图。
# 先在临时目录完成 DRC、导出和交叉校验，全部成功后才替换现有资料。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KC=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
PCB="$ROOT/plush-toy-mainboard.kicad_pcb"
FAB="$ROOT/fab"
TMP="$(mktemp -d "$ROOT/.fab-export.XXXXXX")"
BACKUP="$ROOT/.fab-backup.$$"
cleanup() {
    rm -rf "$TMP"
    if [[ -d "$BACKUP" && ! -d "$FAB" ]]; then mv "$BACKUP" "$FAB"; fi
}
trap cleanup EXIT
mkdir -p "$TMP/fab/gerber"

cd "$ROOT/scripts"
python3 -m unittest test_kicad_env test_config_pins test_board_spec test_part_pins \
    test_netlist_roundtrip test_export_bom -v
"$KP" -m unittest test_project_lib test_pcb test_drc test_post_route -v

# 四层铜 + 双面阻焊 + 正面丝印与钢网（单面贴片，底面无丝印无钢网）+ 板框
$KC pcb export gerbers \
    --layers "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Mask,B.Mask,F.SilkS,F.Paste,Edge.Cuts" \
    --subtract-soldermask --check-zones \
    -o "$TMP/fab/gerber/" "$PCB"
$KC pcb export drill --format excellon --excellon-separate-th --generate-map --map-format gerberx2 \
    -o "$TMP/fab/gerber/" "$PCB"
(cd "$TMP/fab/gerber" && zip -q ../gerber.zip ./*)

# BOM：描述性位号不符合 KiCad 的字母+数字注释规则，直接从唯一数据源 board_spec 导出。
python3 "$ROOT/scripts/export_bom.py" "$TMP/fab/bom.csv"

# 坐标文件：KiCad 原始 CSV 转为嘉立创 Designator/Mid X/Mid Y/Layer/Rotation，单位 mm
$KC pcb export pos --format csv --units mm --side front --exclude-dnp -o "$TMP/raw-positions.csv" "$PCB"
python3 "$ROOT/scripts/fab_tools.py" filter-positions "$TMP/raw-positions.csv" "$TMP/fab/positions.csv"

python3 "$ROOT/scripts/fab_tools.py" validate "$TMP/fab"

$KC pcb render --side top --width 1600 --height 1100 -o "$TMP/final_top.png" "$PCB"
$KC pcb render --side bottom --width 1600 --height 1100 -o "$TMP/final_bottom.png" "$PCB"

if [[ -d "$FAB" ]]; then mv "$FAB" "$BACKUP"; fi
mv "$TMP/fab" "$FAB"
mv "$TMP/final_top.png" "$ROOT/renders/final_top.png"
mv "$TMP/final_bottom.png" "$ROOT/renders/final_bottom.png"
rm -rf "$BACKUP"
echo "制造文件：$FAB"
