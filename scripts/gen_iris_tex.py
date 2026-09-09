#!/usr/bin/env python3
"""把 Adafruit Uncanny_Eyes 的 iris[][] 极坐标条带导出成本仓库的 C++ 源。

上游数组是 iris[IRIS_MAP_HEIGHT][IRIS_MAP_WIDTH]：行是半径（0 = 瞳孔中心，
末行 = 虹膜外缘），列是角度（覆盖 360°）。角度方向统一重采样到 256 列 ——
虹膜直径 88px、周长约 276px，256 已经够密，上游 512 是过采样。
"""
import re
import sys
import urllib.request

BASE = "https://raw.githubusercontent.com/adafruit/Uncanny_Eyes/master/uncannyEyes/graphics/"
TARGET_W = 256


def fetch(name):
    with urllib.request.urlopen(BASE + name + ".h") as f:
        return f.read().decode("utf-8", "replace")


def parse_iris(text):
    w = int(re.search(r"#define IRIS_MAP_WIDTH\s+(\d+)", text).group(1))
    h = int(re.search(r"#define IRIS_MAP_HEIGHT\s+(\d+)", text).group(1))
    start = text.index("iris[IRIS_MAP_HEIGHT][IRIS_MAP_WIDTH]")
    body = text[text.index("{", start) + 1: text.index("};", start)]
    vals = [int(v, 16) for v in re.findall(r"0[xX]([0-9a-fA-F]{1,4})", body)]
    if len(vals) != w * h:
        sys.exit(f"数量不符: 期望 {w*h}, 实到 {len(vals)}")
    return w, h, [vals[y * w:(y + 1) * w] for y in range(h)]


def unpack(c):
    return ((c >> 11) & 0x1F) * 255 // 31, ((c >> 5) & 0x3F) * 255 // 63, (c & 0x1F) * 255 // 31


def pack(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def resample_row(row, target):
    """按等分区间取平均，避免直接抽样丢掉细纹。"""
    n = len(row)
    if n == target:
        return row
    out = []
    for i in range(target):
        lo, hi = i * n // target, max(i * n // target + 1, (i + 1) * n // target)
        rs = gs = bs = 0
        for c in row[lo:hi]:
            r, g, b = unpack(c)
            rs += r; gs += g; bs += b
        k = hi - lo
        out.append(pack(rs // k, gs // k, bs // k))
    return out


def luma_profile(rows):
    out = []
    for row in rows:
        s = 0
        for c in row:
            r, g, b = unpack(c)
            s += (r * 30 + g * 59 + b * 11) // 100
        out.append(s // len(row))
    return out


DESIGNS = [("defaultEye", "kIrisHuman", "human"), ("dragonEye", "kIrisDragon", "dragon")]

parsed = []
for src, sym, short in DESIGNS:
    text = fetch(src)
    w, h, rows = parse_iris(text)
    rows = [resample_row(r, TARGET_W) for r in rows]
    prof = luma_profile(rows)
    print(f"{src}: {w}x{h} -> {TARGET_W}x{h}, 亮度剖面 "
          f"中心 {prof[0]} 峰值 {max(prof)} 外缘 {prof[-1]}", file=sys.stderr)
    parsed.append((sym, short, TARGET_W, h, rows))

with open("eye_iris_tex.h", "w") as f:
    f.write("""#pragma once

#include <stdint.h>

// 虹膜极坐标纹理，来自 Adafruit Uncanny_Eyes（MIT，Phil Burgess / Paint Your
// Dragon）。github.com/adafruit/Uncanny_Eyes，由 scripts/gen_iris_tex.py 生成。
//
// data 按 [radius][angle] 排列：radius 行 0 是瞳孔中心、末行是虹膜外缘，
// angle 列覆盖 360°。角度方向已统一重采样到 256 列。
// 亮度从中心的暗、经中段最亮、到外缘再次转暗 —— 角膜缘环是纹理自带的，
// 用纹理主题时不必再叠程序化的那一圈。
struct IrisTexture {
    const uint16_t* data;
    uint16_t angles;   // 列数，覆盖 360°
    uint16_t radii;    // 行数，0 = 中心，末行 = 虹膜外缘
};

""")
    for sym, _short, _w, _h, _rows in parsed:
        f.write(f"extern const IrisTexture {sym};\n")

with open("eye_iris_tex.cc", "w") as f:
    f.write('#include "eye_iris_tex.h"\n\n')
    f.write("// 本文件由 scripts/gen_iris_tex.py 生成，请勿手改。\n\n")
    for sym, short, w, h, rows in parsed:
        f.write(f"static const uint16_t k{short.capitalize()}Data[{h} * {w}] = {{\n")
        for row in rows:
            for i in range(0, w, 12):
                f.write("    " + " ".join(f"0x{c:04X}," for c in row[i:i + 12]) + "\n")
        f.write("};\n\n")
        f.write(f"const IrisTexture {sym} = {{k{short.capitalize()}Data, {w}, {h}}};\n\n")
print("生成完毕: eye_iris_tex.h / eye_iris_tex.cc", file=sys.stderr)
