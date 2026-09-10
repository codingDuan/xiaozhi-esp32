#include "touch_controller.h"

#include <cstdio>
#include <string>
#include <vector>

static int g_failures = 0;

#define CHECK(cond, msg)                                                \
    do {                                                                \
        if (!(cond)) {                                                  \
            std::printf("FAIL: %s (%s:%d)\n", msg, __FILE__, __LINE__); \
            ++g_failures;                                               \
        }                                                               \
    } while (0)

// 本测试链接了 mpr121.cc，需要这些 I2C 符号。边沿检测不碰硬件，故给最简实现。
struct FakeI2cDevice {};
static FakeI2cDevice g_device;

const char* esp_err_to_name(esp_err_t) { return "fake error"; }

esp_err_t i2c_master_bus_add_device(i2c_master_bus_handle_t, const i2c_device_config_t*,
                                    i2c_master_dev_handle_t* device) {
    *device = &g_device;
    return ESP_OK;
}

esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t) { return ESP_OK; }

esp_err_t i2c_master_transmit(i2c_master_dev_handle_t, const uint8_t*, size_t, int) {
    return ESP_OK;
}

esp_err_t i2c_master_transmit_receive(i2c_master_dev_handle_t, const uint8_t*, size_t, uint8_t*,
                                      size_t, int) {
    return ESP_OK;
}

struct Event {
    int electrode;
    bool pressed;
    bool operator==(const Event& other) const {
        return electrode == other.electrode && pressed == other.pressed;
    }
};

static std::vector<Event> Collect(const std::vector<uint16_t>& samples) {
    std::vector<Event> events;
    TouchController controller(nullptr);
    controller.SetHandler(
        [&](int electrode, bool pressed) { events.push_back({electrode, pressed}); });
    for (uint16_t bits : samples)
        controller.ApplyTouchBits(bits);
    return events;
}

static void TestNoChangeProducesNoEvent() {
    CHECK(Collect({0x000, 0x000, 0x000}).empty(), "状态不变不得产生事件");
    CHECK(Collect({0x001, 0x001}).size() == 1, "持续按住只在按下那一刻产生一个事件");
}

static void TestPressAndRelease() {
    const auto events = Collect({0x000, 0x001, 0x000});
    CHECK(events.size() == 2, "一次按下一次松开应产生两个事件");
    CHECK(events.size() == 2 && events[0] == (Event{0, true}), "第一个事件是电极 0 按下");
    CHECK(events.size() == 2 && events[1] == (Event{0, false}), "第二个事件是电极 0 松开");
}

// 多电极同时翻转必须逐个上报，否则接满 12 个电极后会丢事件。
static void TestSimultaneousBitsEachProduceAnEvent() {
    const auto events = Collect({0x000, 0x005});
    CHECK(events.size() == 2, "两位同时置位应产生两个事件");
    CHECK(events.size() == 2 && events[0] == (Event{0, true}), "低位电极先上报");
    CHECK(events.size() == 2 && events[1] == (Event{2, true}), "高位电极后上报");
}

static void TestHandlerIsOptional() {
    TouchController controller(nullptr);
    controller.ApplyTouchBits(0x001);  // 未设 handler 不得崩溃
    CHECK(!controller.available(), "驱动为空时 available 必须为 false");
}

int main() {
    TestNoChangeProducesNoEvent();
    TestPressAndRelease();
    TestSimultaneousBitsEachProduceAnEvent();
    TestHandlerIsOptional();
    if (g_failures)
        return 1;
    std::puts("all TouchController tests passed");
    return 0;
}
