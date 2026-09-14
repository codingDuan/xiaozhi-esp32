#include "thermal_controller.h"
#include "config.h"

#include <esp_log.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include <algorithm>

#define TAG "ThermalController"

namespace {
// -10℃ 到 90℃、5℃ 步长的码值表，码值随温度下降。由
//   R = 10k·exp(B·(1/T − 1/298.15))，V = 3.3·R/(R+10k)，code = V / 0.125mV
// 离线算出。线性插值相对 B 值公式的最大误差 0.1℃（82℃ 附近），不必在轮询里调 log()。
constexpr int16_t kCodeTable[] = {22532, 21513, 20348, 19051, 17651, 16182, 14685,
                                  13200, 11764, 10405, 9147,  8000,  6971,  6059,
                                  5257,  4557,  3951,  3427,  2976,  2588,  2254};
constexpr int kTableSize = sizeof(kCodeTable) / sizeof(kCodeTable[0]);
constexpr int kTableMinDc = -100;
constexpr int kTableStepDc = 50;

// 升温速率快照间隔：60 秒窗口分六段，7 个快照覆盖整个窗口。
constexpr int64_t kSnapshotIntervalMs = THERMAL_RISE_WINDOW_MS / 6;
}  // namespace

ThermalController::ThermalController(Ads1115* adc) : adc_(adc) {}

void ThermalController::SetHeaterSink(HeaterSink sink) {
    std::lock_guard<std::mutex> lock(mutex_);
    sink_ = std::move(sink);
    output_known_ = false;
}

void ThermalController::SetSuppressor(Suppressor suppressor) {
    std::lock_guard<std::mutex> lock(mutex_);
    suppressor_ = std::move(suppressor);
}

void ThermalController::Start() {
    if (adc_ == nullptr) {
        ESP_LOGW(TAG, "ADS1115 不可用，体温功能已禁用");
        return;
    }
    xTaskCreate(TaskEntry, "thermal", 3072, this, 3, nullptr);
    ESP_LOGI(TAG, "测温轮询已启动，周期 %d ms", THERMAL_POLL_INTERVAL_MS);
}

void ThermalController::TaskEntry(void* arg) { static_cast<ThermalController*>(arg)->Run(); }

void ThermalController::Run() {
    while (true) {
        int16_t code = 0;
        const bool ok = adc_->ReadSingleEnded(THERMAL_NTC_CHANNEL, &code);
        const int64_t now_ms = esp_timer_get_time() / 1000;
        if (ok)
            ApplySample(code, now_ms);
        else
            ApplyReadFailure(now_ms);
        vTaskDelay(pdMS_TO_TICKS(THERMAL_POLL_INTERVAL_MS));
    }
}

int ThermalController::CodeToDeciC(int16_t code) {
    if (code >= kCodeTable[0])
        return kTableMinDc;
    for (int i = 0; i + 1 < kTableSize; ++i) {
        if (code > kCodeTable[i + 1]) {
            const int span = kCodeTable[i] - kCodeTable[i + 1];
            return kTableMinDc + i * kTableStepDc + (kCodeTable[i] - code) * kTableStepDc / span;
        }
    }
    return kTableMinDc + (kTableSize - 1) * kTableStepDc;
}

const char* ThermalController::StateName(ThermalState state) {
    switch (state) {
    case ThermalState::kOff: return "off";
    case ThermalState::kHeating: return "heating";
    case ThermalState::kFault: return "fault";
    }
    return "unknown";
}

const char* ThermalController::FaultName(ThermalFault fault) {
    switch (fault) {
    case ThermalFault::kNone: return "none";
    case ThermalFault::kSensorOutOfRange: return "sensor_out_of_range";
    case ThermalFault::kOverTemp: return "over_temp";
    case ThermalFault::kRiseTooFast: return "rise_too_fast";
    case ThermalFault::kProbeDetached: return "probe_detached";
    case ThermalFault::kSessionExpired: return "session_expired";
    }
    return "unknown";
}

void ThermalController::ApplySample(int16_t code, int64_t now_ms) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (code < THERMAL_CODE_MIN || code > THERMAL_CODE_MAX) {
        RejectSample(now_ms);
        return;
    }
    consecutive_bad_ = 0;
    last_code_ = code;
    temp_dc_ = CodeToDeciC(code);
    has_temp_ = true;

    // 过温不论是否在加热都闭锁：温度读数本身可能来自一次失控的加热。
    if (temp_dc_ >= THERMAL_OVERTEMP_DC && state_ != ThermalState::kFault) {
        ESP_LOGE(TAG, "过温 %d.%d℃，闭锁", temp_dc_ / 10, temp_dc_ % 10);
        EnterFault(ThermalFault::kOverTemp);
    }
    if (state_ == ThermalState::kHeating)
        CheckHeatingSafety(now_ms);
    UpdateOutput(now_ms);
}

void ThermalController::ApplyReadFailure(int64_t now_ms) {
    std::lock_guard<std::mutex> lock(mutex_);
    RejectSample(now_ms);
}

void ThermalController::RejectSample(int64_t now_ms) {
    ++rejected_;
    if (++consecutive_bad_ >= THERMAL_BAD_SAMPLE_LIMIT && state_ != ThermalState::kFault) {
        ESP_LOGE(TAG, "连续 %d 个坏样本，判定传感器故障", consecutive_bad_);
        EnterFault(ThermalFault::kSensorOutOfRange);
    }
    // 坏样本期间仍按时间推进窗口：导通段照常按时结束，不因读不到而延长。
    if (state_ == ThermalState::kHeating &&
        now_ms - session_start_ms_ >= THERMAL_SESSION_MAX_MS) {
        state_ = ThermalState::kOff;
        fault_ = ThermalFault::kSessionExpired;
    }
    UpdateOutput(now_ms);
}

void ThermalController::CheckHeatingSafety(int64_t now_ms) {
    if (now_ms - session_start_ms_ >= THERMAL_SESSION_MAX_MS) {
        ESP_LOGI(TAG, "加热会话到时，自动关闭");
        state_ = ThermalState::kOff;
        fault_ = ThermalFault::kSessionExpired;
        forced_duty_ = -1;
        return;
    }

    // 升温速率：与 60 秒内任一快照比较，而不是只和窗口起点比 ——
    // 后者会把跨越窗口边界的快速升温拆成两段，各自都不超限。
    for (int i = 0; i < snapshot_count_; ++i) {
        const Snapshot& s = snapshots_[i];
        if (now_ms - s.t_ms <= THERMAL_RISE_WINDOW_MS &&
            temp_dc_ - s.temp_dc > THERMAL_RISE_LIMIT_DC) {
            ESP_LOGE(TAG, "升温过快：%d → %d（0.1℃）", s.temp_dc, temp_dc_);
            EnterFault(ThermalFault::kRiseTooFast);
            return;
        }
    }
    if (now_ms - last_snapshot_ms_ >= kSnapshotIntervalMs) {
        snapshots_[snapshot_head_] = {now_ms, temp_dc_};
        snapshot_head_ = (snapshot_head_ + 1) % kRiseSnapshots;
        snapshot_count_ = std::min(snapshot_count_ + 1, kRiseSnapshots);
        last_snapshot_ms_ = now_ms;
    }

    // 探头失联：只在占空比顶到门槛时计时，接近目标时占空比回落，本就不该有明显温升。
    if (duty_ >= THERMAL_DETACH_DUTY_PCT) {
        if (detach_start_ms_ < 0) {
            detach_start_ms_ = now_ms;
            detach_start_temp_dc_ = temp_dc_;
        } else if (now_ms - detach_start_ms_ >= THERMAL_DETACH_WINDOW_MS) {
            if (temp_dc_ - detach_start_temp_dc_ < THERMAL_DETACH_RISE_DC) {
                ESP_LOGE(TAG, "满占空比 %d 秒温升不足，判定探头失联",
                         (int)(THERMAL_DETACH_WINDOW_MS / 1000));
                EnterFault(ThermalFault::kProbeDetached);
                return;
            }
            detach_start_ms_ = now_ms;
            detach_start_temp_dc_ = temp_dc_;
        }
    } else {
        detach_start_ms_ = -1;
    }
}

void ThermalController::EnterFault(ThermalFault fault) {
    state_ = ThermalState::kFault;
    fault_ = fault;
    forced_duty_ = -1;
    duty_ = 0;
    DriveHeater(false);
}

void ThermalController::BeginSession(int64_t now_ms) {
    state_ = ThermalState::kHeating;
    fault_ = ThermalFault::kNone;
    session_start_ms_ = now_ms;
    window_start_ms_ = now_ms;
    detach_start_ms_ = -1;
    snapshots_[0] = {now_ms, temp_dc_};
    snapshot_count_ = 1;
    snapshot_head_ = 1;
    last_snapshot_ms_ = now_ms;
    duty_ = ComputeDuty();
}

bool ThermalController::RequestHeating(int target_dc, int64_t now_ms) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (state_ == ThermalState::kFault || !has_temp_ || consecutive_bad_ > 0)
        return false;
    target_dc_ = std::clamp(target_dc, 0, THERMAL_TARGET_MAX_DC);
    forced_duty_ = -1;
    BeginSession(now_ms);
    UpdateOutput(now_ms);
    return true;
}

bool ThermalController::ForceDuty(int percent, int64_t now_ms) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (state_ == ThermalState::kFault || !has_temp_ || consecutive_bad_ > 0)
        return false;
    forced_duty_ = std::clamp(percent, 0, THERMAL_DUTY_MAX_PCT);
    BeginSession(now_ms);
    UpdateOutput(now_ms);
    return true;
}

void ThermalController::Stop() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (state_ == ThermalState::kHeating) {
        state_ = ThermalState::kOff;
        fault_ = ThermalFault::kNone;
    }
    forced_duty_ = -1;
    duty_ = 0;
    DriveHeater(false);
}

void ThermalController::ClearFault() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (state_ != ThermalState::kFault)
        return;
    state_ = ThermalState::kOff;
    fault_ = ThermalFault::kNone;
    consecutive_bad_ = 0;
    DriveHeater(false);
}

int ThermalController::ComputeDuty() const {
    if (forced_duty_ >= 0)
        return std::min(forced_duty_, THERMAL_DUTY_MAX_PCT);
    const int error_dc = target_dc_ - temp_dc_;
    return std::clamp(error_dc * THERMAL_KP_PERMILLE / 1000, 0, THERMAL_DUTY_MAX_PCT);
}

void ThermalController::UpdateOutput(int64_t now_ms) {
    if (state_ != ThermalState::kHeating) {
        duty_ = 0;
        DriveHeater(false);
        return;
    }
    if (now_ms - window_start_ms_ >= THERMAL_WINDOW_MS) {
        // 从当前时刻重新起窗，而不是累加：轮询卡顿后不会连补几个窗口。
        window_start_ms_ = now_ms;
        duty_ = ComputeDuty();
    }
    const int64_t on_ms = (int64_t)THERMAL_WINDOW_MS * duty_ / 100;
    bool on = now_ms - window_start_ms_ < on_ms;
    // 被抑制的导通时间不补偿。
    if (on && suppressor_ && suppressor_())
        on = false;
    DriveHeater(on);
}

void ThermalController::DriveHeater(bool on) {
    if (output_known_ && on == heater_on_)
        return;
    heater_on_ = on;
    output_known_ = sink_ ? sink_(on) : true;
}

ThermalState ThermalController::state() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return state_;
}

ThermalFault ThermalController::fault() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return fault_;
}

bool ThermalController::has_temperature() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return has_temp_;
}

int ThermalController::temperature_dc() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return temp_dc_;
}

int ThermalController::last_code() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return last_code_;
}

int ThermalController::target_dc() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return target_dc_;
}

int ThermalController::duty_percent() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return duty_;
}

bool ThermalController::heater_on() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return heater_on_;
}

int ThermalController::rejected_samples() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return rejected_;
}

int64_t ThermalController::session_ms(int64_t now_ms) const {
    std::lock_guard<std::mutex> lock(mutex_);
    return state_ == ThermalState::kHeating ? now_ms - session_start_ms_ : 0;
}
