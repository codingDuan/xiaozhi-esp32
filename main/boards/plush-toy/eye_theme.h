#pragma once

#include <stddef.h>
#include <stdint.h>

#include <string_view>

struct IrisTexture;

// 眼睛主题是静态视觉参数；注视、眨眼和表情仍由 EyeState 驱动。
enum class ScleraStyle : uint8_t { kLight, kDark, kNone };
enum class PupilShape : uint8_t { kRound, kVerticalSlit, kHorizontalSlit };

// 虹膜画法。kRealistic 是写实眼：虹膜占比接近真人，着色各向同性。
// kAnime 走日系画法 —— 虹膜显著放大、上缘压一条眼睑投影带、下缘补一道反射光
// 月牙、放射状纤维、加粗的睫毛线，高光也按虹膜比例放大。
// 这不只是配色差别，几何参数也随之切换，所以做成独立字段而不是塞进 ScleraStyle。
enum class IrisStyle : uint8_t { kRealistic, kAnime };

struct EyeTheme {
    uint8_t id;
    std::string_view name;
    uint16_t iris_inner;
    uint16_t iris_outer;
    ScleraStyle sclera;
    PupilShape pupil;
    // 非空时虹膜改用极坐标照片纹理，iris_inner/iris_outer 只在无巩膜主题里
    // 继续用来铺眼白区域。纹理自带角膜缘环，程序化的那一圈会跳过。
    const IrisTexture* iris_tex = nullptr;
    // 排在 iris_tex 之后是刻意的：前面的主题都用位置初始化，插在中间会让
    // 那两个带纹理的主题把 &kIrisHuman 绑到这个字段上。
    IrisStyle iris = IrisStyle::kRealistic;
};

class EyeThemeCatalog {
public:
    static constexpr size_t Count() { return 26; }

    // 无效 ID 回退到默认主题，避免旧 NVS 数据导致崩溃。
    static const EyeTheme& Get(uint8_t id);
    static uint8_t Next(uint8_t id);
    static int Find(std::string_view name);
};

// 纯状态机：把“下一个主题”与“按名称选择”从显示与 NVS 中拆开，便于宿主测试。
class EyeThemeSelection {
public:
    explicit EyeThemeSelection(uint8_t id = 0) : id_(EyeThemeCatalog::Get(id).id) {}

    bool Select(std::string_view requested_name);
    uint8_t id() const { return id_; }
    const EyeTheme& theme() const { return EyeThemeCatalog::Get(id_); }

private:
    uint8_t id_;
};
