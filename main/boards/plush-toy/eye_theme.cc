#include "eye_theme.h"

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
