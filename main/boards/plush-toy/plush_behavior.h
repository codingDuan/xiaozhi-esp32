#pragma once

#include "limb_controller.h"
#include "device_state.h"

#include <string>

// 反射协调器：把设备状态与服务端下发的情绪翻译成肢体动作。
//
// 挂钩方式：自建周期任务轮询 Application::GetDeviceState()（public，
// application.h:68），而非改动核心代码。application.cc:247/:916 虽有现成的
// led->OnStateChanged() 回调，但把玩具行为伪装成 Led 语义别扭。
// 轮询任务本就需要存在，顺手读一次状态即可，零核心改动。
class PlushBehavior {
public:
    explicit PlushBehavior(LimbController* limbs);

    void Start();

    // 由 Display::SetEmotion 转发而来。服务端的 emotion 通道
    // （application.cc:602-606）是现成的，服务端零代码改动。
    void OnEmotion(const char* emotion);

private:
    static void TaskEntry(void* arg);
    void Run();
    void OnStateChanged(DeviceState from, DeviceState to);

    LimbController* limbs_;
    DeviceState last_state_ = kDeviceStateUnknown;
};
