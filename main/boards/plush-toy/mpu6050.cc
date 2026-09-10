#include "mpu6050.h"
#include "config.h"

#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include <cstdio>

#define TAG "Mpu6050"

namespace {
constexpr uint8_t kRegConfig = 0x1A;
constexpr uint8_t kRegAccelConfig = 0x1C;
constexpr uint8_t kRegAccelXoutH = 0x3B;
constexpr uint8_t kRegPwrMgmt1 = 0x6B;
constexpr uint8_t kRegWhoAmI = 0x75;

constexpr uint8_t kDeviceReset = 0x80;
constexpr uint8_t kWhoAmIExpected = 0x68;
// DLPF 44Hz：舵机振动的高频分量在进入判定之前就被滤掉一部分。
constexpr uint8_t kDlpf44Hz = 0x03;
constexpr int kTimeoutMs = 1000;
}  // namespace

Mpu6050::Mpu6050(i2c_master_bus_handle_t bus, uint8_t addr, uint32_t scl_hz) {
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

Mpu6050::~Mpu6050() {
    if (dev_ != nullptr)
        i2c_master_bus_rm_device(dev_);
}

bool Mpu6050::WriteReg(uint8_t reg, uint8_t value) {
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

bool Mpu6050::ReadRegisters(uint8_t reg, uint8_t* data, size_t size) {
    if (dev_ == nullptr)
        return false;
    esp_err_t err = i2c_master_transmit_receive(dev_, &reg, 1, data, size, kTimeoutMs);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "读寄存器 0x%02X 失败: %s", reg, esp_err_to_name(err));
        return false;
    }
    return true;
}

bool Mpu6050::Init() {
    if (dev_ == nullptr)
        return false;

    uint8_t who = 0;
    if (!ReadRegisters(kRegWhoAmI, &who, 1) || who != kWhoAmIExpected) {
        ESP_LOGE(TAG, "WHO_AM_I 读到 0x%02X，期望 0x%02X —— 地址不对或不是 MPU6050", who,
                 kWhoAmIExpected);
        return false;
    }

    if (!WriteReg(kRegPwrMgmt1, kDeviceReset))
        return false;
    vTaskDelay(pdMS_TO_TICKS(100));     // 复位后芯片需要时间稳定
    if (!WriteReg(kRegPwrMgmt1, 0x00))  // 解除睡眠
        return false;
    if (!WriteReg(kRegConfig, kDlpf44Hz))
        return false;
    if (!WriteReg(kRegAccelConfig, MOTION_ACCEL_FS_SEL))
        return false;

    uint8_t back = 0;
    if (!ReadRegisters(kRegAccelConfig, &back, 1) || back != MOTION_ACCEL_FS_SEL) {
        ESP_LOGE(TAG, "量程回读 0x%02X，期望 0x%02X —— 写通路不通", back, MOTION_ACCEL_FS_SEL);
        return false;
    }
    ESP_LOGI(TAG, "初始化完成，±4g，%d LSB/g", MOTION_LSB_PER_G);
    return true;
}

bool Mpu6050::ReadAccel(int16_t& x, int16_t& y, int16_t& z) {
    uint8_t raw[6] = {};
    if (!ReadRegisters(kRegAccelXoutH, raw, sizeof(raw)))
        return false;
    x = (int16_t)((raw[0] << 8) | raw[1]);  // MPU6050 是大端，与 MPR121 相反
    y = (int16_t)((raw[2] << 8) | raw[3]);
    z = (int16_t)((raw[4] << 8) | raw[5]);
    return true;
}

std::string Mpu6050::Diagnostics() {
    uint8_t who = 0;
    uint8_t range = 0;
    int16_t x = 0, y = 0, z = 0;
    if (!ReadRegisters(kRegWhoAmI, &who, 1) || !ReadRegisters(kRegAccelConfig, &range, 1) ||
        !ReadAccel(x, y, z))
        return "read_failed";
    char result[160];
    std::snprintf(result, sizeof(result),
                  "who_am_i=0x%02X range=0x%02X ax=%d ay=%d az=%d last_write_error=%s", who, range,
                  x, y, z, esp_err_to_name(last_write_error_));
    return result;
}
