#pragma once

#include "ads1115.h"
#include "config.h"

#include <functional>
#include <mutex>

enum class ThermalState { kOff, kHeating, kFault };
enum class ThermalFault {
    kNone,
    kSensorOutOfRange,
    kOverTemp,
    kRiseTooFast,
    kProbeDetached,
    kSessionExpired,   // 不闭锁：状态回到 kOff，重新请求即可
};

// 体温控制。把 NTC 码值变成加热决策，全部安全逻辑都在这里。
// 设计见 docs/superpowers/specs/2026-09-10-plush-toy-thermal-design.md 第 3、5 节。
//
// 【安全分层】每层独立生效：
//   1. 合理性闸门：码值越界或 I2C 读失败连续 THERMAL_BAD_SAMPLE_LIMIT 次 → 故障
//   2. 过温闭锁：≥ THERMAL_OVERTEMP_DC → 故障，温度降回也不自动恢复
//   3. 升温过快（任意 60 秒内 > 10℃）与探头失联（满占空比 2 分钟升温 < 1℃）→ 故障
//   4. 与读数无关的时间预算：占空比硬上限、单次会话 30 分钟
//   5. 硬件 KSD9700（不在固件里）
//   6. 默认关闭，只有显式请求才加热
// 故障只能由 ClearFault() 或重启清除。
//
// 【控制】10 秒窗口的时间比例控制，比例 + 硬上限，不做积分。
//
// 时间由调用方传入而非内部读时钟，与 MotionController 同理：所有超时与速率
// 判定必须能在主机侧确定性复现。
//
// 【线程】轮询任务、MCP/HTTP 命令、status 读取来自不同任务，内部加锁。
class ThermalController {
public:
    // 返回 false 表示写失败。控制器会在下个周期重发，不假设已经生效。
    using HeaterSink = std::function<bool(bool on)>;
    // 返回 true 表示当前必须断开加热（舵机动作期间，避免与舵机抢 5V 轨）。
    using Suppressor = std::function<bool()>;

    explicit ThermalController(Ads1115* adc);

    bool available() const { return adc_ != nullptr; }
    void SetHeaterSink(HeaterSink sink);
    void SetSuppressor(Suppressor suppressor);
    void Start();

    // 公开供三处使用：主机侧单测、测试通道的模拟采样、轮询任务自身。
    void ApplySample(int16_t code, int64_t now_ms);
    // I2C 读失败。与坏样本同等对待：若只是跳过，加热会停在上一次的输出上。
    void ApplyReadFailure(int64_t now_ms);

    // 请求加热到目标温度（0.1℃），截断到 THERMAL_TARGET_MAX_DC。
    // 故障态或尚无有效温度时返回 false。
    bool RequestHeating(int target_dc, int64_t now_ms);
    // 标定专用：绕过比例控制直接定占空比。仍受硬上限与全部保护约束。
    bool ForceDuty(int percent, int64_t now_ms);
    void Stop();
    void ClearFault();

    ThermalState state() const;
    ThermalFault fault() const;
    bool has_temperature() const;
    int temperature_dc() const;
    int last_code() const;
    int target_dc() const;
    int duty_percent() const;
    bool heater_on() const;
    int rejected_samples() const;
    int64_t session_ms(int64_t now_ms) const;

    static int CodeToDeciC(int16_t code);
    static const char* StateName(ThermalState state);
    static const char* FaultName(ThermalFault fault);

private:
    static constexpr int kRiseSnapshots = 7;

    static void TaskEntry(void* arg);
    void Run();

    // 以下均要求已持锁
    void RejectSample(int64_t now_ms);
    void CheckHeatingSafety(int64_t now_ms);
    void EnterFault(ThermalFault fault);
    void BeginSession(int64_t now_ms);
    int ComputeDuty() const;
    void UpdateOutput(int64_t now_ms);
    void DriveHeater(bool on);

    Ads1115* adc_ = nullptr;
    HeaterSink sink_;
    Suppressor suppressor_;
    mutable std::mutex mutex_;

    ThermalState state_ = ThermalState::kOff;
    ThermalFault fault_ = ThermalFault::kNone;
    bool has_temp_ = false;
    int temp_dc_ = 0;
    int last_code_ = 0;
    int target_dc_ = THERMAL_TARGET_DEFAULT_DC;
    int forced_duty_ = -1;   // < 0 表示走比例控制
    int duty_ = 0;
    int consecutive_bad_ = 0;
    int rejected_ = 0;

    bool heater_on_ = false;
    // 上电时输出状态未知，首个周期无条件写一次 false；写失败后同样置为未知。
    bool output_known_ = false;

    int64_t session_start_ms_ = 0;
    int64_t window_start_ms_ = 0;
    int64_t detach_start_ms_ = -1;
    int detach_start_temp_dc_ = 0;

    struct Snapshot {
        int64_t t_ms;
        int temp_dc;
    };
    Snapshot snapshots_[kRiseSnapshots] = {};
    int snapshot_count_ = 0;
    int snapshot_head_ = 0;
    int64_t last_snapshot_ms_ = 0;
};
