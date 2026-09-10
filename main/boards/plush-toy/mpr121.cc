#include "mpr121.h"
#include "config.h"

#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include <cstdio>

#define TAG "Mpr121"

namespace {
constexpr uint8_t kRegTouchStatus = 0x00;
constexpr uint8_t kRegFiltered0 = 0x04;
constexpr uint8_t kRegBaseline0 = 0x1E;
constexpr uint8_t kRegThreshold0 = 0x41;  // 每个电极两字节：触摸、释放
constexpr uint8_t kRegDebounce = 0x5B;
constexpr uint8_t kRegConfig1 = 0x5C;
constexpr uint8_t kRegConfig2 = 0x5D;
constexpr uint8_t kRegEcr = 0x5E;
constexpr uint8_t kRegSoftReset = 0x80;

constexpr uint8_t kSoftResetMagic = 0x63;
constexpr uint8_t kEcrRun = 0x8F;  // 基线跟踪 + 启用全部 12 个电极
constexpr int kTimeoutMs = 1000;

// 基线滤波参数取自 NXP AN3944 的推荐配置。
constexpr uint8_t kBaselineFilter[][2] = {
    {0x2B, 0x01}, {0x2C, 0x01}, {0x2D, 0x00}, {0x2E, 0x00},
    {0x2F, 0x01}, {0x30, 0x05}, {0x31, 0x01}, {0x32, 0x00},
};
}  // namespace

Mpr121::Mpr121(i2c_master_bus_handle_t bus, uint8_t addr, uint32_t scl_hz) {
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

Mpr121::~Mpr121() {
    if (dev_ != nullptr)
        i2c_master_bus_rm_device(dev_);
}

bool Mpr121::WriteReg(uint8_t reg, uint8_t value) {
    if (dev_ == nullptr)
        return false;
    uint8_t buf[2] = {reg, value};
    esp_err_t err = i2c_master_transmit(dev_, buf, sizeof(buf), kTimeoutMs);
    if (err != ESP_OK) {
        last_write_error_ = err;
        ESP_LOGE(TAG, "写寄存器 0x%02X 失败: %s", reg, esp_err_to_name(err));
        return false;
    }
    last_write_error_ = ESP_OK;
    return true;
}

bool Mpr121::ReadRegisters(uint8_t reg, uint8_t* data, size_t size) {
    if (dev_ == nullptr)
        return false;
    esp_err_t err = i2c_master_transmit_receive(dev_, &reg, 1, data, size, kTimeoutMs);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "读寄存器 0x%02X 失败: %s", reg, esp_err_to_name(err));
        return false;
    }
    return true;
}

bool Mpr121::Init() {
    if (dev_ == nullptr)
        return false;

    if (!WriteReg(kRegSoftReset, kSoftResetMagic))
        return false;
    vTaskDelay(pdMS_TO_TICKS(2));

    // 配置寄存器只在停机状态下可写，这是芯片的硬性要求
    if (!WriteReg(kRegEcr, 0x00))
        return false;

    for (const auto& pair : kBaselineFilter) {
        if (!WriteReg(pair[0], pair[1]))
            return false;
    }

    for (int ch = 0; ch < TOUCH_ELECTRODE_COUNT; ++ch) {
        const uint8_t base = (uint8_t)(kRegThreshold0 + 2 * ch);
        if (!WriteReg(base, TOUCH_PRESS_THRESHOLD) ||
            !WriteReg((uint8_t)(base + 1), TOUCH_RELEASE_THRESHOLD))
            return false;
    }

    if (!WriteReg(kRegDebounce, 0x22))  // 触摸与释放各需连续 2 次采样一致
        return false;
    if (!WriteReg(kRegConfig1, 0x10) || !WriteReg(kRegConfig2, 0x20))
        return false;
    if (!WriteReg(kRegEcr, kEcrRun))
        return false;

    uint8_t back = 0;
    if (!ReadRegisters(kRegThreshold0, &back, 1) || back != TOUCH_PRESS_THRESHOLD) {
        ESP_LOGE(TAG, "阈值回读 0x%02X，期望 0x%02X —— 芯片未正确响应（接线或地址不对）", back,
                 TOUCH_PRESS_THRESHOLD);
        return false;
    }
    ESP_LOGI(TAG, "初始化完成，%d 电极，触摸阈值 0x%02X", TOUCH_ELECTRODE_COUNT,
             TOUCH_PRESS_THRESHOLD);
    return true;
}

uint16_t Mpr121::ReadTouchBits() {
    uint8_t raw[2] = {};
    if (!ReadRegisters(kRegTouchStatus, raw, sizeof(raw)))
        return 0;
    return (uint16_t)((raw[0] | (raw[1] << 8)) & 0x0FFF);
}

uint16_t Mpr121::ReadFiltered(int ch) {
    if (ch < 0 || ch >= TOUCH_ELECTRODE_COUNT)
        return 0;
    uint8_t raw[2] = {};
    if (!ReadRegisters((uint8_t)(kRegFiltered0 + 2 * ch), raw, sizeof(raw)))
        return 0;
    return (uint16_t)(raw[0] | (raw[1] << 8));
}

uint16_t Mpr121::ReadBaseline(int ch) {
    if (ch < 0 || ch >= TOUCH_ELECTRODE_COUNT)
        return 0;
    uint8_t raw = 0;
    if (!ReadRegisters((uint8_t)(kRegBaseline0 + ch), &raw, 1))
        return 0;
    return (uint16_t)(raw << 2);  // 寄存器存的是实际基线右移两位
}

std::string Mpr121::Diagnostics() {
    uint8_t ecr = 0;
    uint8_t threshold = 0;
    if (!ReadRegisters(kRegEcr, &ecr, 1) || !ReadRegisters(kRegThreshold0, &threshold, 1))
        return "read_failed";
    char result[160];
    std::snprintf(result, sizeof(result),
                  "ecr=0x%02X touch_threshold=0x%02X touch_bits=0x%03X "
                  "e0_filtered=%u e0_baseline=%u last_write_error=%s",
                  ecr, threshold, ReadTouchBits(), ReadFiltered(TOUCH_HEAD_ELECTRODE),
                  ReadBaseline(TOUCH_HEAD_ELECTRODE), esp_err_to_name(last_write_error_));
    return result;
}
