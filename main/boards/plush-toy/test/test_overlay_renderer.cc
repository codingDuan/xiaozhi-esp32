#include "overlay_renderer.h"

#include <climits>
#include <cstdio>
#include <vector>

static int g_failures = 0;

#define CHECK(cond, msg)                                                \
    do {                                                                \
        if (!(cond)) {                                                  \
            std::printf("FAIL: %s (%s:%d)\n", msg, __FILE__, __LINE__); \
            ++g_failures;                                               \
        }                                                               \
    } while (0)

static std::vector<uint16_t> Render(int progress) {
    std::vector<uint16_t> frame(OverlayRenderer::kSize * OverlayRenderer::kSize, 0xFFFF);
    OverlayRenderer::RenderProgress(frame.data(), progress);
    return frame;
}

static int CountColor(const std::vector<uint16_t>& frame, uint16_t color) {
    int count = 0;
    for (uint16_t pixel : frame) {
        if (pixel == color)
            ++count;
    }
    return count;
}

static void TestProgressAddsActiveArc() {
    const auto empty = Render(0);
    const auto half = Render(50);
    const auto full = Render(100);
    const int empty_active = CountColor(empty, 0x363E);
    const int half_active = CountColor(half, 0x363E);
    const int full_active = CountColor(full, 0x363E);
    CHECK(empty_active == 0, "zero percent should have no active arc");
    CHECK(half_active > empty_active, "half progress should add an active arc");
    CHECK(full_active > half_active, "full progress should activate more of the ring");
}

static void TestProgressIsClamped() {
    CHECK(Render(-20) == Render(0), "negative progress should clamp to zero");
    CHECK(Render(120) == Render(100), "progress above 100 should clamp to 100");
}

static void TestCornersStayBlackOnRoundDisplay() {
    const auto frame = Render(100);
    const int n = OverlayRenderer::kSize;
    CHECK(frame[0] == 0x0000, "top-left corner should stay black");
    CHECK(frame[n - 1] == 0x0000, "top-right corner should stay black");
    CHECK(frame[(n - 1) * n] == 0x0000, "bottom-left corner should stay black");
    CHECK(frame[n * n - 1] == 0x0000, "bottom-right corner should stay black");
}

static void TestRingStartsAtTwelveOClock() {
    const auto one_percent = Render(1);
    const int center = OverlayRenderer::kSize / 2;
    CHECK(one_percent[(center - 82) * OverlayRenderer::kSize + center] == 0x363E,
          "progress arc should start at twelve o'clock");
}

static void TestQrUsesDarkModulesOnLightBackground() {
    constexpr int side = 21;
    std::vector<uint8_t> modules(side * side, 0);
    modules[0] = 1;
    modules[(side / 2) * side + side / 2] = 1;
    std::vector<uint16_t> frame(OverlayRenderer::kSize * OverlayRenderer::kSize, 0x1234);
    CHECK(OverlayRenderer::RenderQr(frame.data(), modules, side), "valid QR modules should render");

    const int scale = 169 / (side + 8);
    const int origin = (OverlayRenderer::kSize - scale * side) / 2;
    CHECK(frame[origin * OverlayRenderer::kSize + origin] == 0x0000,
          "dark QR module should render black");
    CHECK(frame[origin * OverlayRenderer::kSize + origin + scale] == 0xFFFF,
          "light QR module should render white");
    CHECK(frame[(origin - 1) * OverlayRenderer::kSize + origin] == 0xFFFF,
          "quiet zone around QR should stay white");
}

static void TestQrRejectsMalformedModules() {
    std::vector<uint16_t> frame(OverlayRenderer::kSize * OverlayRenderer::kSize);
    CHECK(!OverlayRenderer::RenderQr(frame.data(), {}, 0), "empty QR should be rejected");
    CHECK(!OverlayRenderer::RenderQr(frame.data(), {1, 0, 1}, 2),
          "non-square module data should be rejected");
    CHECK(!OverlayRenderer::RenderQr(frame.data(), {}, INT_MAX),
          "oversized QR dimensions should be rejected without integer overflow");
}

static void TestWaitIconIsVisibleButCenterStaysDark() {
    std::vector<uint16_t> frame(OverlayRenderer::kSize * OverlayRenderer::kSize, 0xFFFF);
    OverlayRenderer::RenderWaitIcon(frame.data());
    const int center = OverlayRenderer::kSize / 2;
    CHECK(frame[center * OverlayRenderer::kSize + center] == 0x0000,
          "wait icon center should stay black");
    CHECK(frame[(center - 60) * OverlayRenderer::kSize + center] == 0x363E,
          "wait icon ring should use iris cyan");
    CHECK(frame[0] == 0x0000, "wait icon corner should stay black");
}

int main() {
    TestProgressAddsActiveArc();
    TestProgressIsClamped();
    TestCornersStayBlackOnRoundDisplay();
    TestRingStartsAtTwelveOClock();
    TestQrUsesDarkModulesOnLightBackground();
    TestQrRejectsMalformedModules();
    TestWaitIconIsVisibleButCenterStaysDark();

    if (g_failures == 0) {
        std::printf("all OverlayRenderer tests passed\n");
        return 0;
    }
    std::printf("%d OverlayRenderer test(s) failed\n", g_failures);
    return 1;
}
