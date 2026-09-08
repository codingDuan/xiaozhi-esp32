#pragma once

#include <stdint.h>

// 参数化眼球状态。全部表情由这 7 个字段描述，情绪之间用线性插值过渡。
//
// 造型与取值范围经交互式原型确定（2026-09-06，见 spec §2.2.1）。
// curve 是原型阶段新增的第 6 个字段 —— 弯月笑眼需要下眼睑向上拱起，
// 仅靠 openness 和 lid_tilt 表达不出来：降低 openness 只会得到一条横缝。
struct EyeState {
    float openness    = 0.94f;    // 0 全闭 ~ 1 全睁
    float pupil_x     = 0.0f;     // -1 ~ 1，注视方向水平分量
    float pupil_y     = 0.0f;     // -1 ~ 1，注视方向垂直分量
    float pupil_scale = 1.0f;     // 0.5 ~ 1.6
    float lid_tilt    = 0.0f;     // 上眼睑倾角（度），左眼取值；右眼由 side 取负
    float curve       = 0.0f;     // 下眼睑曲率 -1 下垂 ~ +1 上拱
    uint16_t iris_color = 0x363E; // RGB565，#35C7F5 青蓝
};

struct DirtyRect {
    int x = 0, y = 0, w = 0, h = 0;
};

// 纯计算渲染器：输入参数，输出像素。不接触任何硬件，可在开发机上编译测试。
//
// 双眼不对称偏移刻意不放在这里（放在 EyeDisplay），以保证本类可被精确镜像
// 测试 —— 「左眼 +t 与右眼 -t 应逐像素完全相等」是 lid_tilt 镜像规则唯一的
// 自动化防线。
class EyeRenderer {
public:
    static constexpr int kSize = 240;

    // out 指向 r.w * r.h 个 RGB565 像素，行连续（stride == r.w）
    // side: +1 左眼，-1 右眼（仅影响 lid_tilt 的符号）
    static void Render(uint16_t* out, const EyeState& s, int side, DirtyRect r);

    static DirtyRect FullRect() { return DirtyRect{0, 0, kSize, kSize}; }
};
