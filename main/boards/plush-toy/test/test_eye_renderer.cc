// EyeRenderer 主机端测试。用 g++ 直接编译运行，不需要 ESP-IDF、不需要硬件。
//   cd main/boards/plush-toy/test && make test

#include "eye_renderer.h"
#include "eye_theme.h"

#include <cstdio>
#include <vector>

static int g_failures = 0;

#define CHECK(cond, msg)                                                 \
    do {                                                                 \
        if (!(cond)) {                                                   \
            std::printf("FAIL: %s (%s:%d)\n", msg, __FILE__, __LINE__);  \
            ++g_failures;                                                \
        }                                                                \
    } while (0)

static std::vector<uint16_t> RenderFull(const EyeState& s, int side) {
    std::vector<uint16_t> buf(EyeRenderer::kSize * EyeRenderer::kSize, 0xFFFF);
    EyeRenderer::Render(buf.data(), s, EyeThemeCatalog::Get(0), side, EyeRenderer::FullRect());
    return buf;
}

static std::vector<uint16_t> RenderFull(const EyeState& s, const EyeTheme& theme, int side) {
    std::vector<uint16_t> buf(EyeRenderer::kSize * EyeRenderer::kSize, 0xFFFF);
    EyeRenderer::Render(buf.data(), s, theme, side, EyeRenderer::FullRect());
    return buf;
}

static uint16_t At(const std::vector<uint16_t>& b, int x, int y) {
    return b[y * EyeRenderer::kSize + x];
}

static int CountLit(const std::vector<uint16_t>& b) {
    int n = 0;
    for (uint16_t v : b) {
        if (v != 0x0000) ++n;
    }
    return n;
}

static int CountLitInBand(const std::vector<uint16_t>& b, int y0, int y1) {
    int n = 0;
    for (int y = y0; y < y1; ++y) {
        for (int x = 0; x < EyeRenderer::kSize; ++x) {
            if (At(b, x, y) != 0x0000) ++n;
        }
    }
    return n;
}

// 圆屏之外必须是黑的，否则屏边缘会出现半块亮斑
static void TestOutsideCircleIsBlack() {
    EyeState s;
    auto b = RenderFull(s, +1);
    CHECK(At(b, 2, 2) == 0x0000, "圆屏外左上角应为黑");
    CHECK(At(b, 237, 237) == 0x0000, "圆屏外右下角应为黑");
}

// 睁眼时中心是瞳孔（暗），其正上方是巩膜（亮）
static void TestOpenEyeHasBrightScleraAndDarkPupil() {
    EyeState s;
    s.openness = 1.0f;
    auto b = RenderFull(s, +1);
    CHECK(At(b, 120, 120) < 0x2104, "全睁时中心应为瞳孔，接近黑");
    CHECK(At(b, 120, 52) > 0x8410, "全睁时中心上方应为巩膜，接近白");
}

// 主题必须改变可见帧：无巩膜、竖瞳、横瞳都不能只换一个名字。
static void TestThemesChangeScleraAndPupilShape() {
    EyeState s;
    s.openness = 1.0f;
    auto ocean = RenderFull(s, EyeThemeCatalog::Get(0), +1);
    auto void_blue = RenderFull(s, EyeThemeCatalog::Get(10), +1);
    auto dragon = RenderFull(s, EyeThemeCatalog::Get(13), +1);
    auto cat = RenderFull(s, EyeThemeCatalog::Get(16), +1);

    CHECK(At(ocean, 120, 52) != At(void_blue, 120, 52),
          "无巩膜主题应改变虹膜外的眼白区域");
    CHECK(At(dragon, 120, 94) != At(ocean, 120, 94),
          "竖瞳主题应改变圆瞳上方的像素");
    CHECK(At(cat, 94, 120) != At(ocean, 94, 120),
          "横瞳主题应改变圆瞳左侧的像素");
}

// 全闭时整块屏必须是黑的
static void TestClosedEyeIsBlank() {
    EyeState s;
    s.openness = 0.0f;
    auto b = RenderFull(s, +1);
    CHECK(CountLit(b) == 0, "openness=0 时应全黑");
}

// 镜像规则（spec §2.2.1 约束 2）：左眼 +t 与右眼 -t 必须逐像素相等。
// 这是该规则唯一的自动化防线 —— 同号会让「生气」变成整张脸歪向一边。
static void TestLidTiltMirrorsBetweenEyes() {
    EyeState l;
    l.lid_tilt = 20.0f;
    l.openness = 0.7f;
    EyeState r = l;
    r.lid_tilt = -20.0f;
    auto bl = RenderFull(l, +1);
    auto br = RenderFull(r, -1);
    bool same = true;
    for (size_t i = 0; i < bl.size(); ++i) {
        if (bl[i] != br[i]) { same = false; break; }
    }
    CHECK(same, "左眼 +t 与右眼 -t 应渲染出完全相同的像素");
}

// curve > 0 表示下眼睑上拱（弯月笑眼），下半部分点亮像素应减少
static void TestPositiveCurveRaisesLowerLid() {
    EyeState flat;
    flat.openness = 0.62f;
    flat.curve = 0.0f;
    EyeState smile = flat;
    smile.curve = 0.85f;
    auto bf = RenderFull(flat, +1);
    auto bs = RenderFull(smile, +1);
    CHECK(CountLitInBand(bs, 130, 200) < CountLitInBand(bf, 130, 200),
          "curve>0 应让下半部分点亮像素减少");
}

// 瞳孔水平偏移后，瞳孔中心应随之移动
static void TestPupilFollowsOffset() {
    EyeState s;
    s.openness = 1.0f;
    s.pupil_x = 0.8f;
    EyeRenderer::SetSwapRB(false);
    auto b = RenderFull(s, +1);
    CHECK(At(b, 120, 120) != 0x0041, "瞳孔右移后，屏心不应再是瞳孔");
    CHECK(At(b, 149, 120) == 0x0041, "瞳孔应出现在偏右位置");
}

// 只渲染局部矩形时，输出必须与整屏渲染的对应区域一致（脏矩形刷新的正确性前提）
static void TestPartialRectMatchesFull() {
    EyeState s;
    s.openness = 0.9f;
    auto full = RenderFull(s, +1);
    DirtyRect r{80, 80, 60, 60};
    std::vector<uint16_t> part(r.w * r.h, 0xFFFF);
    EyeRenderer::Render(part.data(), s, EyeThemeCatalog::Get(0), +1, r);
    bool same = true;
    for (int y = 0; y < r.h && same; ++y) {
        for (int x = 0; x < r.w; ++x) {
            if (part[y * r.w + x] != At(full, r.x + x, r.y + y)) { same = false; break; }
        }
    }
    CHECK(same, "局部渲染结果应与整屏渲染的对应区域一致");
}

// 状态未变时不该重绘
static void TestNoChangeYieldsEmptyRect() {
    EyeState a;
    DirtyRect r = EyeRenderer::ComputeDirty(a, a);
    CHECK(r.w == 0 && r.h == 0, "状态未变时脏矩形应为空");
}

// 只有瞳孔平移时，脏矩形必须显著小于全屏，否则脏矩形就白做了
static void TestPupilMoveYieldsSmallRect() {
    EyeState a;
    EyeState b = a;
    b.pupil_x = 0.3f;
    DirtyRect r = EyeRenderer::ComputeDirty(a, b);
    CHECK(r.w > 0 && r.h > 0, "瞳孔移动应产生非空脏矩形");
    CHECK(r.w * r.h < EyeRenderer::kSize * EyeRenderer::kSize / 2,
          "瞳孔移动的脏矩形应小于半屏");
}

// openness 变化牵动眼睑，脏矩形必须覆盖整个眼睛纵向范围
static void TestOpennessChangeYieldsTallRect() {
    EyeState a;
    a.openness = 1.0f;
    EyeState b = a;
    b.openness = 0.2f;
    DirtyRect r = EyeRenderer::ComputeDirty(a, b);
    CHECK(r.h >= 200, "眼睑变化应产生纵向接近全屏的脏矩形");
}

// 脏矩形必须真的覆盖住所有变化的像素，否则屏上会留下残影
static void TestDirtyRectCoversAllChangedPixels() {
    EyeState a;
    EyeState b = a;
    b.pupil_x = 0.35f;
    b.pupil_y = -0.2f;
    auto fa = RenderFull(a, +1);
    auto fb = RenderFull(b, +1);
    DirtyRect r = EyeRenderer::ComputeDirty(a, b);
    bool covered = true;
    for (int y = 0; y < EyeRenderer::kSize && covered; ++y) {
        for (int x = 0; x < EyeRenderer::kSize; ++x) {
            if (At(fa, x, y) == At(fb, x, y)) continue;
            if (x < r.x || x >= r.x + r.w || y < r.y || y >= r.y + r.h) {
                std::printf("  未覆盖的变化像素: (%d,%d)，脏矩形=(%d,%d,%d,%d)\n",
                            x, y, r.x, r.y, r.w, r.h);
                covered = false;
                break;
            }
        }
    }
    CHECK(covered, "脏矩形必须覆盖全部变化像素，否则屏上留残影");
}

// 红蓝互换开关必须真的只换红蓝、不动绿，且可来回切换
static void TestSwapRB() {
    EyeState s;
    s.openness = 1.0f;
    s.iris_color = 0x363E;   // #35C7F5 青蓝

    EyeRenderer::SetSwapRB(false);
    auto normal = RenderFull(s, +1);
    EyeRenderer::SetSwapRB(true);
    auto swapped = RenderFull(s, +1);
    EyeRenderer::SetSwapRB(false);
    auto back = RenderFull(s, +1);

    // 取虹膜上一点（瞳孔右侧、仍在虹膜内）
    const int x = 150, y = 120;
    uint16_t a = At(normal, x, y), b = At(swapped, x, y);
    const int ar = (a >> 11) & 0x1F, ag = (a >> 5) & 0x3F, ab = a & 0x1F;
    const int br = (b >> 11) & 0x1F, bg = (b >> 5) & 0x3F, bb = b & 0x1F;

    CHECK(a != b, "开关打开后颜色应改变");
    CHECK(ag == bg, "绿通道不应受影响");
    CHECK(ar != br || ab != bb, "红蓝通道应发生互换");
    CHECK(normal == back, "关掉开关后应完全恢复原状");
}

int main() {
    TestSwapRB();
    TestNoChangeYieldsEmptyRect();
    TestPupilMoveYieldsSmallRect();
    TestOpennessChangeYieldsTallRect();
    TestDirtyRectCoversAllChangedPixels();
    TestOutsideCircleIsBlack();
    TestOpenEyeHasBrightScleraAndDarkPupil();
    TestThemesChangeScleraAndPupilShape();
    TestClosedEyeIsBlank();
    TestLidTiltMirrorsBetweenEyes();
    TestPositiveCurveRaisesLowerLid();
    TestPupilFollowsOffset();
    TestPartialRectMatchesFull();

    if (g_failures == 0) {
        std::printf("所有测试通过\n");
        return 0;
    }
    std::printf("%d 项测试失败\n", g_failures);
    return 1;
}
