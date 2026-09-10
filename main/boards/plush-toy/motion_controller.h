#pragma once

#include "mpu6050.h"

#include <functional>

enum class Orientation { kUnknown, kUpright, kLying, kInverted };
enum class MotionEvent { kShake, kOrientationChanged };

// 运动判定。只回答「刚被摇了」和「姿态刚变成什么」，
// 不知道该做什么反应 —— 那是 PlushBehavior 的事。
//
// 时间由调用方传入而非内部读时钟：不应期和迟滞必须能在主机侧确定性地测。
class MotionController {
public:
    using MotionHandler = std::function<void(MotionEvent, Orientation)>;
    // 返回 true 表示当前应抑制摇晃判定。舵机动作期间的机械振动会被加速度计
    // 读到，而摇晃的默认反射是摆手，不抑制会自激。
    using Suppressor = std::function<bool()>;

    explicit MotionController(Mpu6050* mpu);

    bool available() const { return mpu_ != nullptr; }
    void SetHandler(MotionHandler handler) { handler_ = std::move(handler); }
    void SetSuppressor(Suppressor suppressor) { suppressor_ = std::move(suppressor); }
    void Start();

    // 公开是为了三个用途：主机侧单测、测试通道的模拟运动、轮询任务自身。
    void ApplySample(int16_t ax, int16_t ay, int16_t az, int64_t now_ms);

    Orientation orientation() const { return orientation_; }
    int shake_hits() const { return shake_hits_; }

private:
    static void TaskEntry(void* arg);
    void Run();
    Orientation ClassifyOrientation(int16_t up_axis_value) const;
    void UpdateShake(int16_t ax, int16_t ay, int16_t az, int64_t now_ms);

    Mpu6050* mpu_ = nullptr;
    MotionHandler handler_;
    Suppressor suppressor_;
    Orientation orientation_ = Orientation::kUnknown;
    int shake_hits_ = 0;
    int64_t shake_window_start_ms_ = 0;
    int64_t shake_cooldown_until_ms_ = 0;
};
