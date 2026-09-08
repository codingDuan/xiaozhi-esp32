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

static void TestFirstPulseAfterAllOffRestoresOutputs() {
    FakeI2cBus bus;
    Pca9685 pca(&bus, 0x40, 100000);

    g_writes.clear();
    pca.AllOff();
    CHECK(g_writes == std::vector<std::vector<uint8_t>>({{0xFD, 0x10}}),
          "AllOff should address the write-only ALL_LED_OFF_H register directly");
    g_writes.clear();
    pca.SetPulseUs(0, 1500);
    pca.SetPulseUs(1, 1500);

    CHECK(g_writes.size() == 3,
          "first pulse after AllOff should restore outputs once, then write both channels");
    if (g_writes.size() != 3)
        return;
    CHECK(g_writes[0] == std::vector<uint8_t>({0xFD, 0x00}),
          "output restore should address ALL_LED_OFF_H directly");
    CHECK(g_writes[1][0] == 0x06, "first pulse should target channel 0");
    CHECK(g_writes[2][0] == 0x0A, "second pulse should target channel 1");
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
    CHECK(diagnostics.find("all_off_h=write_only") != std::string::npos,
          "diagnostics should not report a fabricated value for a write-only register");
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

int main() {
    TestConstructorSoftwareResetsPca();
    TestFirstPulseAfterAllOffRestoresOutputs();
    TestDiagnosticsReportsOutputRegisters();
    TestDiagnosticsPreservesLastWriteFailure();

    if (g_failures == 0) {
        std::printf("all Pca9685 tests passed\n");
        return 0;
    }
    std::printf("%d Pca9685 test(s) failed\n", g_failures);
    return 1;
}
