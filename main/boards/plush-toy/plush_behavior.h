#pragma once

#include "config.h"
#include "device_state.h"
#include "limb_controller.h"
#include "motion_controller.h"

#include <stdint.h>
#include <string>

class EyeDisplay;

// 反射协调器：把设备状态与服务端下发的情绪翻译成肢体动作。
//
// 挂钩方式：自建周期任务轮询 Application::GetDeviceState()（public，
// application.h:68），而非改动核心代码。application.cc:247/:916 虽有现成的
// led->OnStateChanged() 回调，但把玩具行为伪装成 Led 语义别扭。
// 轮询任务本就需要存在，顺手读一次状态即可，零核心改动。
class PlushBehavior {
public:
    PlushBehavior(LimbController* limbs, EyeDisplay* display);

    void Start();

    // 由 Display::SetEmotion 转发而来。服务端的 emotion 通道
    // （application.cc:602-606）是现成的，服务端零代码改动。
    void OnEmotion(const char* emotion);

    // 由 TouchController 转发而来。按模式掩码分发，四条路径互不影响。
    void OnTouch(int electrode, bool pressed);

    uint32_t touch_modes() const { return touch_modes_; }
    // 立即生效并写回 NVS。
    void SetTouchModes(uint32_t modes);

    // 由 MotionController 转发而来。按 motion_modes 掩码分发。
    void OnMotion(MotionEvent event, Orientation orientation);

    uint32_t motion_modes() const { return motion_modes_; }
    void SetMotionModes(uint32_t modes);

private:
    static void TaskEntry(void* arg);
    void Run();
    void OnStateChanged(DeviceState from, DeviceState to);

    LimbController* limbs_;
    EyeDisplay* display_;
    DeviceState last_state_ = kDeviceStateUnknown;
    uint32_t touch_modes_ = TOUCH_MODES_DEFAULT;
    uint32_t motion_modes_ = MOTION_MODES_DEFAULT;
};
