#include "overlay_qr.h"

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

static void TestEncodesWifiString() {
    std::vector<uint8_t> modules;
    int side = 0;
    bool ok = OverlayQr::Encode("WIFI:S:Xiaozhi-A1B2;T:nopass;;", modules, side);
    CHECK(ok, "standard Wi-Fi provisioning text should encode");
    CHECK(side >= 21 && side <= 41, "QR version should stay within the round-screen limit");
    CHECK(static_cast<int>(modules.size()) == side * side,
          "module array length should be side*side");
}

static void TestFinderPatternsArePresent() {
    std::vector<uint8_t> modules;
    int side = 0;
    CHECK(OverlayQr::Encode("WIFI:S:Xiaozhi-A1B2;T:nopass;;", modules, side),
          "fixture should encode before checking finder patterns");
    if (side <= 0)
        return;
    CHECK(modules[0] == 1, "top-left finder corner should be dark");
    CHECK(modules[side - 1] == 1, "top-right finder corner should be dark");
    CHECK(modules[(side - 1) * side] == 1, "bottom-left finder corner should be dark");
}

static void TestFitsRoundScreenWithQuietZone() {
    std::vector<uint8_t> modules;
    int side = 0;
    CHECK(OverlayQr::Encode("WIFI:S:Xiaozhi-A1B2;T:nopass;;", modules, side),
          "fixture should encode before checking screen fit");
    if (side <= 0)
        return;
    const int scale = 169 / (side + 8);
    CHECK(scale >= 4, "QR modules should render at least 4px wide including quiet zone");
    CHECK((side + 8) * scale <= 169,
          "QR plus four-module quiet zone should fit the inscribed square");
}

static void TestRejectsInvalidInputWithoutStaleOutput() {
    std::vector<uint8_t> modules{1, 1, 1};
    int side = 7;
    CHECK(!OverlayQr::Encode(nullptr, modules, side), "null text should be rejected");
    CHECK(modules.empty() && side == 0, "failed encoding should clear outputs");

    modules = {1};
    side = 1;
    CHECK(!OverlayQr::Encode("", modules, side), "empty text should be rejected");
    CHECK(modules.empty() && side == 0, "empty text should not leave stale outputs");
}

int main() {
    TestEncodesWifiString();
    TestFinderPatternsArePresent();
    TestFitsRoundScreenWithQuietZone();
    TestRejectsInvalidInputWithoutStaleOutput();

    if (g_failures == 0) {
        std::printf("all OverlayQr tests passed\n");
        return 0;
    }
    std::printf("%d OverlayQr test(s) failed\n", g_failures);
    return 1;
}
