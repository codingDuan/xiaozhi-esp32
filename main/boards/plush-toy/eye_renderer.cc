#include "eye_renderer.h"
#include "eye_iris_tex.h"
#include "eye_theme.h"

#include <math.h>

// 几何参数取自已归档的交互式原型（spec §8，prototype/eye-renderer 分支）。
// 屏心 (120,120)，巩膜半径 100，虹膜 44，瞳孔 21×scale。
//
// 三处观感改动借鉴 Adafruit Uncanny Eyes（github.com/adafruit/Uncanny_Eyes）：
// 边界抗锯齿、角膜缘环、羽化高光。它们靠预烘焙的虹膜纹理贴图拿到这些效果，
// 我们没有那几十 KB flash 预算，因此改成按有符号距离现算，观感等价。
bool EyeRenderer::swap_rb_ = false;

namespace {

constexpr int kC = EyeRenderer::kSize / 2;   // 120
constexpr float kScleraR = 100.0f;
constexpr float kIrisR   = 44.0f;
constexpr float kPupilR  = 21.0f;
constexpr float kPupilDx = 36.0f;            // pupil_x = 1.0 时的像素偏移
constexpr float kPupilDy = 30.0f;
// 眼裂满开时的半高。刻意小于巩膜半径：等于巩膜半径时上下睑几乎切不到东西，
// 轮廓退化成整个巩膜圆，看着像圆角方块而不像眼睛。
constexpr float kLidHalfH = 82.0f;

// 角膜缘环：虹膜最外 18% 压暗成一圈深色边。真实虹膜都有这一圈，
// 缺了它虹膜会像一块贴上去的色板，是原来"没美感"的主因之一。
constexpr float kLimbalStart = 0.82f;
constexpr float kLimbalDark  = 0.26f;        // 环最深处相对虹膜外圈色的亮度系数

// 高光。主高光偏左上，是眼睛显得"活"的关键；副高光在瞳孔右下，
// 强度只有三成，用来暗示球面而不抢主高光。
constexpr float kHi1R = 9.5f, kHi1Dx = -15.0f, kHi1Dy = -17.0f;
constexpr float kHi2R = 5.5f, kHi2Dx = 13.0f, kHi2Dy = 14.0f;
constexpr float kHi2Alpha = 0.32f;
constexpr float kHiSoft = 3.0f;              // 高光边缘羽化宽度（像素）

// 工作色：0~255 的线性 RGB，未经红蓝互换。所有混色都在这里做，末尾只 Pack 一次。
// 不能在 RGB565 上链式混色 —— swap_rb 会被叠加成偶数次而自我抵消。
struct Rgb {
    float r, g, b;
};

inline float Clamp01(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }

inline Rgb Unpack(uint16_t c) {
    return Rgb{(float)(((c >> 11) & 0x1F) * 255 / 31), (float)(((c >> 5) & 0x3F) * 255 / 63),
               (float)((c & 0x1F) * 255 / 31)};
}

inline Rgb Mix(const Rgb& a, const Rgb& b, float t) {
    return Rgb{a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t};
}

inline Rgb Scale(const Rgb& a, float k) { return Rgb{a.r * k, a.g * k, a.b * k}; }

// 4×4 有序抖动矩阵。巩膜是 255→211 的宽缓渐变，落到 RGB565 只剩五六个红蓝台阶，
// 会在眼白上摊出一圈圈同心色带。抖动把量化误差散成噪点，色带就看不见了。
constexpr float kBayer[16] = {0,  8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5};

inline uint16_t Pack(const Rgb& c, int x, int y) {
    // 每通道的量化步长：红蓝 5 位是 8，绿 6 位是 4
    const float d = (kBayer[(y & 3) * 4 + (x & 3)] + 0.5f) / 16.0f - 0.5f;
    int r = (int)(c.r + d * 8.0f + 0.5f);
    int g = (int)(c.g + d * 4.0f + 0.5f);
    int b = (int)(c.b + d * 8.0f + 0.5f);
    r = r < 0 ? 0 : (r > 255 ? 255 : r);
    g = g < 0 ? 0 : (g > 255 ? 255 : g);
    b = b < 0 ? 0 : (b > 255 ? 255 : b);
    if (EyeRenderer::swap_rb()) { const int t = r; r = b; b = t; }
    return (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}

// 抗锯齿的唯一入口：把「到边界的有符号距离（内正外负）」换成 1 像素宽的覆盖率斜坡。
// 原来所有边界都是二值判断，240 圆屏上锯齿肉眼可见。
inline float Cov(float signed_dist) { return Clamp01(signed_dist + 0.5f); }

// 羽化圆盘，用于高光。硬边高光看着像贴纸。
inline float SoftDisc(float dx, float dy, float radius) {
    const float d2 = dx * dx + dy * dy;
    if (d2 >= radius * radius) return 0.0f;
    return Clamp01((radius - sqrtf(d2)) / kHiSoft);
}

// 眼睑轮廓表。上下睑共用一条归一化曲线 p(x) = (1-u²)^E，u = (x-120)/kApertureW，
// 眼裂高度按列取 open*kLidHalfH*p(x)。指数小于 1 使顶部平缓、眼角收尖，得到杏仁形。
//
// 原来上睑是水平直线、下睑是抛物线，两条线都比巩膜宽，于是在圆形巩膜上切出上下两条
// 弦，睁眼时轮廓是个八边形。改成按列的轮廓后，眼角处 p(x) 已降到巩膜以下，
// 两侧交回巩膜圆弧，上下则是平缓的杏仁弧，八边形消失。
//
// 取 kApertureW > 巩膜半径 100 是刻意的：眼角要落在巩膜之外，否则眼裂会在
// 巩膜边缘内部收口，看着像眯着一条缝。
constexpr float kApertureW = 116.0f;
constexpr float kApertureE = 0.72f;

// curve 的上拱弧要比眼裂轮廓宽得多。共用一条轮廓会让下睑和上睑等比例收窄，
// 弯月笑眼就退化成一条等宽带子；这里单独给一条平缓的宽抛物线。
constexpr float kBowW = 168.0f;

// 每列一组 {轮廓值, 轮廓斜率}。斜率只用于抗锯齿的法向归一化 ——
// 少了它，眼角附近眼睑近乎竖直，1 像素的覆盖率斜坡会被拉成一条明显的灰边。
struct LidProfile {
    float p[EyeRenderer::kSize];
    float dp[EyeRenderer::kSize];
    float b[EyeRenderer::kSize];    // curve 的宽上拱弧
    float db[EyeRenderer::kSize];

    LidProfile() {
        for (int x = 0; x < EyeRenderer::kSize; ++x) {
            const float dx = (float)x - (float)kC;

            const float u = dx / kApertureW;
            const float q = 1.0f - u * u;
            if (q <= 0.0f) {
                p[x] = 0.0f;
                dp[x] = 0.0f;
            } else {
                p[x] = powf(q, kApertureE);
                dp[x] = kApertureE * powf(q, kApertureE - 1.0f) * (-2.0f * u) / kApertureW;
            }

            const float v = dx / kBowW;
            const float r = 1.0f - v * v;
            b[x] = r > 0.0f ? r : 0.0f;
            db[x] = r > 0.0f ? (-2.0f * dx / (kBowW * kBowW)) : 0.0f;
        }
    }
};

const LidProfile& Profile() {
    static const LidProfile kProfile;
    return kProfile;
}

// 眼睑几何。tanf 只跟 lid_tilt 有关，每帧算一次而不是每像素。
struct LidGeom {
    bool closed;
    float amp;         // 眼裂半高，上下睑共用
    float bow;         // curve 的上拱量，只作用于下睑
    float slope_u;     // lid_tilt 造成的线性剪切
};

LidGeom MakeLidGeom(const EyeState& s, int side) {
    LidGeom g{};
    const float open = Clamp01(s.openness);
    if (open <= 0.0f) {
        g.closed = true;
        return g;
    }
    // side 是 lid_tilt 镜像规则的唯一落点：左眼 +1、右眼 -1。
    const float tilt = (s.lid_tilt * (float)side) * (float)M_PI / 180.0f;
    g.closed = false;
    g.amp = open * kLidHalfH;
    g.bow = s.curve * kLidHalfH * 0.95f;
    g.slope_u = tanf(tilt);
    return g;
}

// 像素落在睁开的眼缝内的覆盖率。上下睑都是轮廓表的缩放，上睑另加 lid_tilt 剪切。
inline float LidCoverage(int x, float y, const LidGeom& g, const LidProfile& prof) {
    if (g.closed) return 0.0f;
    const float p = prof.p[x];
    const float dp = prof.dp[x];
    const float dx = (float)x - (float)kC;

    // 上睑。倾角剪切也乘上轮廓，让它在眼角收敛到 0：
    // 直接线性剪切会在外眼角戳出一个尖角，把「难过」画成一副凶相。
    const float y_up = (float)kC - g.amp * p + g.slope_u * dx * p;
    const float k_up = -g.amp * dp + g.slope_u * (p + dx * dp);
    const float raw_up = y - y_up;

    // 下睑：眼裂轮廓再减去 curve 的宽上拱弧
    const float y_lo = (float)kC + g.amp * p - g.bow * prof.b[x];
    const float k_lo = g.amp * dp - g.bow * prof.db[x];
    const float raw_lo = y_lo - y;

    // raw 是竖直距离，要除以 sqrt(1+k²) 才是到睑缘的垂距。但抗锯齿只在边缘
    // 一像素内起作用，用 sqrt(1+k²) ≤ 1+|k| 先做保守夹逼，绝大多数像素在这里
    // 就判完了，省掉两次开方。
    const float bu = 0.5f * (1.0f + fabsf(k_up));
    const float bl = 0.5f * (1.0f + fabsf(k_lo));
    if (raw_up > bu && raw_lo > bl) return 1.0f;
    if (raw_up < -bu || raw_lo < -bl) return 0.0f;

    const float d_upper = raw_up / sqrtf(1.0f + k_up * k_up);
    const float d_lower = raw_lo / sqrtf(1.0f + k_lo * k_lo);
    return Cov(d_upper < d_lower ? d_upper : d_lower);
}

// 瞳孔覆盖率。椭圆到边界的距离用 f/|∇f| 近似；圆的情况下该式恰好精确。
inline float PupilCoverage(float dx, float dy, float radius, PupilShape shape) {
    float a = radius, b = radius;
    switch (shape) {
        case PupilShape::kVerticalSlit:   a = radius * 0.24f; b = radius * 1.22f; break;
        case PupilShape::kHorizontalSlit: a = radius * 1.22f; b = radius * 0.24f; break;
        case PupilShape::kRound: break;
    }
    if (a <= 0.0f || b <= 0.0f) return 0.0f;

    const float aa = a * a, bb = b * b;
    const float f = (dx * dx) / aa + (dy * dy) / bb - 1.0f;
    if (f > 0.5f) return 0.0f;                       // 明显在外，省掉开方

    const float gx = 2.0f * dx / aa, gy = 2.0f * dy / bb;
    const float gm = sqrtf(gx * gx + gy * gy);
    if (gm < 1e-6f) return 1.0f;                     // 正中心
    return Cov(-f / gm);
}

}  // namespace

void EyeRenderer::Render(uint16_t* out, const EyeState& s, const EyeTheme& theme, int side,
                         DirtyRect r) {
    const float px = (float)kC + s.pupil_x * kPupilDx;
    const float py = (float)kC + s.pupil_y * kPupilDy;
    const float pupil_r = kPupilR * s.pupil_scale;
    const float iris_r = kIrisR * (0.9f + 0.1f * s.pupil_scale);

    const LidGeom lids = MakeLidGeom(s, side);
    const LidProfile& prof = Profile();
    const IrisTexture* tex = theme.iris_tex;
    const Rgb iris_in = Unpack(theme.iris_inner);
    const Rgb iris_out = Unpack(theme.iris_outer);
    const Rgb limbal = Scale(iris_out, kLimbalDark);
    const Rgb pupil_c = Rgb{7.0f, 9.0f, 12.0f};
    const Rgb white = Rgb{255.0f, 255.0f, 255.0f};
    const Rgb black = Rgb{0.0f, 0.0f, 0.0f};

    const float hi1x = px + kHi1Dx, hi1y = py + kHi1Dy;
    const float hi2x = px + kHi2Dx, hi2y = py + kHi2Dy;

    for (int yy = 0; yy < r.h; ++yy) {
        const int y = r.y + yy;
        for (int xx = 0; xx < r.w; ++xx) {
            const int x = r.x + xx;

            const float dxs = (float)(x - kC), dys = (float)(y - kC);
            const float ds = sqrtf(dxs * dxs + dys * dys);

            // 圆屏边缘、巩膜外沿、眼睑三道边界合成一个覆盖率
            const float edge = ((float)kC - ds) < (kScleraR - ds) ? ((float)kC - ds)
                                                                  : (kScleraR - ds);
            const float alpha = Cov(edge) * LidCoverage(x, (float)y, lids, prof);
            if (alpha <= 0.0f) {
                out[yy * r.w + xx] = 0x0000;
                continue;
            }

            // 巩膜：中心略亮的径向渐变。无巩膜主题则以主题虹膜色铺满眼白区域。
            const float t = Clamp01(ds / kScleraR);
            Rgb c;
            if (theme.sclera == ScleraStyle::kLight) {
                const float v = 255.0f - 44.0f * t;
                c = Rgb{v, v, v * 0.98f};
            } else if (theme.sclera == ScleraStyle::kDark) {
                const float v = 39.0f - 20.0f * t;
                c = Rgb{v * 0.5f, v, v + 14.0f};
            } else {
                c = Mix(iris_in, iris_out, t);
            }

            const float dxp = (float)x - px, dyp = (float)y - py;
            const float dp2 = dxp * dxp + dyp * dyp;

            // 虹膜，外沿压一圈角膜缘环。
            // 巩膜区占了大部分像素，那里根本用不到 dp，先用平方比一次省掉开方。
            const float iris_edge = iris_r + 1.0f;
            if (dp2 <= iris_edge * iris_edge) {
                const float dp = sqrtf(dp2);
                const float ia = Cov(iris_r - dp);
                const float k = Clamp01(dp / iris_r);
                Rgb ic;
                if (tex != nullptr) {
                    // 极坐标采样。atan2f 只在虹膜盘内算，那约占脏矩形的一成半。
                    // 纹理外缘自带角膜缘环，不再叠程序化的那一圈。
                    float a = atan2f(dyp, dxp) * (0.5f / (float)M_PI);
                    if (a < 0.0f) a += 1.0f;
                    int ai = (int)(a * (float)tex->angles);
                    if (ai >= tex->angles) ai = tex->angles - 1;
                    int ri = (int)(k * (float)(tex->radii - 1) + 0.5f);
                    if (ri >= tex->radii) ri = tex->radii - 1;
                    ic = Unpack(tex->data[(size_t)ri * tex->angles + ai]);
                } else {
                    ic = Mix(iris_in, iris_out, k);
                    const float lr = Clamp01((k - kLimbalStart) / (1.0f - kLimbalStart));
                    ic = Mix(ic, limbal, lr * lr * (3.0f - 2.0f * lr));   // smoothstep
                }
                c = Mix(c, ic, ia);
            }

            // 瞳孔
            const float pa = PupilCoverage(dxp, dyp, pupil_r, theme.pupil);
            if (pa > 0.0f) c = Mix(c, pupil_c, pa);

            // 高光
            const float h1 = SoftDisc((float)x - hi1x, (float)y - hi1y, kHi1R);
            if (h1 > 0.0f) c = Mix(c, white, h1);
            const float h2 = SoftDisc((float)x - hi2x, (float)y - hi2y, kHi2R);
            if (h2 > 0.0f) c = Mix(c, white, h2 * kHi2Alpha);

            if (alpha < 1.0f) c = Mix(black, c, alpha);
            out[yy * r.w + xx] = Pack(c, x, y);
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
        // 眼睑扫过整个眼球，退化为巩膜外接矩形。
        // 纵向必须按巩膜半径而不是 kLidHalfH：后者更小，会漏掉眼睑让开后露出的那圈巩膜。
        int x0 = kC - (int)kScleraR - 2;
        int y0 = kC - (int)kScleraR - 2;
        int x1 = kC + (int)kScleraR + 2;
        int y1 = kC + (int)kScleraR + 2;
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
