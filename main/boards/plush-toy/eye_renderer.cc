#include "eye_renderer.h"

#include <math.h>

// 几何参数取自已归档的交互式原型（spec §8，prototype/eye-renderer 分支）。
// 屏心 (120,120)，巩膜半径 100，虹膜 44，瞳孔 21×scale。
bool EyeRenderer::swap_rb_ = false;

namespace {

constexpr int kC = EyeRenderer::kSize / 2;   // 120
constexpr float kScleraR = 100.0f;
constexpr float kIrisR   = 44.0f;
constexpr float kPupilR  = 21.0f;
constexpr float kPupilDx = 36.0f;            // pupil_x = 1.0 时的像素偏移
constexpr float kPupilDy = 30.0f;
constexpr float kLidHalfW = 106.0f;
constexpr float kLidHalfH = 100.0f;

inline uint16_t Rgb565(int r, int g, int b) {
    if (EyeRenderer::swap_rb()) { const int t = r; r = b; b = t; }
    return (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}

// 按比例调暗/调亮 RGB565，用于虹膜的径向渐变
inline uint16_t Shade(uint16_t c, float f) {
    int r = ((c >> 11) & 0x1F) * 255 / 31;
    int g = ((c >> 5) & 0x3F) * 255 / 63;
    int b = (c & 0x1F) * 255 / 31;
    auto cl = [](float v) { return (int)(v < 0 ? 0 : (v > 255 ? 255 : v)); };
    return Rgb565(cl(r * f), cl(g * f), cl(b * f));
}

inline float Clamp01(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }

// 像素是否落在睁开的眼缝内。
// 上睑是一条带倾角的直线，下睑是一条抛物线（curve>0 时向上拱起成弯月笑眼）。
// side 是 lid_tilt 镜像规则的唯一落点：左眼 +1、右眼 -1。
inline bool InsideLids(float x, float y, const EyeState& s, int side) {
    const float open = Clamp01(s.openness);
    if (open <= 0.0f) return false;

    const float tilt = (s.lid_tilt * (float)side) * (float)M_PI / 180.0f;
    const float top = (float)kC - open * kLidHalfH;
    const float bot = (float)kC + open * kLidHalfH;
    const float bow = s.curve * kLidHalfH * 0.95f;
    const float dx = x - (float)kC;

    // 上睑
    if (y < top + tanf(tilt) * dx) return false;

    // 下睑：顶点比 bot 高 bow，两端回落到 bot
    const float u = dx / (kLidHalfW * 1.5f);
    const float lower = bot - bow * (1.0f - u * u);
    if (y > lower) return false;

    return true;
}

}  // namespace

void EyeRenderer::Render(uint16_t* out, const EyeState& s, int side, DirtyRect r) {
    const float px = (float)kC + s.pupil_x * kPupilDx;
    const float py = (float)kC + s.pupil_y * kPupilDy;
    const float pupil_r = kPupilR * s.pupil_scale;
    const float iris_r = kIrisR * (0.9f + 0.1f * s.pupil_scale);

    for (int yy = 0; yy < r.h; ++yy) {
        const int y = r.y + yy;
        for (int xx = 0; xx < r.w; ++xx) {
            const int x = r.x + xx;
            uint16_t c = 0x0000;

            const float dxs = (float)(x - kC), dys = (float)(y - kC);
            const float ds = sqrtf(dxs * dxs + dys * dys);

            // 圆屏之外、巩膜之外、眼睑之外，一律黑
            if (ds <= (float)kC && ds <= kScleraR &&
                InsideLids((float)x, (float)y, s, side)) {

                // 巩膜：中心略亮的径向渐变
                const float t = ds / kScleraR;
                const int v = (int)(255.0f - 44.0f * t);
                c = Rgb565(v, v, (int)(v * 0.98f));

                const float dxp = (float)x - px, dyp = (float)y - py;
                const float dp = sqrtf(dxp * dxp + dyp * dyp);

                // 虹膜
                if (dp <= iris_r) {
                    const float k = dp / iris_r;
                    c = Shade(s.iris_color, 1.35f - 0.93f * k);
                }
                // 瞳孔
                if (dp <= pupil_r) {
                    c = Rgb565(7, 9, 12);
                }
                // 主高光：偏左上，是眼睛显得"活"的关键
                const float hx = (float)x - (px - 15.0f);
                const float hy = (float)y - (py - 17.0f);
                if (hx * hx + hy * hy <= 9.5f * 9.5f) {
                    c = 0xFFFF;
                }
            }

            out[yy * r.w + xx] = c;
        }
    }
}

DirtyRect EyeRenderer::ComputeDirty(const EyeState& a, const EyeState& b) {
    auto ne = [](float x, float y) { return fabsf(x - y) > 1e-4f; };

    const bool lids_changed =
        ne(a.openness, b.openness) || ne(a.lid_tilt, b.lid_tilt) || ne(a.curve, b.curve);
    const bool pupil_changed =
        ne(a.pupil_x, b.pupil_x) || ne(a.pupil_y, b.pupil_y) ||
        ne(a.pupil_scale, b.pupil_scale) || a.iris_color != b.iris_color;

    if (!lids_changed && !pupil_changed) return DirtyRect{0, 0, 0, 0};

    if (lids_changed) {
        // 眼睑扫过整个眼球，退化为外接矩形
        int x0 = kC - (int)kScleraR - 2;
        int y0 = kC - (int)kLidHalfH - 2;
        int x1 = kC + (int)kScleraR + 2;
        int y1 = kC + (int)kLidHalfH + 2;
        if (x0 < 0) x0 = 0;
        if (y0 < 0) y0 = 0;
        if (x1 > kSize) x1 = kSize;
        if (y1 > kSize) y1 = kSize;
        return DirtyRect{x0, y0, x1 - x0, y1 - y0};
    }

    // 仅瞳孔/虹膜变化：取两帧虹膜圆的并集，加高光偏移与余量
    const float rad = kIrisR * 1.1f + 26.0f;
    const float ax = kC + a.pupil_x * kPupilDx, ay = kC + a.pupil_y * kPupilDy;
    const float bx = kC + b.pupil_x * kPupilDx, by = kC + b.pupil_y * kPupilDy;
    int x0 = (int)floorf(fminf(ax, bx) - rad);
    int y0 = (int)floorf(fminf(ay, by) - rad);
    int x1 = (int)ceilf(fmaxf(ax, bx) + rad);
    int y1 = (int)ceilf(fmaxf(ay, by) + rad);
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > kSize) x1 = kSize;
    if (y1 > kSize) y1 = kSize;
    return DirtyRect{x0, y0, x1 - x0, y1 - y0};
}
