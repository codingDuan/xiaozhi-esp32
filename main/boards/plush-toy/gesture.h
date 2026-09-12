#pragma once

// 手势名单独成头文件：决策层（gesture_policy.h）只需要这个枚举，
// 不该被 limb_controller.h 的 FreeRTOS 与 I2C 依赖拖进来 —— 那样主机侧就测不了。
enum class Gesture {
    kHome,       // 双臂归中并泄力
    kWaveLeft,
    kWaveRight,
    kWaveBoth,
    kHug,        // 双臂张开并保持
    kCheer,      // 双臂反相摆动
    kDroop,      // 双臂下垂
    kLean,       // 双臂微微前倾（聆听态）
};
