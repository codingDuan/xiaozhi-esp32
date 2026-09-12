#pragma once

#include "config.h"
#include "device_state.h"
#include "gesture.h"

#include <stdint.h>
#include <string>

// 自发手势的决策层：给定设备状态（或服务端 emotion）与掩码，回答「动不动、动什么」。
//
// 和 MotionController 同一个理由做成纯函数：不碰 Application、不碰硬件，
// 主机侧可确定性地测。「默认一轮对话零手势」这条约束必须有测试守着，
// 否则以后谁顺手加一个 case 就悄悄退回每句话都抖的老样子。
//
// 返回 true 表示应执行 out 指定的手势。

inline bool StateGesture(DeviceState to, uint32_t modes, Gesture& out) {
    switch (to) {
        case kDeviceStateListening:
            if ((modes & GESTURE_MODE_LISTEN) == 0)
                return false;
            out = Gesture::kLean;  // 微微前倾，像在专心听
            return true;
        case kDeviceStateSpeaking:
            if ((modes & GESTURE_MODE_SPEAK) == 0)
                return false;
            out = Gesture::kCheer;  // 说话时轻摆一次
            return true;
        case kDeviceStateIdle:
            if ((modes & GESTURE_MODE_IDLE) == 0)
                return false;
            out = Gesture::kHome;  // 归中泄力
            return true;
        default:
            // 配网、升级、连接、故障态一律不动：这些状态下要么没人看着，
            // 要么屏幕上正显示要紧信息，手臂动作只会干扰。
            return false;
    }
}

inline bool EmotionGesture(const std::string& emotion, uint32_t modes, Gesture& out, int& times) {
    if ((modes & GESTURE_MODE_EMOTION) == 0)
        return false;

    // 服务端 EMOJI_MAP（textUtils.py:8-30）共 21 种，此处只映射有明确
    // 肢体表达的几类。其余刻意不动作 —— 动作稀疏比动作滥用更自然：
    // angry 时静止不动比手舞足蹈更有张力，thinking 时动作会干扰"正在想"的表达。
    if (emotion == "happy" || emotion == "laughing" || emotion == "funny" || emotion == "silly") {
        out = Gesture::kCheer;
        times = 2;
        return true;
    }
    if (emotion == "loving" || emotion == "kissy") {
        out = Gesture::kHug;
        times = 1;
        return true;
    }
    if (emotion == "sad" || emotion == "crying") {
        out = Gesture::kDroop;
        times = 1;
        return true;
    }
    if (emotion == "surprised" || emotion == "shocked") {
        out = Gesture::kWaveBoth;
        times = 1;
        return true;
    }
    return false;
}
