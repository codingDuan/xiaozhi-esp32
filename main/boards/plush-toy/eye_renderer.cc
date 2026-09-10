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

// 日系画法的虹膜远大于写实比例，瞳孔反而相对更小 —— 这个占比本身就是
// 「动漫眼」最直观的特征，只改配色不改几何做不出来。
// 虹膜 62 + 注视偏移 30 = 92，超过眼裂半高 82，睁大眼向上看时虹膜上缘会被
// 上睑切掉一截。那是日系画法的常态，不是 bug。
constexpr float kAnimeIrisR  = 62.0f;
constexpr float kAnimePupilR = 22.0f;
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

// ---- 日系画法参数 ----
// 配方来自几份日系眼睛画法教程，五件事缺一不可：上睑投影带、下缘反射月牙、
// 放射纤维、加粗睫毛线、按虹膜比例放大的高光。全部现算，不占 flash。
//
// 高光按虹膜半径的比例给，虹膜一放大高光就跟着放大 —— 写实主题那种固定
// 9.5px 的小圆点摊到 62px 虹膜上会缩成一颗水珠。
constexpr float kAnimeHi1K = 0.27f, kAnimeHi1DxK = -0.34f, kAnimeHi1DyK = -0.36f;
constexpr float kAnimeHi2K = 0.15f, kAnimeHi2DxK = 0.42f, kAnimeHi2DyK = 0.46f;
constexpr float kAnimeHi2Alpha = 0.70f;
constexpr float kAnimeHiSoft = 2.0f;         // 日系高光边缘比写实硬

// 上睑投影带。ny 是相对瞳孔中心、按虹膜半径归一化的纵坐标。
constexpr float kShadowY = -0.05f, kShadowSoft = 0.42f, kShadowDark = 0.44f;

// 下缘反射月牙：正对投影带的一段亮弧，贴着虹膜外圈。
constexpr float kCrescentR = 0.72f, kCrescentW = 0.26f;
constexpr float kCrescentY = 0.18f, kCrescentSoft = 0.35f, kCrescentAmp = 0.85f;

// 放射纤维。24 条摊在 62px 半径的虹膜上约每 16px 一条，肉眼刚好分得清。
// 包络取 4k(1-k)，两端归零，免得纤维戳进瞳孔或穿过角膜缘环。
constexpr float kFiberN = 24.0f, kFiberAmp = 0.07f;

// 角膜缘环：比写实主题起得更早、压得更深，这是日系虹膜"描边感"的来源。
constexpr float kAnimeLimbalStart = 0.76f, kAnimeLimbalDark = 0.20f;

// 睫毛线：上睑内侧的一条深色粗边，日系与写实最直观的区别。
// 线宽还要卡在睑缝高度的 kLashSlitCap 以内，否则眨眼眨到一半时
// 上下睑各画一半线宽，整条缝会被填成纯黑，看着像眼睛直接消失。
constexpr float kLashW = 10.0f, kLashSlitCap = 0.22f, kLashSharp = 6.0f;

// 上睑投在眼白上的柔和阴影。虹膜自带更深的投影带，这里只补虹膜之外的部分。
constexpr float kLidShadowW = 10.0f, kLidShadowDark = 0.10f;

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
inline float SoftDisc(float dx, float dy, float radius, float soft) {
    const float d2 = dx * dx + dy * dy;
    if (d2 >= radius * radius) return 0.0f;
    return Clamp01((radius - sqrtf(d2)) / soft);
}

inline float Smoothstep01(float t) { return t * t * (3.0f - 2.0f * t); }

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

// 一次采样同时给出三件事：覆盖率、到上睑缘的垂距、该列的睑缝高度。
// 后两项只有日系画法用（睫毛线和睑影），但它们和覆盖率共用同一套几何，
// 拆成两个函数会把 powf 查表和剪切计算做两遍。
struct LidSample {
    float cov;
    float d_upper;   // 睑内为正。离上睑较远时给一个哨兵大值，省掉开方
    float slit;      // 该列上下睑缘之间的高度
};

// 睫毛线宽 11、睑影宽 26，超过这个距离的像素两者都用不上，不必开方。
constexpr float kUpperBand = 48.0f;

// 像素落在睁开的眼缝内的覆盖率。上下睑都是轮廓表的缩放，上睑另加 lid_tilt 剪切。
inline LidSample SampleLids(int x, float y, const LidGeom& g, const LidProfile& prof) {
    LidSample out{0.0f, 1e9f, 0.0f};
    if (g.closed) return out;
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

    out.slit = y_lo - y_up;

    // raw 是竖直距离，要除以 sqrt(1+k²) 才是到睑缘的垂距。抗锯齿只在边缘一像素
    // 内起作用，用 sqrt(1+k²) ≤ 1+|k| 先做保守夹逼；日系的睫毛线要往里吃几十像素，
    // 所以上睑那一侧的开方门槛放宽到 kUpperBand，仍能替绝大多数像素省掉开方。
    const float bu = 0.5f * (1.0f + fabsf(k_up));
    const float bl = 0.5f * (1.0f + fabsf(k_lo));

    float d_upper = 1e9f, d_lower = 1e9f;
    if (raw_up < kUpperBand) d_upper = raw_up / sqrtf(1.0f + k_up * k_up);
    if (raw_lo < kUpperBand) d_lower = raw_lo / sqrtf(1.0f + k_lo * k_lo);
    out.d_upper = d_upper;

    if (raw_up > bu && raw_lo > bl) {
        out.cov = 1.0f;
        return out;
    }
    if (raw_up < -bu || raw_lo < -bl) return out;   // cov 已是 0

    // 走到这里两侧 raw 都落在 ±b 内，因而都小于 kUpperBand，垂距一定已经算过
    out.cov = Cov(d_upper < d_lower ? d_upper : d_lower);
    return out;
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

// 日系虹膜着色。nx/ny 是相对瞳孔中心、按虹膜半径归一化的坐标，k = 到中心的
// 归一化距离，angle 是极角（弧度）。五道工序按顺序叠：
// 基础渐变 → 放射纤维 → 上睑投影带 → 角膜缘环 → 下缘反射月牙。
//
// 月牙必须排在角膜缘环之后。它本来就画在虹膜外圈上，排在环之前会被环压掉，
// 而"深色描边的底部透出一道亮光"正是日系虹膜的招牌观感。
inline Rgb AnimeIris(const Rgb& inner, const Rgb& outer, float ny, float k, float angle) {
    Rgb c = Mix(inner, outer, powf(k, 1.15f));

    const float env = 4.0f * k * (1.0f - k);
    c = Scale(c, 1.0f + kFiberAmp * sinf(angle * kFiberN) * env);

    const float sh = Smoothstep01(Clamp01((kShadowY - ny) / kShadowSoft));
    c = Scale(c, 1.0f - kShadowDark * sh);

    const float lr = Smoothstep01(Clamp01((k - kAnimeLimbalStart) / (1.0f - kAnimeLimbalStart)));
    c = Mix(c, Scale(outer, kAnimeLimbalDark), lr);

    const float rb = Clamp01(1.0f - fabsf(k - kCrescentR) / kCrescentW);
    const float ab = Clamp01((ny - kCrescentY) / kCrescentSoft);
    if (rb > 0.0f && ab > 0.0f) {
        const Rgb glow = Mix(inner, Rgb{255.0f, 255.0f, 255.0f}, 0.55f);
        c = Mix(c, glow, kCrescentAmp * Smoothstep01(rb) * Smoothstep01(ab));
    }
    return c;
}

}  // namespace

void EyeRenderer::Render(uint16_t* out, const EyeState& s, const EyeTheme& theme, int side,
                         DirtyRect r) {
    const bool anime = theme.iris == IrisStyle::kAnime;

    const float px = (float)kC + s.pupil_x * kPupilDx;
    const float py = (float)kC + s.pupil_y * kPupilDy;
    const float pupil_r = (anime ? kAnimePupilR : kPupilR) * s.pupil_scale;
    const float iris_r = (anime ? kAnimeIrisR : kIrisR) * (0.9f + 0.1f * s.pupil_scale);

    const LidGeom lids = MakeLidGeom(s, side);
    const LidProfile& prof = Profile();
    const IrisTexture* tex = theme.iris_tex;
    const Rgb iris_in = Unpack(theme.iris_inner);
    const Rgb iris_out = Unpack(theme.iris_outer);
    const Rgb limbal = Scale(iris_out, kLimbalDark);
    const Rgb pupil_c = Rgb{7.0f, 9.0f, 12.0f};
    const Rgb white = Rgb{255.0f, 255.0f, 255.0f};
    const Rgb black = Rgb{0.0f, 0.0f, 0.0f};
    const Rgb lash_c = Rgb{18.0f, 14.0f, 22.0f};

    // 日系高光按虹膜半径取，写实高光是固定像素尺寸
    const float hi1r = anime ? iris_r * kAnimeHi1K : kHi1R;
    const float hi2r = anime ? iris_r * kAnimeHi2K : kHi2R;
    const float hi2a = anime ? kAnimeHi2Alpha : kHi2Alpha;
    const float hi_soft = anime ? kAnimeHiSoft : kHiSoft;
    const float hi1x = px + (anime ? iris_r * kAnimeHi1DxK : kHi1Dx);
    const float hi1y = py + (anime ? iris_r * kAnimeHi1DyK : kHi1Dy);
    const float hi2x = px + (anime ? iris_r * kAnimeHi2DxK : kHi2Dx);
    const float hi2y = py + (anime ? iris_r * kAnimeHi2DyK : kHi2Dy);

    for (int yy = 0; yy < r.h; ++yy) {
        const int y = r.y + yy;
        for (int xx = 0; xx < r.w; ++xx) {
            const int x = r.x + xx;

            const float dxs = (float)(x - kC), dys = (float)(y - kC);
            const float ds = sqrtf(dxs * dxs + dys * dys);

            // 圆屏边缘、巩膜外沿、眼睑三道边界合成一个覆盖率
            const float edge = ((float)kC - ds) < (kScleraR - ds) ? ((float)kC - ds)
                                                                  : (kScleraR - ds);
            const LidSample lid = SampleLids(x, (float)y, lids, prof);
            const float alpha = Cov(edge) * lid.cov;
            if (alpha <= 0.0f) {
                out[yy * r.w + xx] = 0x0000;
                continue;
            }

            // 巩膜：中心略亮的径向渐变。无巩膜主题则以主题虹膜色铺满眼白区域。
            // 日系眼白比写实平得多，径向压暗量减到三分之一。
            const float t = Clamp01(ds / kScleraR);
            Rgb c;
            if (theme.sclera == ScleraStyle::kLight) {
                const float v = 255.0f - (anime ? 15.0f : 44.0f) * t;
                c = Rgb{v, v, v * 0.98f};
            } else if (theme.sclera == ScleraStyle::kDark) {
                const float v = 39.0f - 20.0f * t;
                c = Rgb{v * 0.5f, v, v + 14.0f};
            } else {
                c = Mix(iris_in, iris_out, t);
            }

            // 上睑投在眼白上的柔和阴影。必须赶在混入虹膜之前 —— 虹膜自带更深的
            // 投影带，两层叠上去虹膜上缘会黑成一块。
            if (anime && lid.d_upper < kLidShadowW) {
                const float sw = Clamp01(1.0f - lid.d_upper / kLidShadowW);
                c = Scale(c, 1.0f - kLidShadowDark * sw * sw);
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
                } else if (anime) {
                    // atan2f 只在虹膜盘内算。日系虹膜大，这一块约占脏矩形三成，
                    // 仍远好过为放射纹理烧掉几十 KB flash。
                    ic = AnimeIris(iris_in, iris_out, dyp / iris_r, k, atan2f(dyp, dxp));
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

            // 睫毛线。压在虹膜和瞳孔之上、高光之下 —— 日系画法里高光是允许
            // 骑在睫毛线上的，那正是"眼睛在反光"的读法。
            if (anime) {
                const float cap = lid.slit * kLashSlitCap;
                const float w = cap < kLashW ? cap : kLashW;
                if (w > 0.0f && lid.d_upper < w) {
                    const float la = Clamp01((1.0f - lid.d_upper / w) * kLashSharp);
                    c = Mix(c, lash_c, la);
                }
            }

            // 高光
            const float h1 = SoftDisc((float)x - hi1x, (float)y - hi1y, hi1r, hi_soft);
            if (h1 > 0.0f) c = Mix(c, white, h1);
            const float h2 = SoftDisc((float)x - hi2x, (float)y - hi2y, hi2r, hi_soft);
            if (h2 > 0.0f) c = Mix(c, white, h2 * hi2a);

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

    // 仅瞳孔/虹膜变化：取两帧虹膜圆的并集，加高光偏移与余量。
    // ComputeDirty 拿不到主题，只能按两种画法里够得最远的那个取值：
    // 写实主题的高光是固定像素尺寸，会溢出 44px 的虹膜，26 的余量是为它留的；
    // 日系虹膜 62 更大，但高光按虹膜比例给，反而全落在盘内。
    constexpr float kRealReach = kIrisR * 1.1f + 26.0f;
    constexpr float kAnimeReach = kAnimeIrisR * 1.1f + 6.0f;
    const float rad = kRealReach > kAnimeReach ? kRealReach : kAnimeReach;
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
