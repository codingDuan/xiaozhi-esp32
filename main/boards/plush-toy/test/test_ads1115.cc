#include "ads1115.h"

#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

struct FakeI2cBus {};
struct FakeI2cDevice {};

// ADS1115 的寄存器是 16 位大端，指针寄存器选址。只模拟用到的两个：
// 0x00 转换结果、0x01 配置。
static FakeI2cDevice g_device;
static std::vector<std::vector<uint8_t>> g_writes;
static uint16_t g_config = 0x8583;       // 上电复位值
static uint16_t g_conversion = 0;
static bool g_add_device_fails = false;
static bool g_read_fails = false;
// 模拟“写进去了但芯片没存住”——回读校验这条否则测不到。
static bool g_config_frozen = false;
// 模拟转换一直不结束：OS 位始终读 0。
static bool g_conversion_stuck = false;
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
    if (data_size == 3 && data[0] == 0x01 && !g_config_frozen) {
        uint16_t value = (uint16_t)((data[1] << 8) | data[2]);
        // OS 位写 1 触发单次转换；读回时 OS=1 表示空闲（转换已完成）。
        // 转换卡住时它读 0。
        if (g_conversion_stuck)
            value &= 0x7FFF;
        else
            value |= 0x8000;
        g_config = value;
    }
    return ESP_OK;
}

esp_err_t i2c_master_transmit_receive(i2c_master_dev_handle_t, const uint8_t* write_data, size_t,
                                      uint8_t* read_data, size_t read_size, int) {
    if (g_read_fails || read_size != 2)
        return ESP_FAIL;
    const uint16_t value = write_data[0] == 0x01 ? g_config : g_conversion;
    read_data[0] = (uint8_t)(value >> 8);
    read_data[1] = (uint8_t)(value & 0xFF);
    return ESP_OK;
}

static void Reset() {
    g_writes.clear();
    g_config = 0x8583;
    g_conversion = 0;
    g_read_fails = false;
    g_config_frozen = false;
    g_conversion_stuck = false;
}

static bool WroteConfig(uint16_t value) {
    for (const auto& w : g_writes) {
        if (w.size() == 3 && w[0] == 0x01 && (uint16_t)((w[1] << 8) | w[2]) == value)
            return true;
    }
    return false;
}

// 0x4383 = OS0 | MUX A0 单端 | PGA ±4.096V | 单次模式 | 128SPS | 比较器关闭
static void TestInitWritesIdleConfigAndVerifies() {
    FakeI2cBus bus;
    Reset();
    Ads1115 adc(&bus, 0x48, 100000);
    CHECK(adc.Init(), "配置回读一致时 Init 必须成功");
    CHECK(WroteConfig(0x4383), "Init 必须写 PGA ±4.096V、单次、128SPS、比较器关闭，且不触发转换");
}

// 只看 I2C 是否 ACK 区分不了「能读不能写」，必须回读自己写过的配置。
static void TestInitFailsWhenConfigDoesNotStick() {
    FakeI2cBus bus;
    Reset();
    Ads1115 adc(&bus, 0x48, 100000);
    g_config_frozen = true;   // 停在复位值 0x8583，PGA 是 ±2.048V
    CHECK(!adc.Init(), "配置寄存器回读不一致时 Init 必须返回 false");
}

// OS 位读回的语义与写入相反（读 1 = 空闲），比较时必须屏蔽掉，
// 否则一颗好芯片也会被判为写失败。
static void TestInitIgnoresOsBitOnReadback() {
    FakeI2cBus bus;
    Reset();
    Ads1115 adc(&bus, 0x48, 100000);
    CHECK(adc.Init(), "回读 0xC383 与写入 0x4383 只差 OS 位，必须视为一致");
    CHECK((g_config & 0x7FFF) == 0x4383, "fake 芯片应保存了写入的配置");
}

static void TestReadSingleEndedSelectsChannelAndDecodes() {
    FakeI2cBus bus;
    Reset();
    Ads1115 adc(&bus, 0x48, 100000);
    adc.Init();
    g_conversion = 13200;   // 25℃ 时节点约 1.65V
    int16_t code = 0;
    CHECK(adc.ReadSingleEnded(0, &code), "转换完成时读取必须成功");
    CHECK(code == 13200, "码值必须按大端拼接");
    CHECK(WroteConfig(0xC383), "A0 单次转换必须写 OS=1 | MUX=100");

    g_writes.clear();
    CHECK(adc.ReadSingleEnded(3, &code), "A3 读取必须成功");
    CHECK(WroteConfig(0xF383), "A3 单次转换必须写 MUX=111");
}

// 单端输入在 0V 附近会因失调读出小负数，这是合法码值，不能被当作无符号截断。
static void TestNegativeCodeIsSigned() {
    FakeI2cBus bus;
    Reset();
    Ads1115 adc(&bus, 0x48, 100000);
    adc.Init();
    g_conversion = 0xFFFE;
    int16_t code = 0;
    CHECK(adc.ReadSingleEnded(0, &code), "读取必须成功");
    CHECK(code == -2, "码值必须按有符号解释");
}

static void TestInvalidChannelRejected() {
    FakeI2cBus bus;
    Reset();
    Ads1115 adc(&bus, 0x48, 100000);
    adc.Init();
    int16_t code = 77;
    g_writes.clear();
    CHECK(!adc.ReadSingleEnded(4, &code), "通道 4 不存在，必须返回 false");
    CHECK(!adc.ReadSingleEnded(-1, &code), "负通道必须返回 false");
    CHECK(code == 77, "非法通道不得改写出参");
    CHECK(g_writes.empty(), "非法通道不得碰总线");
}

// 转换迟迟不结束时必须放弃，而不是把上一次的旧结果当新值返回。
// 旧值对温度闸门是隐形的：它落在合理区间内，却可能已经过时几分钟。
static void TestStuckConversionTimesOut() {
    FakeI2cBus bus;
    Reset();
    Ads1115 adc(&bus, 0x48, 100000);
    adc.Init();
    g_conversion = 13200;
    g_conversion_stuck = true;
    int16_t code = 55;
    CHECK(!adc.ReadSingleEnded(0, &code), "转换不结束时必须返回 false");
    CHECK(code == 55, "超时不得改写出参");
}

// 码值 0 是合法值（节点短路到地），失败只能靠返回值报告。
static void TestReadFailureReportsFalseAndKeepsOutput() {
    FakeI2cBus bus;
    Reset();
    Ads1115 adc(&bus, 0x48, 100000);
    adc.Init();
    int16_t code = 99;
    g_read_fails = true;
    CHECK(!adc.ReadSingleEnded(0, &code), "读失败必须返回 false");
    CHECK(code == 99, "读失败不得改写出参");
}

static void TestUnavailableWhenDeviceCannotBeAdded() {
    FakeI2cBus bus;
    Reset();
    g_add_device_fails = true;
    Ads1115 adc(&bus, 0x48, 100000);
    g_add_device_fails = false;
    CHECK(!adc.available(), "挂载失败时 available 必须为 false");
    CHECK(!adc.Init(), "挂载失败时 Init 必须返回 false");
    int16_t code = 0;
    CHECK(!adc.ReadSingleEnded(0, &code), "挂载失败时读取必须返回 false");
}

int main() {
    TestInitWritesIdleConfigAndVerifies();
    TestInitFailsWhenConfigDoesNotStick();
    TestInitIgnoresOsBitOnReadback();
    TestReadSingleEndedSelectsChannelAndDecodes();
    TestNegativeCodeIsSigned();
    TestInvalidChannelRejected();
    TestStuckConversionTimesOut();
    TestReadFailureReportsFalseAndKeepsOutput();
    TestUnavailableWhenDeviceCannotBeAdded();
    if (g_failures)
        return 1;
    std::puts("all Ads1115 tests passed");
    return 0;
}
