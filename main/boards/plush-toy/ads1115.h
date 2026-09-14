#pragma once

#include <driver/i2c_master.h>
#include <stdint.h>
#include <string>

// ADS1115 16 位 I2C ADC 驱动。只做单端单次转换，不知道什么是温度。
//
// 【为什么挂 I2C 而不用 ESP32 自带 ADC】
// S3 的 ADC 只在 GPIO1-20 上，这些脚已被麦克风、摄像头、屏占满；
// ADC2 在 Wi-Fi 开启时本就不可靠。见体温设计方案 2.1。
//
// 【固定量程与速率】
// PGA ±4.096V：3.3V 分压的全程都落在量程内，1 LSB = 0.125mV。
// 128SPS：单次转换约 7.8ms，远快于 500ms 的温度轮询，且速率越低噪声越小。
// 比较器关闭：ALERT 脚无处可接。
//
// 【为什么不继承 I2cDevice】
// 同 pca9685.h / mpu6050.h：该基类把 scl_speed_hz 硬编码为 400kHz。
//
// 【线程】
// 一次读取是「写配置 → 等待 → 读配置 → 读结果」多个事务，不是原子的。
// 两个任务同时读不同通道会互相覆盖 MUX。当前只有 A0 一个调用方，
// 将来 ThermalController 独占读取，其他地方只读它缓存的码值。
class Ads1115 {
public:
    Ads1115(i2c_master_bus_handle_t bus, uint8_t addr, uint32_t scl_hz);
    ~Ads1115();

    bool available() const { return dev_ != nullptr; }

    // 写空闲配置并回读校验。只看 ACK 区分不了「能读不能写」。
    bool Init();

    // 触发 channel(0-3) 的单端单次转换并等待结果。
    // 失败返回 false 且不改写出参：码值 0 是合法值（节点短路到地）。
    bool ReadSingleEnded(int channel, int16_t* code);

    std::string Diagnostics();

private:
    bool WriteRegister(uint8_t reg, uint16_t value);
    bool ReadRegister(uint8_t reg, uint16_t* value);

    i2c_master_dev_handle_t dev_ = nullptr;
    esp_err_t last_write_error_ = ESP_OK;
};
