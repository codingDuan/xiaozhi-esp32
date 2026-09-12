#include "gesture_policy.h"

#include <cstdio>

static int g_failures = 0;

#define CHECK(cond, msg)                                                \
    do {                                                                \
        if (!(cond)) {                                                  \
            std::printf("FAIL: %s (%s:%d)\n", msg, __FILE__, __LINE__); \
            ++g_failures;                                               \
        }                                                               \
    } while (0)

static void TestDefaultIsSilent() {
    // 这条是本模块存在的理由：出厂默认下，一轮完整对话
    // （Idle→Listening→Speaking→Idle）一个手势都不许发。
    Gesture g;
    CHECK(!StateGesture(kDeviceStateListening, GESTURE_MODES_DEFAULT, g), "默认聆听不动");
    CHECK(!StateGesture(kDeviceStateSpeaking, GESTURE_MODES_DEFAULT, g), "默认说话不动");
    CHECK(!StateGesture(kDeviceStateIdle, GESTURE_MODES_DEFAULT, g), "默认回到空闲不动");

    int times = 0;
    CHECK(!EmotionGesture("happy", GESTURE_MODES_DEFAULT, g, times), "默认情绪不动");
}

static void TestEachBitEnablesOnlyItsOwnState() {
    Gesture g;
    CHECK(StateGesture(kDeviceStateListening, GESTURE_MODE_LISTEN, g) && g == Gesture::kLean,
          "LISTEN 位打开时聆听前倾");
    CHECK(!StateGesture(kDeviceStateSpeaking, GESTURE_MODE_LISTEN, g), "LISTEN 位不该带出说话手势");
    CHECK(!StateGesture(kDeviceStateIdle, GESTURE_MODE_LISTEN, g), "LISTEN 位不该带出归中");

    CHECK(StateGesture(kDeviceStateSpeaking, GESTURE_MODE_SPEAK, g) && g == Gesture::kCheer,
          "SPEAK 位打开时说话轻摆");
    CHECK(StateGesture(kDeviceStateIdle, GESTURE_MODE_IDLE, g) && g == Gesture::kHome,
          "IDLE 位打开时归中");
}

static void TestUnrelatedStatesNeverGesture() {
    Gesture g;
    const uint32_t all = GESTURE_MODES_ALL;
    CHECK(!StateGesture(kDeviceStateConnecting, all, g), "连接中不动");
    CHECK(!StateGesture(kDeviceStateUpgrading, all, g), "升级中不动");
    CHECK(!StateGesture(kDeviceStateWifiConfiguring, all, g), "配网中不动");
    CHECK(!StateGesture(kDeviceStateFatalError, all, g), "故障态不动");
}

static void TestEmotionMapping() {
    Gesture g;
    int times = 0;
    const uint32_t m = GESTURE_MODE_EMOTION;

    CHECK(EmotionGesture("laughing", m, g, times) && g == Gesture::kCheer && times == 2,
          "laughing 摆两次");
    CHECK(EmotionGesture("loving", m, g, times) && g == Gesture::kHug && times == 1, "loving 拥抱");
    CHECK(EmotionGesture("crying", m, g, times) && g == Gesture::kDroop, "crying 垂臂");
    CHECK(EmotionGesture("shocked", m, g, times) && g == Gesture::kWaveBoth, "shocked 双臂摆");

    // 刻意不动作的几类：angry 静止比手舞足蹈更有张力，thinking 动作干扰"正在想"。
    CHECK(!EmotionGesture("angry", m, g, times), "angry 不动");
    CHECK(!EmotionGesture("thinking", m, g, times), "thinking 不动");
    CHECK(!EmotionGesture("neutral", m, g, times), "neutral 不动");
    CHECK(!EmotionGesture("", m, g, times), "空情绪不动");
}

static void TestEmotionBitIsIndependent() {
    Gesture g;
    int times = 0;
    // 关掉 EMOTION 位而其余全开，情绪仍不得驱动手臂 —— 服务端几乎每次回复
    // 都带 emotion，这一位是"每条指令都动"的另一个来源。
    CHECK(!EmotionGesture("happy", GESTURE_MODES_ALL & ~GESTURE_MODE_EMOTION, g, times),
          "EMOTION 位关闭时情绪不动");
    CHECK(StateGesture(kDeviceStateSpeaking, GESTURE_MODES_ALL & ~GESTURE_MODE_EMOTION, g),
          "关 EMOTION 位不影响状态手势");
}

int main() {
    TestDefaultIsSilent();
    TestEachBitEnablesOnlyItsOwnState();
    TestUnrelatedStatesNeverGesture();
    TestEmotionMapping();
    TestEmotionBitIsIndependent();

    if (g_failures == 0)
        std::printf("test_gesture_policy: 全部通过\n");
    return g_failures == 0 ? 0 : 1;
}
