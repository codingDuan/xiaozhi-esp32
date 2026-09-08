#pragma once

#include <stddef.h>
#include <stdint.h>

#include <string_view>

// 眼睛主题是静态视觉参数；注视、眨眼和表情仍由 EyeState 驱动。
enum class ScleraStyle : uint8_t { kLight, kDark, kNone };
enum class PupilShape : uint8_t { kRound, kVerticalSlit, kHorizontalSlit };

struct EyeTheme {
    uint8_t id;
    std::string_view name;
    uint16_t iris_inner;
    uint16_t iris_outer;
    ScleraStyle sclera;
    PupilShape pupil;
};

class EyeThemeCatalog {
public:
    static constexpr size_t Count() { return 20; }

    // 无效 ID 回退到默认主题，避免旧 NVS 数据导致崩溃。
    static const EyeTheme& Get(uint8_t id);
    static uint8_t Next(uint8_t id);
    static int Find(std::string_view name);
};
