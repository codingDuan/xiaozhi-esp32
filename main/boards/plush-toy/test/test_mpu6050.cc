#include "mpu6050.h"
#include "config.h"

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
static bool g_read_fails = false;
// 模拟“写进去了但芯片没存住”——回读校验这条否则测不到。
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
    if (g_read_fails)
        return ESP_FAIL;
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

static void PrepareChip() {
    std::memset(g_registers, 0, sizeof(g_registers));
    g_registers[0x75] = 0x68;  // WHO_AM_I
    g_writes.clear();
}

static void TestInitWakesChipAndSetsRange() {
    FakeI2cBus bus;
    PrepareChip();
    Mpu6050 mpu(&bus, 0x68, 100000);
    CHECK(mpu.Init(), "WHO_AM_I 与回读都正确时 Init 必须成功");
    CHECK(WroteRegister(0x6B, 0x80), "必须先写设备复位");
    CHECK(WroteRegister(0x6B, 0x00), "必须解除睡眠位");
    CHECK(WroteRegister(0x1C, MOTION_ACCEL_FS_SEL), "必须设置 ±4g 量程");
    CHECK(WroteRegister(0x1A, 0x03), "必须开 DLPF 抑制舵机振动带来的高频分量");
}

static void TestInitFailsOnWrongWhoAmI() {
    FakeI2cBus bus;
    PrepareChip();
    g_registers[0x75] = 0x00;  // 不是 MPU6050
    Mpu6050 mpu(&bus, 0x68, 100000);
    CHECK(!mpu.Init(), "WHO_AM_I 不匹配时 Init 必须返回 false");
}

// 只读 WHO_AM_I 无法区分「能读不能写」，因此仍要回读一个自己写过的寄存器。
static void TestInitFailsWhenWrittenRegisterDoesNotStick() {
    FakeI2cBus bus;
    PrepareChip();
    Mpu6050 mpu(&bus, 0x68, 100000);
    g_frozen_register = 0x1C;
    const bool ok = mpu.Init();
    g_frozen_register = -1;
    CHECK(!ok, "量程寄存器回读不一致时 Init 必须返回 false");
}

static void TestAccelIsBigEndianSigned() {
    FakeI2cBus bus;
    PrepareChip();
    Mpu6050 mpu(&bus, 0x68, 100000);
    g_registers[0x3B] = 0x20; g_registers[0x3C] = 0x00;   // X = +8192 = +1g
    g_registers[0x3D] = 0xE0; g_registers[0x3E] = 0x00;   // Y = -8192 = -1g
    g_registers[0x3F] = 0x00; g_registers[0x40] = 0x01;   // Z = +1
    int16_t x = 0, y = 0, z = 0;
    CHECK(mpu.ReadAccel(x, y, z), "读成功必须返回 true");
    CHECK(x == 8192, "X 轴高字节在前");
    CHECK(y == -8192, "Y 轴必须按有符号解释");
    CHECK(z == 1, "Z 轴低字节参与拼接");
}

// 加速度的 0 是合法值，因此失败必须靠返回值报告，且不得改写出参。
static void TestReadFailureReportsFalseAndKeepsOutputs() {
    FakeI2cBus bus;
    PrepareChip();
    Mpu6050 mpu(&bus, 0x68, 100000);
    int16_t x = 123, y = 456, z = 789;
    g_read_fails = true;
    const bool ok = mpu.ReadAccel(x, y, z);
    g_read_fails = false;
    CHECK(!ok, "读失败必须返回 false");
    CHECK(x == 123 && y == 456 && z == 789, "读失败不得改写出参");
}

static void TestUnavailableWhenDeviceCannotBeAdded() {
    FakeI2cBus bus;
    g_add_device_fails = true;
    Mpu6050 mpu(&bus, 0x68, 100000);
    g_add_device_fails = false;
    CHECK(!mpu.available(), "挂载失败时 available 必须为 false");
    CHECK(!mpu.Init(), "挂载失败时 Init 必须返回 false");
    int16_t x = 0, y = 0, z = 0;
    CHECK(!mpu.ReadAccel(x, y, z), "挂载失败时读取必须返回 false");
}

int main() {
    TestInitWakesChipAndSetsRange();
    TestInitFailsOnWrongWhoAmI();
    TestInitFailsWhenWrittenRegisterDoesNotStick();
    TestAccelIsBigEndianSigned();
    TestReadFailureReportsFalseAndKeepsOutputs();
    TestUnavailableWhenDeviceCannotBeAdded();
    if (g_failures)
        return 1;
    std::puts("all Mpu6050 tests passed");
    return 0;
}
