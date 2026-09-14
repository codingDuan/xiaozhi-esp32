#!/usr/bin/env bash
# 导出嘉立创下单所需的制造文件：Gerber + 钻孔（打包 zip）、BOM、坐标文件，以及最终渲染图。
# 只在 DRC 全绿之后运行（test_drc.py）。输出目录 fab/ 每次先清空。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KC=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
PCB="$ROOT/plush-toy-mainboard.kicad_pcb"
SCH="$ROOT/plush-toy-mainboard.kicad_sch"
FAB="$ROOT/fab"
rm -rf "$FAB" && mkdir -p "$FAB/gerber" "$ROOT/renders"

# 四层铜 + 双面阻焊 + 正面丝印与钢网（单面贴片，底面无丝印无钢网）+ 板框
$KC pcb export gerbers \
    --layers "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Mask,B.Mask,F.SilkS,F.Paste,Edge.Cuts" \
    --subtract-soldermask --check-zones \
    -o "$FAB/gerber/" "$PCB"
$KC pcb export drill --format excellon --excellon-separate-th --generate-map --map-format gerberx2 \
    -o "$FAB/gerber/" "$PCB"
(cd "$FAB/gerber" && zip -q ../gerber.zip ./*)

# BOM：按取值 + 封装 + LCSC 料号合并，不贴件排除
$KC sch export bom \
    --fields "Reference,Value,Footprint,LCSC,\${QUANTITY}" \
    --labels "Designator,Comment,Footprint,LCSC Part #,Quantity" \
    --group-by "Value,Footprint,LCSC" --exclude-dnp \
    -o "$FAB/bom.csv" "$SCH"

# 坐标文件：只有正面，单位 mm
$KC pcb export pos --format csv --units mm --side front --exclude-dnp -o "$FAB/positions.csv" "$PCB"

$KC pcb render --side top --width 1600 --height 1100 -o "$ROOT/renders/final_top.png" "$PCB"
$KC pcb render --side bottom --width 1600 --height 1100 -o "$ROOT/renders/final_bottom.png" "$PCB"
echo "制造文件：$FAB"
