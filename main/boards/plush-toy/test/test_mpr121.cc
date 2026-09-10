#include "mpr121.h"
#include "config.h"  // 断言里要用 TOUCH_PRESS_THRESHOLD

#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

struct FakeI2cBus {};
struct FakeI2cDevice {};

static FakeI2cDevice g_device;
static std::vector<std::vector<uint8_t>> g_writes;
static uint8_t g_registers[256];
static bool g_add_device_fails = false;
// 模拟“写进去了但芯片没存住”——接线松动和地址不对时的真实表现。
// 没有它就无法测回读校验：fake 的写入会把预置的回读值覆盖掉。
static int g_frozen_register = -1;
static int g_failures = 0;

#define CHECK(cond, msg)                                                \
    do {                                                                \
        if (!(cond)) {                                                  \
            std::printf("FAIL: %s (%s:%d)\n", msg, __FILE__, __LINE__); \
            ++g_failures;                                               \
        }                                                               \
    } while (0)

const char* esp_err_to_name(esp_err_t) { return "fake error"; }

esp_err_t i2c_master_bus_add_device(i2c_master_bus_handle_t, const i2c_device_config_t*,
                                    i2c_master_dev_handle_t* device) {
    if (g_add_device_fails)
        return ESP_FAIL;
    *device = &g_device;
    return ESP_OK;
}

esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t) { return ESP_OK; }

esp_err_t i2c_master_transmit(i2c_master_dev_handle_t, const uint8_t* data, size_t data_size, int) {
    g_writes.emplace_back(data, data + data_size);
    for (size_t i = 1; i < data_size; ++i) {
        const uint8_t reg = static_cast<uint8_t>(data[0] + i - 1);
        if ((int)reg == g_frozen_register)
            continue;
        g_registers[reg] = data[i];
    }
    return ESP_OK;
}

esp_err_t i2c_master_transmit_receive(i2c_master_dev_handle_t, const uint8_t* write_data, size_t,
                                      uint8_t* read_data, size_t read_size, int) {
    std::memcpy(read_data, &g_registers[write_data[0]], read_size);
    return ESP_OK;
}

static bool WroteRegister(uint8_t reg, uint8_t value) {
    for (const auto& write : g_writes) {
        if (write.size() == 2 && write[0] == reg && write[1] == value)
            return true;
    }
    return false;
}

// Init 必须先软复位再停机，否则改配置寄存器无效 —— 这是芯片的硬性时序。
static void TestInitStopsChipBeforeConfiguring() {
    FakeI2cBus bus;
    g_writes.clear();
    Mpr121 mpr(&bus, 0x5A, 100000);
    CHECK(mpr.Init(), "配置回读一致时 Init 必须成功");
    CHECK(WroteRegister(0x80, 0x63), "必须写软复位");
    CHECK(WroteRegister(0x5E, 0x00), "改配置前必须先把 ECR 清零停机");
    CHECK(WroteRegister(0x41, TOUCH_PRESS_THRESHOLD), "必须写 E0 触摸阈值");
    CHECK(WroteRegister(0x42, TOUCH_RELEASE_THRESHOLD), "必须写 E0 释放阈值");
    CHECK(WroteRegister(0x57, TOUCH_PRESS_THRESHOLD), "必须写 E11 触摸阈值");
    CHECK(WroteRegister(0x5E, 0x8F), "最后必须写 ECR 启用 12 电极");
}

// 回读校验是唯一的在线验证手段：MPR121 没有 WHO_AM_I，空写不报错。
static void TestInitFailsWhenReadbackMismatches() {
    FakeI2cBus bus;
    g_writes.clear();
    Mpr121 mpr(&bus, 0x5A, 100000);
    g_registers[0x41] = 0xFF;  // 让回读与写入不一致
    g_frozen_register = 0x41;  // 芯片“没存住”这次写入
    const bool ok = mpr.Init();
    g_frozen_register = -1;
    CHECK(!ok, "阈值回读不一致时 Init 必须返回 false");
}

static void TestTouchBitsAreTwelveBits() {
    FakeI2cBus bus;
    g_writes.clear();
    Mpr121 mpr(&bus, 0x5A, 100000);
    g_registers[0x00] = 0x05;
    g_registers[0x01] = 0x1A;  // 高字节只有低 4 位属于电极
    CHECK(mpr.ReadTouchBits() == 0x0A05, "触摸位必须是 12 位，高 4 位丢弃");
}

static void TestFilteredIsLittleEndianTenBits() {
    FakeI2cBus bus;
    g_writes.clear();
    Mpr121 mpr(&bus, 0x5A, 100000);
    g_registers[0x04] = 0x34;  // E0 LSB
    g_registers[0x05] = 0x02;  // E0 MSB
    CHECK(mpr.ReadFiltered(0) == 0x0234, "滤波值低字节在前");
}

// 基线寄存器存的是实际值右移两位，读出后必须补回来，否则和滤波值不同量纲。
static void TestBaselineIsShiftedLeftByTwo() {
    FakeI2cBus bus;
    g_writes.clear();
    Mpr121 mpr(&bus, 0x5A, 100000);
    g_registers[0x1E] = 0x40;
    CHECK(mpr.ReadBaseline(0) == 0x0100, "基线必须左移两位还原");
}

static void TestUnavailableWhenDeviceCannotBeAdded() {
    FakeI2cBus bus;
    g_add_device_fails = true;
    Mpr121 mpr(&bus, 0x5A, 100000);
    g_add_device_fails = false;
    CHECK(!mpr.available(), "挂载失败时 available 必须为 false");
    CHECK(!mpr.Init(), "挂载失败时 Init 必须返回 false");
    CHECK(mpr.ReadTouchBits() == 0, "挂载失败时读触摸位必须返回 0 而不是崩溃");
}

int main() {
    std::memset(g_registers, 0, sizeof(g_registers));
    TestInitStopsChipBeforeConfiguring();
    TestInitFailsWhenReadbackMismatches();
    std::memset(g_registers, 0, sizeof(g_registers));
    TestTouchBitsAreTwelveBits();
    TestFilteredIsLittleEndianTenBits();
    TestBaselineIsShiftedLeftByTwo();
    TestUnavailableWhenDeviceCannotBeAdded();
    if (g_failures)
        return 1;
    std::puts("all Mpr121 tests passed");
    return 0;
}
