#pragma once

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

extern const IrisTexture kIrisHuman;
extern const IrisTexture kIrisDragon;
