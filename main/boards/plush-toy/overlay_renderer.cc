#include "overlay_renderer.h"

#include <algorithm>
#include <cmath>

namespace {

constexpr uint16_t kBackground = 0x0000;
constexpr uint16_t kTrack = 0x10C4;
constexpr uint16_t kActive = 0x363E;
constexpr float kInnerRadius = 76.0f;
constexpr float kOuterRadius = 88.0f;
constexpr float kTwoPi = 6.28318530717958647692f;

}  // namespace

void OverlayRenderer::RenderProgress(uint16_t* out, int progress) {
    if (out == nullptr)
        return;

    progress = std::clamp(progress, 0, 100);
    const float sweep = kTwoPi * static_cast<float>(progress) / 100.0f;
    const float center = static_cast<float>(kSize) / 2.0f;

    for (int y = 0; y < kSize; ++y) {
        for (int x = 0; x < kSize; ++x) {
            const float dx = (static_cast<float>(x) + 0.5f) - center;
            const float dy = (static_cast<float>(y) + 0.5f) - center;
            const float radius = std::sqrt(dx * dx + dy * dy);
            uint16_t color = kBackground;

            if (radius >= kInnerRadius && radius <= kOuterRadius) {
                color = kTrack;
                float angle = std::atan2(dx, -dy);  // 0 at 12 o'clock, clockwise positive
                if (angle < 0.0f)
                    angle += kTwoPi;
                if (progress > 0 && angle <= sweep)
                    color = kActive;
            }

            out[y * kSize + x] = color;
        }
    }
}

bool OverlayRenderer::RenderQr(uint16_t* out, const std::vector<uint8_t>& modules, int side) {
    if (out == nullptr || side <= 0) {
        return false;
    }
    const size_t module_count = static_cast<size_t>(side) * static_cast<size_t>(side);
    if (modules.size() != module_count) {
        return false;
    }

    constexpr int kInscribedSquare = 169;
    constexpr int kQuietModules = 8;  // four modules on every side
    if (side > kInscribedSquare - kQuietModules)
        return false;
    const int scale = kInscribedSquare / (side + kQuietModules);
    if (scale <= 0)
        return false;

    std::fill(out, out + kSize * kSize, static_cast<uint16_t>(0xFFFF));
    const int origin = (kSize - side * scale) / 2;
    for (int module_y = 0; module_y < side; ++module_y) {
        for (int module_x = 0; module_x < side; ++module_x) {
            if (modules[module_y * side + module_x] == 0)
                continue;
            for (int dy = 0; dy < scale; ++dy) {
                uint16_t* row =
                    out + (origin + module_y * scale + dy) * kSize + origin + module_x * scale;
                std::fill(row, row + scale, static_cast<uint16_t>(0x0000));
            }
        }
    }
    return true;
}

void OverlayRenderer::RenderWaitIcon(uint16_t* out) {
    if (out == nullptr)
        return;

    constexpr float kInner = 55.0f;
    constexpr float kOuter = 65.0f;
    const float center = static_cast<float>(kSize) / 2.0f;
    for (int y = 0; y < kSize; ++y) {
        for (int x = 0; x < kSize; ++x) {
            const float dx = (static_cast<float>(x) + 0.5f) - center;
            const float dy = (static_cast<float>(y) + 0.5f) - center;
            const float radius = std::sqrt(dx * dx + dy * dy);
            out[y * kSize + x] = (radius >= kInner && radius <= kOuter) ? kActive : kBackground;
        }
    }
}
