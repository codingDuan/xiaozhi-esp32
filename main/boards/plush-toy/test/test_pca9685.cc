#include "pca9685.h"

#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

struct FakeI2cBus {};
struct FakeI2cDevice {};

static FakeI2cDevice g_device;
static std::vector<std::vector<uint8_t>> g_writes;
static uint8_t g_registers[256];
static esp_err_t g_next_transmit_error = ESP_OK;
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
    *device = &g_device;
    return ESP_OK;
}

esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t) { return ESP_OK; }

esp_err_t i2c_master_transmit(i2c_master_dev_handle_t, const uint8_t* data, size_t data_size, int) {
    g_writes.emplace_back(data, data + data_size);
    if (g_next_transmit_error != ESP_OK) {
        esp_err_t error = g_next_transmit_error;
        g_next_transmit_error = ESP_OK;
        return error;
    }
    for (size_t i = 1; i < data_size; ++i) {
        g_registers[static_cast<uint8_t>(data[0] + i - 1)] = data[i];
    }
    return ESP_OK;
}

esp_err_t i2c_master_transmit_receive(i2c_master_dev_handle_t, const uint8_t* write_data, size_t,
                                      uint8_t* read_data, size_t read_size, int) {
    std::memcpy(read_data, &g_registers[write_data[0]], read_size);
    return ESP_OK;
}

static void TestAllOffUsesOnlyServoChannels() {
    FakeI2cBus bus;
    Pca9685 pca(&bus, 0x40, 100000);

    g_writes.clear();
    pca.AllOff();
    CHECK(g_writes == std::vector<std::vector<uint8_t>>({{0x09, 0x10}, {0x0D, 0x10}}),
          "AllOff must disable channels 0 and 1 individually, never the global output gate");
    g_writes.clear();
    pca.SetPulseUs(0, 1500);
    pca.SetPulseUs(1, 1500);

    CHECK(g_writes.size() == 2, "each pulse must directly restore only its own channel");
    if (g_writes.size() != 2)
        return;
    CHECK(g_writes[0][0] == 0x06, "first pulse should target channel 0");
    CHECK(g_writes[1][0] == 0x0A, "second pulse should target channel 1");
    CHECK((g_writes[0][4] & 0x10) == 0, "channel 0 pulse must clear its full-off bit");
    CHECK((g_writes[1][4] & 0x10) == 0, "channel 1 pulse must clear its full-off bit");
}

static void TestConstructorSoftwareResetsPca() {
    FakeI2cBus bus;
    g_writes.clear();

    Pca9685 pca(&bus, 0x40, 100000);

    CHECK(!g_writes.empty() && g_writes.front() == std::vector<uint8_t>({0x06}),
          "constructor should issue the PCA9685 general-call software reset");
}

static void TestDiagnosticsReportsOutputRegisters() {
    FakeI2cBus bus;
    Pca9685 pca(&bus, 0x40, 100000);
    g_registers[0x00] = 0xA1;
    g_registers[0x01] = 0x04;
    g_registers[0xFE] = 121;
    g_registers[0xFD] = 0x10;
    g_registers[0x06] = 0x00;
    g_registers[0x07] = 0x00;
    g_registers[0x08] = 0x33;
    g_registers[0x09] = 0x01;
    g_registers[0x0A] = 0x00;
    g_registers[0x0B] = 0x00;
    g_registers[0x0C] = 0x34;
    g_registers[0x0D] = 0x01;

    std::string diagnostics = pca.Diagnostics();

    CHECK(diagnostics.find("mode1=0xA1") != std::string::npos, "diagnostics should report MODE1");
    CHECK(diagnostics.find("prescale=121") != std::string::npos,
          "diagnostics should report PRE_SCALE");
    CHECK(diagnostics.find("output_mode=per_channel") != std::string::npos,
          "diagnostics should report the per-channel output strategy");
    CHECK(diagnostics.find("ch0_off=307") != std::string::npos,
          "diagnostics should decode channel 0 OFF count");
    CHECK(diagnostics.find("ch1_off=308") != std::string::npos,
          "diagnostics should decode channel 1 OFF count");
}

static void TestDiagnosticsPreservesLastWriteFailure() {
    FakeI2cBus bus;
    Pca9685 pca(&bus, 0x40, 100000);

    g_next_transmit_error = ESP_FAIL;
    pca.AllOff();

    std::string diagnostics = pca.Diagnostics();

    CHECK(diagnostics.find("last_write_error=fake error") != std::string::npos,
          "diagnostics should retain the last failed I2C write after read-only checks");
}

// 加热走 CH15。全开：ON_H bit4=1 且 OFF_H bit4=0（芯片规定 FULL_OFF 优先于 FULL_ON，
// 不清掉 OFF_H 的 bit4 就开不了）。四个寄存器一次突发写完，不留半开的中间态。
static void TestSetFullOnWritesOnBitAndClearsOffBit() {
    FakeI2cBus bus;
    Pca9685 pca(&bus, 0x40, 100000);
    g_writes.clear();
    CHECK(pca.SetFullOn(15), "SetFullOn should report success");
    CHECK(g_writes == std::vector<std::vector<uint8_t>>({{0x42, 0x00, 0x10, 0x00, 0x00}}),
          "SetFullOn(15) must burst-write LED15 ON_H bit4 and clear OFF_H bit4");
}

static void TestSetFullOffWritesOffBit() {
    FakeI2cBus bus;
    Pca9685 pca(&bus, 0x40, 100000);
    g_writes.clear();
    CHECK(pca.SetFullOff(15), "SetFullOff should report success");
    CHECK(g_writes == std::vector<std::vector<uint8_t>>({{0x42, 0x00, 0x00, 0x00, 0x10}}),
          "SetFullOff(15) must burst-write LED15 OFF_H bit4 and clear ON_H bit4");
}

// 加热的调用方必须知道写没写进去：失败时要下个周期重发，而不是以为已经关了。
static void TestFullOnOffReportWriteFailure() {
    FakeI2cBus bus;
    Pca9685 pca(&bus, 0x40, 100000);
    g_next_transmit_error = ESP_FAIL;
    CHECK(!pca.SetFullOff(15), "SetFullOff must return false when the I2C write fails");
    g_next_transmit_error = ESP_FAIL;
    CHECK(!pca.SetFullOn(15), "SetFullOn must return false when the I2C write fails");
}

static void TestFullOnOffRejectInvalidChannel() {
    FakeI2cBus bus;
    Pca9685 pca(&bus, 0x40, 100000);
    g_writes.clear();
    CHECK(!pca.SetFullOn(16), "channel 16 does not exist");
    CHECK(!pca.SetFullOff(-1), "negative channel does not exist");
    CHECK(g_writes.empty(), "invalid channel must not touch the bus");
}

// AllOff 是舵机动作后的泄力，每个手势都会调用。它若顺带关掉 CH15，
// 加热会被每次摆手打断，因此只动舵机通道。
static void TestAllOffLeavesHeaterChannelAlone() {
    FakeI2cBus bus;
    Pca9685 pca(&bus, 0x40, 100000);
    g_writes.clear();
    pca.AllOff();
    for (const auto& w : g_writes)
        CHECK(w[0] < 0x42 || w[0] > 0x45, "AllOff must not write LED15 registers");
}

int main() {
    TestSetFullOnWritesOnBitAndClearsOffBit();
    TestSetFullOffWritesOffBit();
    TestFullOnOffReportWriteFailure();
    TestFullOnOffRejectInvalidChannel();
    TestAllOffLeavesHeaterChannelAlone();
    TestConstructorSoftwareResetsPca();
    TestAllOffUsesOnlyServoChannels();
    TestDiagnosticsReportsOutputRegisters();
    TestDiagnosticsPreservesLastWriteFailure();

    if (g_failures == 0) {
        std::printf("all Pca9685 tests passed\n");
        return 0;
    }
    std::printf("%d Pca9685 test(s) failed\n", g_failures);
    return 1;
}
