#include "motion_controller.h"
#include "config.h"

#include <cstdio>
#include <string>
#include <vector>

static int g_failures = 0;

#define CHECK(cond, msg)                                                \
    do {                                                                \
        if (!(cond)) {                                                  \
            std::printf("FAIL: %s (%s:%d)\n", msg, __FILE__, __LINE__); \
            ++g_failures;                                               \
        }                                                               \
    } while (0)

// 本测试链接 mpu6050.cc，需要这些 I2C 符号；判定逻辑不碰硬件，给最简实现。
struct FakeI2cDevice {};
static FakeI2cDevice g_device;
const char* esp_err_to_name(esp_err_t) { return "fake error"; }
esp_err_t i2c_master_bus_add_device(i2c_master_bus_handle_t, const i2c_device_config_t*,
                                    i2c_master_dev_handle_t* device) {
    *device = &g_device;
    return ESP_OK;
}
esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t) { return ESP_OK; }
esp_err_t i2c_master_transmit(i2c_master_dev_handle_t, const uint8_t*, size_t, int) {
    return ESP_OK;
}
esp_err_t i2c_master_transmit_receive(i2c_master_dev_handle_t, const uint8_t*, size_t, uint8_t*,
                                      size_t, int) {
    return ESP_OK;
}

struct Record {
    MotionEvent event;
    Orientation orientation;
};

static const int kG = MOTION_LSB_PER_G;

// 竖直静置：Z 轴 +1g，其余为零。
static void FeedUpright(MotionController& c, int64_t& t, int samples) {
    for (int i = 0; i < samples; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(0, 0, kG, t);
}

static void TestSteadyUprightEmitsOneOrientationEvent() {
    std::vector<Record> log;
    MotionController c(nullptr);
    c.SetHandler([&](MotionEvent e, Orientation o) { log.push_back({e, o}); });
    int64_t t = 0;
    FeedUpright(c, t, 20);
    CHECK(log.size() == 1, "从未知态进入竖直只应产生一个事件");
    CHECK(!log.empty() && log[0].orientation == Orientation::kUpright, "首个事件必须是竖直");
    CHECK(c.orientation() == Orientation::kUpright, "当前姿态必须是竖直");
}

static void TestInvertedProducesOneMoreEvent() {
    std::vector<Record> log;
    MotionController c(nullptr);
    c.SetHandler([&](MotionEvent e, Orientation o) { log.push_back({e, o}); });
    int64_t t = 0;
    FeedUpright(c, t, 5);
    for (int i = 0; i < 10; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(0, 0, -kG, t);
    // 竖直翻到倒置必然路过躺倒：先跌破竖直的离开门限，再越过倒置的进入门限。
    // 实物翻转本来就要经过水平，这不是抖动。
    CHECK(log.size() == 3, "竖直转倒置应经由躺倒产生两个新事件");
    CHECK(log.size() == 3 && log[1].orientation == Orientation::kLying, "中间态是躺倒");
    CHECK(log.size() == 3 && log[2].orientation == Orientation::kInverted, "终态是倒置");
}

// 迟滞的意义：在门限附近抖动不得反复产生事件。
static void TestHysteresisSuppressesBoundaryChatter() {
    std::vector<Record> log;
    MotionController c(nullptr);
    // 只数姿态事件：0.6g 样本对 1g 的偏离超过摇晃阈值，会顺带产生摇晃事件，
    // 那与本条要验证的迟滞无关。
    c.SetHandler([&](MotionEvent e, Orientation o) {
        if (e == MotionEvent::kOrientationChanged)
            log.push_back({e, o});
    });
    int64_t t = 0;
    FeedUpright(c, t, 5);
    const size_t after_upright = log.size();
    // 在 0.5g 与 0.7g 之间来回：已进入竖直态，且未跌破离开门限，不应有新事件
    for (int i = 0; i < 10; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(0, 0, (i % 2 == 0) ? (kG * 6) / 10 : (kG * 8) / 10, t);
    CHECK(log.size() == after_upright, "门限之间的抖动不得产生姿态事件");
}

static void TestShakeNeedsEnoughHits() {
    std::vector<Record> log;
    MotionController c(nullptr);
    c.SetHandler([&](MotionEvent e, Orientation o) { log.push_back({e, o}); });
    int64_t t = 0;
    FeedUpright(c, t, 5);
    const size_t before = log.size();
    // 只有两次剧烈样本，不够 MOTION_SHAKE_HITS
    for (int i = 0; i < 2; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(0, 0, kG * 2, t);
    CHECK(log.size() == before, "命中次数不足不得产生摇晃事件");
}

static void TestShakeCooldownCollapsesBurst() {
    std::vector<Record> log;
    MotionController c(nullptr);
    c.SetHandler([&](MotionEvent e, Orientation o) {
        if (e == MotionEvent::kShake)
            log.push_back({e, o});
    });
    int64_t t = 0;
    FeedUpright(c, t, 5);
    // 1.2 秒连续剧烈样本：短于不应期，必须塌缩成一个事件
    for (int i = 0; i < 12; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(0, 0, kG * 2, t);
    CHECK(log.size() == 1, "不应期内的连续剧烈样本只应产生一个摇晃事件");
}

// 不应期是限流不是封禁：过了就必须能再次触发，否则摇两次只响一次。
static void TestShakeFiresAgainAfterCooldown() {
    std::vector<Record> log;
    MotionController c(nullptr);
    c.SetHandler([&](MotionEvent e, Orientation o) {
        if (e == MotionEvent::kShake)
            log.push_back({e, o});
    });
    int64_t t = 0;
    FeedUpright(c, t, 5);
    for (int i = 0; i < 5; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(0, 0, kG * 2, t);
    CHECK(log.size() == 1, "第一阵摇晃产生一个事件");
    t += MOTION_SHAKE_COOLDOWN_MS + MOTION_POLL_INTERVAL_MS;  // 等过不应期
    for (int i = 0; i < 5; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(0, 0, kG * 2, t);
    CHECK(log.size() == 2, "不应期过后第二阵摇晃必须能再次触发");
}

// 舵机自振会被加速度计读到，且摇晃的默认反射是摆手，不抑制会自激。
static void TestSuppressorBlocksShakeButNotOrientation() {
    std::vector<Record> log;
    MotionController c(nullptr);
    c.SetSuppressor([] { return true; });
    c.SetHandler([&](MotionEvent e, Orientation o) { log.push_back({e, o}); });
    int64_t t = 0;
    for (int i = 0; i < 20; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(0, 0, kG * 2, t);
    for (const auto& r : log)
        CHECK(r.event != MotionEvent::kShake, "抑制期间不得产生摇晃事件");
    FeedUpright(c, t, 5);
    bool saw_orientation = false;
    for (const auto& r : log)
        if (r.event == MotionEvent::kOrientationChanged)
            saw_orientation = true;
    CHECK(saw_orientation, "抑制不得影响姿态判定");
}

// 实测：I2C 偶发吐出全 1 的坏字节，az 变成 -258 或整轴变成 -1。
// 判定层照单全收的话，一个坏样本就能把姿态从竖直翻成躺倒。
static void TestImplausibleSampleIsRejected() {
    std::vector<Record> log;
    MotionController c(nullptr);
    c.SetHandler([&](MotionEvent e, Orientation o) { log.push_back({e, o}); });
    int64_t t = 0;
    FeedUpright(c, t, 10);
    const size_t before = log.size();
    const int rejected_before = c.rejected_samples();
    // 实测采到的两个真实坏样本
    c.ApplySample(2647, -1, -1, t);
    t += MOTION_POLL_INTERVAL_MS;
    c.ApplySample(2778, -225, -258, t);
    t += MOTION_POLL_INTERVAL_MS;
    CHECK(log.size() == before, "不合物理的样本不得产生任何事件");
    CHECK(c.orientation() == Orientation::kUpright, "坏样本不得改变姿态");
    CHECK(c.rejected_samples() == rejected_before + 2, "坏样本必须被计数");
}

// 单个落在合理区间内的坏样本仍可能出现，因此姿态还要求连续若干次一致。
static void TestOrientationNeedsConsecutiveAgreement() {
    std::vector<Record> log;
    MotionController c(nullptr);
    c.SetHandler([&](MotionEvent e, Orientation o) {
        if (e == MotionEvent::kOrientationChanged)
            log.push_back({e, o});
    });
    int64_t t = 0;
    FeedUpright(c, t, 10);
    const size_t before = log.size();
    // 少于确认次数的连续躺倒样本：不得切换
    for (int i = 0; i < MOTION_ORIENT_CONFIRM - 1; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(kG, 0, 0, t);
    CHECK(log.size() == before, "确认次数不足不得切换姿态");
    CHECK(c.orientation() == Orientation::kUpright, "确认次数不足时姿态保持不变");
    // 补足一次即达成确认
    c.ApplySample(kG, 0, 0, t);
    t += MOTION_POLL_INTERVAL_MS;
    CHECK(log.size() == before + 1, "确认次数达成后必须切换姿态");
    CHECK(c.orientation() == Orientation::kLying, "姿态应变为躺倒");
}

// 一次坏样本插在连续判定中间，不得让确认计数从头开始又不得让它蒙混过关。
static void TestSingleOutlierDoesNotFlipOrientation() {
    std::vector<Record> log;
    MotionController c(nullptr);
    c.SetHandler([&](MotionEvent e, Orientation o) {
        if (e == MotionEvent::kOrientationChanged)
            log.push_back({e, o});
    });
    int64_t t = 0;
    FeedUpright(c, t, 10);
    const size_t before = log.size();
    for (int i = 0; i < 20; ++i, t += MOTION_POLL_INTERVAL_MS) {
        // 每三次夹一个躺倒读数，模拟偶发坏样本
        if (i % 3 == 2)
            c.ApplySample(kG, 0, 0, t);
        else
            c.ApplySample(0, 0, kG, t);
    }
    CHECK(log.size() == before, "孤立的异常样本不得翻转姿态");
    CHECK(c.orientation() == Orientation::kUpright, "姿态必须保持竖直");
}

static void TestHandlerIsOptional() {
    MotionController c(nullptr);
    c.ApplySample(0, 0, kG, 0);  // 未设 handler 不得崩溃
    CHECK(!c.available(), "驱动为空时 available 必须为 false");
}

int main() {
    TestSteadyUprightEmitsOneOrientationEvent();
    TestInvertedProducesOneMoreEvent();
    TestHysteresisSuppressesBoundaryChatter();
    TestShakeNeedsEnoughHits();
    TestShakeCooldownCollapsesBurst();
    TestShakeFiresAgainAfterCooldown();
    TestSuppressorBlocksShakeButNotOrientation();
    TestImplausibleSampleIsRejected();
    TestOrientationNeedsConsecutiveAgreement();
    TestSingleOutlierDoesNotFlipOrientation();
    TestHandlerIsOptional();
    if (g_failures)
        return 1;
    std::puts("all MotionController tests passed");
    return 0;
}
