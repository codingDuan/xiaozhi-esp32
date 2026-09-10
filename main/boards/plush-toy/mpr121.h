#pragma once

#include <driver/i2c_master.h>
#include <stdint.h>
#include <string>

// MPR121 12 通道电容触摸驱动。本期只接一个头部电极，但驱动按 12 通道实现。
//
// 【为什么轮询而不用 IRQ】
// ESP32-S3 引脚已用尽：GPIO0-21 与 38-48 被摄像头、双眼屏、音频、舵机 I2C 和
// 原生 USB 占完，26-32 是 flash，33-37 被八线 PSRAM 占用。IRQ 无处可接。
// 代价可以接受：去抖由芯片的 DEBOUNCE 寄存器(0x5B)完成，软件只比较状态位。
//
// 【为什么不继承 I2cDevice】
// 同 pca9685.h：该基类把 scl_speed_hz 硬编码为 400kHz，本项目面包板飞线上
// 会导致寄存器读写失真。此处自持 device handle。
class Mpr121 {
public:
    Mpr121(i2c_master_bus_handle_t bus, uint8_t addr, uint32_t scl_hz);
    ~Mpr121();

    bool available() const { return dev_ != nullptr; }

    // 软复位并写入配置序列，末尾回读校验。
    // 返回 false 表示回读不一致 —— MPR121 没有 WHO_AM_I，回读是唯一能区分
    // 「I2C 真的通了」和「空写不报错」的手段。
    bool Init();

    // 12 位触摸状态，bit N 对应电极 N。读失败返回 0。
    uint16_t ReadTouchBits();

    // 标定阈值用的原始值。ch 为 0-11。
    uint16_t ReadFiltered(int ch);
    uint16_t ReadBaseline(int ch);

    // 只读诊断快照，格式对齐 Pca9685::Diagnostics()。
    std::string Diagnostics();

private:
    bool WriteReg(uint8_t reg, uint8_t value);
    bool ReadRegisters(uint8_t reg, uint8_t* data, size_t size);

    i2c_master_dev_handle_t dev_ = nullptr;
    esp_err_t last_write_error_ = ESP_OK;
};
