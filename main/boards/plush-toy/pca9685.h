#pragma once

#include <driver/i2c_master.h>
#include <stdint.h>
#include <string>

// PCA9685 16 路 PWM 驱动。本项目只用前两路驱动 SG90 舵机。
//
// 寄存器时序已于 2026-09-07 实机验证：50Hz 对应 PRE_SCALE=121，
// 写入后回读一致；芯片地址 0x40（0x70 是同一芯片的 ALLCALL 广播地址）。
//
// 【为什么不继承 I2cDevice】
// 仓库惯例是 I2C 外设继承 main/boards/common/i2c_device.h。但该基类把
// scl_speed_hz 硬编码为 400kHz（i2c_device.cc:12），实测在本项目的面包板
// 飞线上会导致寄存器读写失真：PRE_SCALE 写 121 回读得 217。降到 100kHz 后
// 恢复正常。改基类会影响全部 100+ 个板型，故此处自持 device handle。
class Pca9685 {
public:
    Pca9685(i2c_master_bus_handle_t bus, uint8_t addr, uint32_t scl_hz);
    ~Pca9685();

    // 设置 PWM 频率并唤醒芯片。
    // 返回 false 表示 PRE_SCALE 回读校验不通过 —— 用于区分「I2C 真的通了」
    // 和「空写不报错」，后者在接线松动或时钟过高时都会出现。
    bool Init(int freq_hz);

    // 设置某路脉宽（微秒）。ch 为 0-15。
    void SetPulseUs(int ch, int us);

    // 关闭全部 16 路输出，舵机泄力。
    void AllOff();

    uint8_t ReadPrescale();

    // 只读诊断快照，用于在没有串口和万用表时确认 PCA9685 是否真正保存了
    // PWM 寄存器。不会改变输出状态。
    std::string Diagnostics();

private:
    bool WriteReg(uint8_t reg, uint8_t value);
    bool ReadRegisters(uint8_t reg, uint8_t* data, size_t size);

    i2c_master_dev_handle_t dev_ = nullptr;
    esp_err_t last_write_error_ = ESP_OK;
};
