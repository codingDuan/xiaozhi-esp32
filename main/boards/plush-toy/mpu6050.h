#pragma once

#include <driver/i2c_master.h>
#include <stdint.h>
#include <string>

// MPU6050 六轴传感器驱动。本项目只读加速度计。
//
// 【为什么不读陀螺仪】
// 姿态由重力方向得出，摇晃由加速度幅值判定，两者都不需要角速度。
// 少读 6 个字节，也少一组要标定的参数。寄存器随时可以加。
//
// 【为什么轮询】
// 引脚已用尽，INT 无处可接。姿态与摇晃都不需要毫秒级响应。
//
// 【为什么不继承 I2cDevice】
// 同 pca9685.h / mpr121.h：该基类把 scl_speed_hz 硬编码为 400kHz。
class Mpu6050 {
public:
    Mpu6050(i2c_master_bus_handle_t bus, uint8_t addr, uint32_t scl_hz);
    ~Mpu6050();

    bool available() const { return dev_ != nullptr; }

    // 复位、解除睡眠、设量程与低通，末尾校验 WHO_AM_I 并回读量程寄存器。
    // 只查 WHO_AM_I 不够 —— 它区分不了「能读不能写」。
    bool Init();

    // 一次突发读 6 字节，保证三轴来自同一采样时刻。
    // 失败返回 false 且不改写出参：加速度的 0 是合法值，不能用哨兵值报错。
    bool ReadAccel(int16_t& x, int16_t& y, int16_t& z);

    std::string Diagnostics();

private:
    bool WriteReg(uint8_t reg, uint8_t value);
    bool ReadRegisters(uint8_t reg, uint8_t* data, size_t size);

    i2c_master_dev_handle_t dev_ = nullptr;
    esp_err_t last_write_error_ = ESP_OK;
};
