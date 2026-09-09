#include "pca9685.h"

#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include <cstdio>

#define TAG "Pca9685"

namespace {
constexpr uint8_t kRegMode1 = 0x00;
constexpr uint8_t kRegMode2 = 0x01;
constexpr uint8_t kRegLed0OnL = 0x06;
constexpr uint8_t kRegPrescale = 0xFE;

constexpr uint8_t kMode1Restart = 0x80;
constexpr uint8_t kMode1AutoInc = 0x20;
constexpr uint8_t kMode1Sleep = 0x10;
constexpr uint8_t kMode1AllCall = 0x01;
constexpr uint8_t kMode2OutDrv = 0x04;

constexpr int kPwmPeriodUs = 20000;  // 50Hz
constexpr int kPwmSteps = 4096;      // 12 位分辨率
constexpr int kTimeoutMs = 1000;
constexpr int kServoChannelCount = 2;

bool SoftwareReset(i2c_master_bus_handle_t bus, uint32_t scl_hz) {
    i2c_device_config_t cfg = {};
    cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    cfg.device_address = 0x00;  // PCA9685 SWRST General Call address
    cfg.scl_speed_hz = scl_hz;

    i2c_master_dev_handle_t reset_device = nullptr;
    esp_err_t err = i2c_master_bus_add_device(bus, &cfg, &reset_device);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "挂载软件复位地址失败: %s", esp_err_to_name(err));
        return false;
    }
    uint8_t command = 0x06;
    err = i2c_master_transmit(reset_device, &command, 1, kTimeoutMs);
    i2c_master_bus_rm_device(reset_device);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "PCA9685 软件复位失败: %s", esp_err_to_name(err));
        return false;
    }
    vTaskDelay(pdMS_TO_TICKS(1));
    return true;
}
}  // namespace

Pca9685::Pca9685(i2c_master_bus_handle_t bus, uint8_t addr, uint32_t scl_hz) {
    SoftwareReset(bus, scl_hz);

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

Pca9685::~Pca9685() {
    if (dev_ != nullptr) {
        i2c_master_bus_rm_device(dev_);
    }
}

bool Pca9685::WriteReg(uint8_t reg, uint8_t value) {
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

bool Pca9685::ReadRegisters(uint8_t reg, uint8_t* data, size_t size) {
    if (dev_ == nullptr)
        return false;
    esp_err_t err = i2c_master_transmit_receive(dev_, &reg, 1, data, size, kTimeoutMs);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "读寄存器 0x%02X 失败: %s", reg, esp_err_to_name(err));
        return false;
    }
    return true;
}

uint8_t Pca9685::ReadPrescale() {
    uint8_t out = 0;
    if (!ReadRegisters(kRegPrescale, &out, 1)) {
        return 0;
    }
    return out;
}

std::string Pca9685::Diagnostics() {
    uint8_t mode1 = 0;
    uint8_t mode2 = 0;
    uint8_t prescale = 0;
    uint8_t channels[8] = {};
    if (!ReadRegisters(kRegMode1, &mode1, 1) || !ReadRegisters(kRegMode2, &mode2, 1) ||
        !ReadRegisters(kRegPrescale, &prescale, 1) ||
        !ReadRegisters(kRegLed0OnL, channels, sizeof(channels))) {
        return "read_failed";
    }

    uint16_t ch0_off = channels[2] | ((channels[3] & 0x0F) << 8);
    uint16_t ch1_off = channels[6] | ((channels[7] & 0x0F) << 8);
    char result[160];
    std::snprintf(result, sizeof(result),
                  "mode1=0x%02X mode2=0x%02X prescale=%u output_mode=per_channel "
                  "ch0_off=%u ch1_off=%u last_write_error=%s",
                  mode1, mode2, prescale, ch0_off, ch1_off, esp_err_to_name(last_write_error_));
    return result;
}

bool Pca9685::Init(int freq_hz) {
    if (dev_ == nullptr)
        return false;

    // 改 PRE_SCALE 前必须先进睡眠，这是芯片的硬性要求
    if (!WriteReg(kRegMode1, kMode1Sleep))
        return false;
    vTaskDelay(pdMS_TO_TICKS(5));

    uint8_t prescale = (uint8_t)((25000000.0 / (4096.0 * freq_hz)) + 0.5) - 1;
    if (!WriteReg(kRegPrescale, prescale))
        return false;

    if (!WriteReg(kRegMode1, kMode1AutoInc | kMode1AllCall))
        return false;
    vTaskDelay(pdMS_TO_TICKS(5));
    if (!WriteReg(kRegMode1, kMode1Restart | kMode1AutoInc | kMode1AllCall))
        return false;
    if (!WriteReg(kRegMode2, kMode2OutDrv))
        return false;

    uint8_t back = ReadPrescale();
    if (back != prescale) {
        ESP_LOGE(TAG, "PRE_SCALE 回读 %u，期望 %u —— 芯片未正确响应（时钟过高或接线不良）", back,
                 prescale);
        return false;
    }
    ESP_LOGI(TAG, "初始化完成，%d Hz，PRE_SCALE=%u", freq_hz, prescale);
    return true;
}

void Pca9685::SetPulseUs(int ch, int us) {
    if (dev_ == nullptr)
        return;
    uint16_t off = (uint16_t)((us * kPwmSteps) / kPwmPeriodUs);
    // 一路占 4 个连续寄存器，用突发写一次发完，避免中途被打断产生半个脉宽
    uint8_t buf[5] = {
        (uint8_t)(kRegLed0OnL + 4 * ch), 0x00, 0x00,  // ON 计数固定为 0
        (uint8_t)(off & 0xFF),                        // OFF_L
        (uint8_t)((off >> 8) & 0x0F),                 // OFF_H
    };
    esp_err_t err = i2c_master_transmit(dev_, buf, sizeof(buf), kTimeoutMs);
    if (err != ESP_OK) {
        last_write_error_ = err;
        ESP_LOGE(TAG, "写通道 %d 脉宽失败: %s", ch, esp_err_to_name(err));
    } else {
        last_write_error_ = ESP_OK;
    }
}

void Pca9685::AllOff() {
    if (dev_ == nullptr)
        return;

    // 不使用 ALL_LED_OFF_H 的全局关闭闸门。该寄存器是写入即生效且不可回读，
    // 一旦恢复写入丢失会静默所有通道。逐通道置 FULL_OFF 后，下一次 SetPulseUs 的
    // 连续四字节写会天然清除该通道的 bit4 并恢复 PWM。
    for (int ch = 0; ch < kServoChannelCount; ++ch) {
        const uint8_t off_h = kRegLed0OnL + 4 * ch + 3;
        if (!WriteReg(off_h, 0x10)) {
            ESP_LOGE(TAG, "关闭通道 %d 输出失败", ch);
        }
    }
}
