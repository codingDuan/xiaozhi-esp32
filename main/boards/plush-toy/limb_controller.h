#pragma once

#include "pca9685.h"

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>

#include <stdint.h>

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

// 舵机动作层。
//
// 三条硬性约束，全部来自 2026-09-07 实测：
//  1. 动作队列串行 —— 两个手势叠加会产生超出机械限位的合成角度
//  2. 每个动作结束后泄力 —— 保护 SG90 塑料齿（毛绒布料的持续回弹力是打齿主因）
//  3. 动作之间强制冷却 —— 双路无间歇连续摆动会触发 BROWNOUT 掉电重启（可复现）
//     间歇是必需项而非优化项
class LimbController {
public:
    explicit LimbController(Pca9685* pca);

    void Start();
    bool Enqueue(Gesture g, int times = 1);
    bool available() const { return pca_ != nullptr; }

    // 动作执行期间及结束后的沉降窗口内为 true。
    // 运动感知靠它屏蔽舵机自振，否则摆手会被判成摇晃、再触发摆手。
    bool busy() const;

private:
    static void TaskEntry(void* arg);
    void Run();
    void Perform(Gesture g, int times);
    void MoveTo(int left_deg, int right_deg, int step_ms);
    void Relax();

    Pca9685* pca_;
    QueueHandle_t queue_ = nullptr;
    int64_t busy_until_us_ = 0;
    int left_deg_ = 0;
    int right_deg_ = 0;
};
