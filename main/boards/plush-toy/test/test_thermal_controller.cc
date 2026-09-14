#include "thermal_controller.h"
#include "config.h"

#include <cstdio>
#include <cstdlib>
#include <vector>

static int g_failures = 0;

#define CHECK(cond, msg)                                                \
    do {                                                                \
        if (!(cond)) {                                                  \
            std::printf("FAIL: %s (%s:%d)\n", msg, __FILE__, __LINE__); \
            ++g_failures;                                               \
        }                                                               \
    } while (0)

// 本测试链接 ads1115.cc，需要这些 I2C 符号；控制逻辑不碰硬件，给最简实现。
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

// 表中码值（PGA ±4.096V，3V3 分压，10k / NTC 10K B3950）
static const int16_t kCode0C = 20348;
static const int16_t kCode25C = 13200;
static const int16_t kCode35C = 10405;
static const int16_t kCode40C = 9147;
static const int16_t kCode48C = 7369;
static const int16_t kCodeOpen = 26400;   // 探头断线，节点被拉到 3V3
static const int16_t kCodeShort = 0;      // 探头短路

static const int kTick = THERMAL_POLL_INTERVAL_MS;

struct Harness {
    ThermalController c{nullptr};
    std::vector<bool> sink_calls;
    bool sink_ok = true;
    bool suppress = false;
    int64_t t = 0;

    Harness() {
        c.SetHeaterSink([this](bool on) {
            sink_calls.push_back(on);
            return sink_ok;
        });
        c.SetSuppressor([this]() { return suppress; });
    }
    void Feed(int16_t code, int samples) {
        for (int i = 0; i < samples; ++i, t += kTick)
            c.ApplySample(code, t);
    }
};

static void TestOpenProbeFaultsAfterLimit() {
    Harness h;
    h.Feed(kCode25C, 1);
    CHECK(h.c.RequestHeating(380, h.t), "有有效温度时请求加热应成功");
    h.Feed(kCodeOpen, THERMAL_BAD_SAMPLE_LIMIT - 1);
    CHECK(h.c.state() != ThermalState::kFault, "未满连续坏样本上限不应进故障态");
    h.Feed(kCodeOpen, 1);
    CHECK(h.c.state() == ThermalState::kFault, "断线连续坏样本满上限必须进故障态");
    CHECK(h.c.fault() == ThermalFault::kSensorOutOfRange, "故障原因必须是传感器越界");
    CHECK(!h.c.heater_on(), "故障态加热必须断开");
    CHECK(!h.sink_calls.empty() && !h.sink_calls.back(), "HeaterSink 最后收到的必须是 false");
}

static void TestShortedProbeFaults() {
    Harness h;
    h.Feed(kCode25C, 1);
    h.c.RequestHeating(380, h.t);
    h.Feed(kCodeShort, THERMAL_BAD_SAMPLE_LIMIT);
    CHECK(h.c.fault() == ThermalFault::kSensorOutOfRange, "短路同样必须进故障态");
}

// I2C 读失败时轮询任务拿不到码值。若只是跳过，加热会停在上一次的输出上 ——
// 读失败必须和坏样本同等对待。
static void TestReadFailuresCountAsBadSamples() {
    Harness h;
    h.Feed(kCode25C, 1);
    h.c.RequestHeating(380, h.t);
    for (int i = 0; i < THERMAL_BAD_SAMPLE_LIMIT; ++i, h.t += kTick)
        h.c.ApplyReadFailure(h.t);
    CHECK(h.c.fault() == ThermalFault::kSensorOutOfRange, "连续读失败必须进故障态");
    CHECK(!h.c.heater_on(), "连续读失败后加热必须断开");
}

static void TestSporadicBadSamplesTolerated() {
    Harness h;
    h.Feed(kCode25C, 1);
    h.Feed(kCodeOpen, THERMAL_BAD_SAMPLE_LIMIT - 1);
    h.Feed(kCode25C, 1);
    h.Feed(kCodeOpen, THERMAL_BAD_SAMPLE_LIMIT - 1);
    CHECK(h.c.state() != ThermalState::kFault, "零星坏样本被好样本打断后不应进故障态");
    CHECK(h.c.rejected_samples() == 2 * (THERMAL_BAD_SAMPLE_LIMIT - 1), "丢弃计数必须累计");
}

static void TestOverTempFaultsImmediately() {
    Harness h;
    h.Feed(kCode25C, 1);
    h.c.RequestHeating(380, h.t);
    h.Feed(kCode48C, 1);
    CHECK(h.c.state() == ThermalState::kFault, "到 48℃ 必须立即进故障态");
    CHECK(h.c.fault() == ThermalFault::kOverTemp, "故障原因必须是过温");
    CHECK(!h.c.heater_on(), "过温后加热必须断开");
}

static void TestFaultIsLatched() {
    Harness h;
    h.Feed(kCode48C, 1);
    h.Feed(kCode25C, 20);
    CHECK(h.c.state() == ThermalState::kFault, "温度降回后故障必须仍然闭锁");
    CHECK(!h.c.RequestHeating(380, h.t), "故障态下请求加热必须被拒绝");
    CHECK(!h.c.heater_on(), "故障态下加热必须保持断开");
}

static void TestClearFaultAllowsHeatingAgain() {
    Harness h;
    h.Feed(kCode48C, 1);
    h.Feed(kCode25C, 1);
    h.c.ClearFault();
    CHECK(h.c.state() == ThermalState::kOff, "清除后回到关闭态");
    CHECK(h.c.fault() == ThermalFault::kNone, "清除后故障原因为空");
    CHECK(h.c.RequestHeating(380, h.t), "清除后可再次请求加热");
}

// 没有有效温度就不知道离过温还有多远，不能开。
static void TestNoHeatingWithoutValidTemperature() {
    Harness h;
    CHECK(!h.c.RequestHeating(380, h.t), "尚无有效样本时请求加热必须被拒绝");
    h.Feed(kCodeOpen, 1);
    CHECK(!h.c.RequestHeating(380, h.t), "只有坏样本时请求加热必须被拒绝");
}

static void TestRiseTooFastFaults() {
    Harness h;
    h.Feed(kCode25C, 1);
    h.c.RequestHeating(380, h.t);
    // 30 秒内从 25℃ 线性升到 40℃，远超 10℃/分钟，但未到 48℃ 过温线
    const int steps = 30000 / kTick;
    for (int i = 1; i <= steps && h.c.state() != ThermalState::kFault; ++i, h.t += kTick)
        h.c.ApplySample((int16_t)(kCode25C + (kCode40C - kCode25C) * i / steps), h.t);
    CHECK(h.c.fault() == ThermalFault::kRiseTooFast, "60 秒内升温超 10℃ 必须判升温过快");
}

// 不加热时温度快速变化是正常的（冰水标定、探头从冷处拿到手里），不能误报。
static void TestRiseRateIgnoredWhenNotHeating() {
    Harness h;
    h.Feed(kCode0C, 1);
    const int steps = 30000 / kTick;
    for (int i = 1; i <= steps; ++i, h.t += kTick)
        h.c.ApplySample((int16_t)(kCode0C + (kCode25C - kCode0C) * i / steps), h.t);
    CHECK(h.c.state() == ThermalState::kOff, "未加热时快速升温不应进故障态");
}

static void TestProbeDetachedFaults() {
    Harness h;
    h.Feed(kCode25C, 1);
    h.c.RequestHeating(380, h.t);   // 差 13℃，占空比顶在上限
    h.Feed(kCode25C, THERMAL_DETACH_WINDOW_MS / kTick + 2);
    CHECK(h.c.fault() == ThermalFault::kProbeDetached, "满占空比 2 分钟无温升必须判探头失联");
    CHECK(!h.c.heater_on(), "探头失联后加热必须断开");
}

static void TestDutyCappedRegardlessOfError() {
    Harness h;
    h.Feed(kCode0C, 1);
    h.c.RequestHeating(400, h.t);   // 差 40℃
    CHECK(h.c.duty_percent() == THERMAL_DUTY_MAX_PCT, "误差再大占空比也不得超过上限");
    h.c.Stop();
    CHECK(h.c.ForceDuty(100, h.t), "强制占空比请求应被接受");
    CHECK(h.c.duty_percent() == THERMAL_DUTY_MAX_PCT, "强制占空比同样受硬上限约束");
}

static void TestTargetClamped() {
    Harness h;
    h.Feed(kCode25C, 1);
    h.c.RequestHeating(900, h.t);
    CHECK(h.c.target_dc() == THERMAL_TARGET_MAX_DC, "目标温度必须截断到上限");
}

static void TestAboveTargetHeaterOff() {
    Harness h;
    h.Feed(kCode40C, 1);
    h.c.RequestHeating(380, h.t);
    h.Feed(kCode40C, 4);
    CHECK(h.c.duty_percent() == 0, "超过目标时占空比为 0");
    CHECK(!h.c.heater_on(), "超过目标时加热断开");
    CHECK(h.c.state() == ThermalState::kHeating, "超过目标仍保持加热会话，只是不导通");
}

static void TestSessionExpires() {
    Harness h;
    h.Feed(kCode35C, 1);
    h.c.RequestHeating(380, h.t);   // 差 3℃，占空比 15%，低于失联检测门槛
    h.Feed(kCode35C, THERMAL_SESSION_MAX_MS / kTick + 2);
    CHECK(h.c.state() == ThermalState::kOff, "会话超时必须自动关闭");
    CHECK(h.c.fault() == ThermalFault::kSessionExpired, "关闭原因必须是会话超时");
    CHECK(!h.c.heater_on(), "会话超时后加热断开");
    CHECK(h.c.RequestHeating(380, h.t), "超时不是闭锁故障，重新请求即可");
    CHECK(h.c.fault() == ThermalFault::kNone, "重新请求后超时原因清空");
}

static void TestSuppressorForcesHeaterOff() {
    Harness h;
    h.Feed(kCode25C, 1);
    h.c.RequestHeating(380, h.t);
    h.Feed(kCode25C, 1);
    CHECK(h.c.heater_on(), "窗口前段应导通");
    h.suppress = true;
    h.Feed(kCode25C, 1);
    CHECK(!h.c.heater_on(), "抑制器为 true 时加热必须断开");
    CHECK(!h.sink_calls.empty() && !h.sink_calls.back(), "抑制时 HeaterSink 必须收到 false");
}

static void TestTimeProportionalWindow() {
    Harness h;
    h.Feed(kCode25C, 1);
    h.c.RequestHeating(380, h.t);
    const int64_t start = h.t;
    int on_ms = 0;
    for (; h.t < start + THERMAL_WINDOW_MS; h.t += kTick) {
        h.c.ApplySample(kCode25C, h.t);
        if (h.c.heater_on())
            on_ms += kTick;
    }
    CHECK(on_ms == THERMAL_WINDOW_MS * THERMAL_DUTY_MAX_PCT / 100,
          "占空比 20% 时 10 秒窗口内导通时长必须是 2 秒");
}

static void TestStopTurnsHeaterOffImmediately() {
    Harness h;
    h.Feed(kCode25C, 1);
    h.c.RequestHeating(380, h.t);
    h.Feed(kCode25C, 1);
    h.c.Stop();
    CHECK(h.c.state() == ThermalState::kOff, "Stop 后为关闭态");
    CHECK(!h.c.heater_on(), "Stop 后加热断开");
    CHECK(!h.sink_calls.empty() && !h.sink_calls.back(), "Stop 必须立刻通知 HeaterSink");
}

// 写失败时不能以为已经关了：下一个周期必须重发。
static void TestSinkFailureIsRetried() {
    Harness h;
    h.Feed(kCode25C, 1);
    h.c.RequestHeating(380, h.t);
    h.Feed(kCode25C, 1);
    h.sink_ok = false;
    h.c.Stop();
    const size_t after_stop = h.sink_calls.size();
    h.sink_ok = true;
    h.Feed(kCode25C, 1);
    CHECK(h.sink_calls.size() > after_stop, "上次写失败，下个周期必须重发");
    CHECK(!h.sink_calls.back(), "重发的必须是 false");
}

static void TestOffStateNeverHeats() {
    Harness h;
    h.Feed(kCode0C, 100);
    for (bool on : h.sink_calls)
        CHECK(!on, "从未请求加热时 HeaterSink 不得收到 true");
    CHECK(!h.c.heater_on(), "从未请求加热时不得导通");
}

static void TestCodeToTemperature() {
    const struct {
        int16_t code;
        int deci_c;
    } points[] = {{22532, -100}, {20348, 0}, {13200, 250}, {12045, 290}, {9889, 370},
                  {9147, 400},   {8000, 450}, {7369, 480},  {5257, 600},  {2254, 900}};
    for (const auto& p : points) {
        const int got = ThermalController::CodeToDeciC(p.code);
        CHECK(std::abs(got - p.deci_c) <= 5, "码值转温度误差必须在 0.5℃ 内");
    }
}

int main() {
    TestOpenProbeFaultsAfterLimit();
    TestShortedProbeFaults();
    TestReadFailuresCountAsBadSamples();
    TestSporadicBadSamplesTolerated();
    TestOverTempFaultsImmediately();
    TestFaultIsLatched();
    TestClearFaultAllowsHeatingAgain();
    TestNoHeatingWithoutValidTemperature();
    TestRiseTooFastFaults();
    TestRiseRateIgnoredWhenNotHeating();
    TestProbeDetachedFaults();
    TestDutyCappedRegardlessOfError();
    TestTargetClamped();
    TestAboveTargetHeaterOff();
    TestSessionExpires();
    TestSuppressorForcesHeaterOff();
    TestTimeProportionalWindow();
    TestStopTurnsHeaterOffImmediately();
    TestSinkFailureIsRetried();
    TestOffStateNeverHeats();
    TestCodeToTemperature();
    if (g_failures)
        return 1;
    std::puts("all ThermalController tests passed");
    return 0;
}
