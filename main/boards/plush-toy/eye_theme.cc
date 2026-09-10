#include "eye_theme.h"

#include "eye_iris_tex.h"

namespace {

constexpr EyeTheme kThemes[] = {
    {0, "ocean", 0x363E, 0x00A7, ScleraStyle::kLight, PupilShape::kRound},
    {1, "emerald", 0x5EC8, 0x0220, ScleraStyle::kLight, PupilShape::kRound},
    {2, "violet", 0xA35F, 0x300B, ScleraStyle::kLight, PupilShape::kRound},
    {3, "amber", 0xFE46, 0x7840, ScleraStyle::kLight, PupilShape::kRound},
    {4, "rose", 0xF9B5, 0x900D, ScleraStyle::kLight, PupilShape::kRound},
    {5, "ice", 0xDFFF, 0x3D9F, ScleraStyle::kLight, PupilShape::kRound},
    {6, "copper", 0xFD09, 0x7800, ScleraStyle::kLight, PupilShape::kRound},
    {7, "jade", 0x9EF2, 0x0485, ScleraStyle::kLight, PupilShape::kRound},
    {8, "midnight", 0x5A9F, 0x080F, ScleraStyle::kDark, PupilShape::kRound},
    {9, "pearl", 0xFFFF, 0x9DFF, ScleraStyle::kLight, PupilShape::kRound},
    {10, "void-blue", 0x6DFF, 0x0014, ScleraStyle::kNone, PupilShape::kRound},
    {11, "void-purple", 0xD41F, 0x280D, ScleraStyle::kNone, PupilShape::kRound},
    {12, "void-rose", 0xFC5B, 0x780D, ScleraStyle::kNone, PupilShape::kRound},
    {13, "dragon-amber", 0xFF08, 0xA000, ScleraStyle::kDark, PupilShape::kVerticalSlit},
    {14, "dragon-emerald", 0x9F2A, 0x0520, ScleraStyle::kDark, PupilShape::kVerticalSlit},
    {15, "dragon-violet", 0xCB5F, 0x400F, ScleraStyle::kDark, PupilShape::kVerticalSlit},
    {16, "cat-gold", 0xFF0E, 0x8040, ScleraStyle::kLight, PupilShape::kHorizontalSlit},
    {17, "cat-jade", 0xA7F3, 0x05A0, ScleraStyle::kLight, PupilShape::kHorizontalSlit},
    {18, "cat-ice", 0xE7FF, 0x3DFF, ScleraStyle::kLight, PupilShape::kHorizontalSlit},
    {19, "cat-rose", 0xFCB8, 0x980F, ScleraStyle::kLight, PupilShape::kHorizontalSlit},
    // 照片纹理虹膜，来自 Adafruit Uncanny_Eyes。iris_inner/outer 仅在
    // 无巩膜主题下才会用到，这里留着与前面保持同一初始化形状。
    {20, "uncanny-human", 0x8B4A, 0x4208, ScleraStyle::kLight, PupilShape::kRound, &kIrisHuman},
    {21, "uncanny-dragon", 0xFF08, 0xA000, ScleraStyle::kDark, PupilShape::kVerticalSlit,
     &kIrisDragon},
    // 日系画法。内外色差要比写实主题大得多 —— 动漫虹膜是一条从瞳孔边缘的浅色
    // 到外缘深色的强渐变，内外色太接近会让放射纤维和角膜缘环一起糊掉。
    {22, "anime-sky", 0x7F5F, 0x0A75, ScleraStyle::kLight, PupilShape::kRound, nullptr,
     IrisStyle::kAnime},
    {23, "anime-rose", 0xFD9B, 0xA0CC, ScleraStyle::kLight, PupilShape::kRound, nullptr,
     IrisStyle::kAnime},
    {24, "anime-gold", 0xFF11, 0x9AC0, ScleraStyle::kLight, PupilShape::kRound, nullptr,
     IrisStyle::kAnime},
    {25, "anime-violet", 0xDDDF, 0x48F2, ScleraStyle::kLight, PupilShape::kRound, nullptr,
     IrisStyle::kAnime},
};

static_assert(sizeof(kThemes) / sizeof(kThemes[0]) == EyeThemeCatalog::Count());

}  // namespace

const EyeTheme& EyeThemeCatalog::Get(uint8_t id) {
    return kThemes[id < Count() ? id : 0];
}

uint8_t EyeThemeCatalog::Next(uint8_t id) {
    return id < Count() - 1 ? static_cast<uint8_t>(id + 1) : 0;
}

int EyeThemeCatalog::Find(std::string_view name) {
    for (size_t i = 0; i < Count(); ++i) {
        if (kThemes[i].name == name)
            return static_cast<int>(i);
    }
    return -1;
}

bool EyeThemeSelection::Select(std::string_view requested_name) {
    if (requested_name.empty()) {
        id_ = EyeThemeCatalog::Next(id_);
        return true;
    }
    const int found = EyeThemeCatalog::Find(requested_name);
    if (found < 0)
        return false;
    id_ = static_cast<uint8_t>(found);
    return true;
}
