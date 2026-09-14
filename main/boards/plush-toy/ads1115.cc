#include "ads1115.h"

#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include <cstdio>

#define TAG "Ads1115"

namespace {
constexpr uint8_t kRegConversion = 0x00;
constexpr uint8_t kRegConfig = 0x01;

// 配置寄存器位域
constexpr uint16_t kOsStart = 0x8000;       // 写 1 触发单次转换；读 1 表示空闲
constexpr int kMuxShift = 12;
constexpr uint16_t kMuxSingleA0 = 0x4;      // 100：AIN0 对 GND，AINn = 0x4 + n
constexpr uint16_t kPga4096 = 0x0200;       // 001：±4.096V
constexpr uint16_t kModeSingleShot = 0x0100;
constexpr uint16_t kDr128Sps = 0x0080;      // 100：128SPS
constexpr uint16_t kCompQueueDisable = 0x0003;
constexpr uint16_t kBaseConfig = kPga4096 | kModeSingleShot | kDr128Sps | kCompQueueDisable;

// 128SPS 一次转换 7.8ms，先等 9ms 再查，之后每 2ms 查一次，最多查 5 次，
// 仍未完成就判定失败，不返回旧结果。
constexpr int kFirstWaitMs = 9;
constexpr int kPollWaitMs = 2;
constexpr int kPollAttempts = 5;
constexpr int kTimeoutMs = 1000;

// 本工程 CONFIG_FREERTOS_HZ=100，一个 tick 10ms，pdMS_TO_TICKS 向下取整，
// 9ms 和 2ms 都会变成 0 tick —— 根本不等待，转换还没做完就轮询完判超时。
// 实机上曾因此 thermal_code 一次都读不出来。至少等 1 tick。
int TicksAtLeast(int ms) {
    const int ticks = (int)pdMS_TO_TICKS(ms);
    return ticks > 0 ? ticks : 1;
}

uint16_t ConfigFor(int channel) {
    return (uint16_t)(((kMuxSingleA0 + channel) << kMuxShift) | kBaseConfig);
}
}  // namespace

Ads1115::Ads1115(i2c_master_bus_handle_t bus, uint8_t addr, uint32_t scl_hz) {
    i2c_device_config_t cfg = {};
    cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    cfg.device_address = addr;
    cfg.scl_speed_hz = scl_hz;
    esp_err_t err = i2c_master_bus_add_device(bus, &cfg, &dev_);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "挂载设备失败: %s", esp_err_to_name(err));
        dev_ = nullptr;
    }
}

Ads1115::~Ads1115() {
    if (dev_ != nullptr)
        i2c_master_bus_rm_device(dev_);
}

bool Ads1115::WriteRegister(uint8_t reg, uint16_t value) {
    if (dev_ == nullptr)
        return false;
    uint8_t buf[3] = {reg, (uint8_t)(value >> 8), (uint8_t)(value & 0xFF)};  // 大端
    esp_err_t err = i2c_master_transmit(dev_, buf, sizeof(buf), kTimeoutMs);
    if (err != ESP_OK) {
        last_write_error_ = err;
        ESP_LOGE(TAG, "写寄存器 0x%02X 失败: %s", reg, esp_err_to_name(err));
        return false;
    }
    last_write_error_ = ESP_OK;
    return true;
}

bool Ads1115::ReadRegister(uint8_t reg, uint16_t* value) {
    if (dev_ == nullptr)
        return false;
    uint8_t raw[2] = {};
    esp_err_t err = i2c_master_transmit_receive(dev_, &reg, 1, raw, sizeof(raw), kTimeoutMs);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "读寄存器 0x%02X 失败: %s", reg, esp_err_to_name(err));
        return false;
    }
    *value = (uint16_t)((raw[0] << 8) | raw[1]);
    return true;
}

bool Ads1115::Init() {
    if (dev_ == nullptr)
        return false;
    // 写入时不带 OS 位：初始化只配置，不触发转换。
    const uint16_t config = ConfigFor(0);
    if (!WriteRegister(kRegConfig, config))
        return false;

    uint16_t back = 0;
    // OS 位读回语义与写入不同（读 1 = 空闲），比较时屏蔽。
    if (!ReadRegister(kRegConfig, &back) || (back & ~kOsStart) != config) {
        ESP_LOGE(TAG, "配置回读 0x%04X，期望 0x%04X —— 写通路不通或地址上不是 ADS1115", back,
                 config);
        return false;
    }
    ESP_LOGI(TAG, "初始化完成，±4.096V，128SPS，单次模式");
    return true;
}

bool Ads1115::ReadSingleEnded(int channel, int16_t* code) {
    if (dev_ == nullptr || code == nullptr || channel < 0 || channel > 3)
        return false;
    if (!WriteRegister(kRegConfig, (uint16_t)(ConfigFor(channel) | kOsStart)))
        return false;

    vTaskDelay(TicksAtLeast(kFirstWaitMs));
    bool done = false;
    for (int i = 0; i < kPollAttempts; ++i) {
        uint16_t config = 0;
        if (!ReadRegister(kRegConfig, &config))
            return false;
        if ((config & kOsStart) != 0) {
            done = true;
            break;
        }
        vTaskDelay(TicksAtLeast(kPollWaitMs));
    }
    if (!done) {
        ESP_LOGW(TAG, "A%d 转换超时", channel);
        return false;
    }

    uint16_t raw = 0;
    if (!ReadRegister(kRegConversion, &raw))
        return false;
    *code = (int16_t)raw;
    return true;
}

std::string Ads1115::Diagnostics() {
    uint16_t config = 0;
    int16_t a0 = 0;
    if (!ReadRegister(kRegConfig, &config) || !ReadSingleEnded(0, &a0))
        return "read_failed";
    char result[96];
    std::snprintf(result, sizeof(result), "config=0x%04X a0=%d last_write_error=%s", config, a0,
                  esp_err_to_name(last_write_error_));
    return result;
}
