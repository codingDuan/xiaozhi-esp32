# 毛绒玩具触摸感知（MPR121）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 plush-toy 板型接入 MPR121 电容触摸传感器，触摸事件按可运行时配置的位掩码分发到眼睛、手臂、对话状态机和服务端。

**Architecture:** 三层，与现有 `Pca9685` → `LimbController` → `PlushBehavior` 同构。`Mpr121` 是纯寄存器驱动；`TouchController` 独立任务轮询并做边沿检测；`PlushBehavior` 持有模式掩码并分发。MPR121 并入现有的 `I2C_NUM_0` 总线，不占用任何新 GPIO。

**Tech Stack:** ESP-IDF v6.1、FreeRTOS、`i2c_master` 新驱动、NVS `Settings` 封装、主机侧 g++ 单测（`main/boards/plush-toy/test/Makefile`）。

**Spec:** `docs/superpowers/specs/2026-09-10-plush-toy-mpr121-touch-design.md`

## Global Constraints

- MPR121 地址 `0x5A`，挂在 `SERVO_I2C_PORT`（`I2C_NUM_0`）上，速率 `SERVO_I2C_HZ`（100000）。不新增 GPIO，不接 IRQ。
- 模块 VCC 必须接 3V3。5V 会把 SDA(GPIO44)/SCL(GPIO3) 上拉到 5V，超出耐压。
- 触摸链路任何失败只记状态、保持 `nullptr`，绝不 `ESP_ERROR_CHECK`。没有触摸的玩具仍须能对话、动手臂、眨眼。
- 事件词汇只有**碰到**和**离开**。本期不做点击/长按/抚摸区分。
- 模式位：`0x01` 本地反射、`0x02` 唤醒对话、`0x04` 上报大模型、`0x08` 读值诊断。默认 `0x09`。NVS 命名空间 `plush`，键名 `touch_modes`。
- 观测必须走 HTTP。板子的应用层控制台目前完全静默（见 `plans/TODO.md` 技术债），打日志的诊断拿不到任何结果。
- 不继承 `main/boards/common/i2c_device.h`：该基类把 scl_speed_hz 硬编码为 400kHz，本项目面包板飞线上会失真。理由同 `pca9685.h` 的注释。
- 每个任务结束时跑 `cd main/boards/plush-toy/test && make clean && make test`，全绿才提交。

---

### Task 1: Mpr121 驱动

**Files:**
- Create: `main/boards/plush-toy/mpr121.h`
- Create: `main/boards/plush-toy/mpr121.cc`
- Test: `main/boards/plush-toy/test/test_mpr121.cc`
- Modify: `main/boards/plush-toy/test/Makefile`
- Modify: `main/boards/plush-toy/config.h`

**Interfaces:**
- Consumes: 无
- Produces: `class Mpr121`，方法 `bool Init()`、`uint16_t ReadTouchBits()`、`uint16_t ReadFiltered(int ch)`、`uint16_t ReadBaseline(int ch)`、`std::string Diagnostics()`、`bool available() const`。构造签名 `Mpr121(i2c_master_bus_handle_t bus, uint8_t addr, uint32_t scl_hz)`，与 `Pca9685` 一致。

- [ ] **Step 1: 在 config.h 加入常量**

在 `config.h` 舵机段之后加：

```c
// ── 触摸：MPR121 并入舵机那条 I2C，不占新引脚 ──
// 引脚已用尽（26-32 是 flash，33-37 被八线 PSRAM 占用），IRQ 接不上，
// 因此只能轮询。去抖交给芯片的 DEBOUNCE 寄存器(0x5B)，不在软件里做。
#define MPR121_ADDR              0x5A   // ADDR 接地时的默认地址
#define TOUCH_POLL_INTERVAL_MS   50
#define TOUCH_HEAD_ELECTRODE     0      // 本期只接头部一个电极
#define TOUCH_ELECTRODE_COUNT    12
// 出厂猜测值，必须实机标定后回填。标定方法见 README「触摸标定」。
#define TOUCH_PRESS_THRESHOLD    0x0C
#define TOUCH_RELEASE_THRESHOLD  0x06
```

- [ ] **Step 2: 写失败测试**

创建 `test/test_mpr121.cc`。fake I2C 层照抄 `test_pca9685.cc` 的写法（同一目录下已有可用范式）：

```cpp
#include "mpr121.h"
#include "config.h"   // 断言里要用 TOUCH_PRESS_THRESHOLD

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
        g_registers[static_cast<uint8_t>(data[0] + i - 1)] = data[i];
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
    CHECK(!mpr.Init(), "阈值回读不一致时 Init 必须返回 false");
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
```

- [ ] **Step 3: 加 Makefile 目标**

在 `test/Makefile` 的 `test:` 目标里把 `test_mpr121` 加进依赖和执行列表，并加规则：

```make
test_mpr121: test_mpr121.cc ../mpr121.cc ../mpr121.h ../config.h
	$(CXX) $(CXXFLAGS) -o $@ test_mpr121.cc ../mpr121.cc
```

同时把 `test_mpr121` 加进 `clean` 的 `rm -f` 列表。

注意 `config.h` 顶部 `#include <driver/gpio.h>`，主机侧没有这个头。在 `test/stubs/driver/` 下新建空的 `gpio.h` 与 `i2c_types.h`：

```c
#pragma once
```

- [ ] **Step 4: 跑测试确认失败**

```sh
cd main/boards/plush-toy/test && make test_mpr121
```

预期：编译失败，`mpr121.h: No such file or directory`。

- [ ] **Step 5: 写 mpr121.h**

```cpp
#pragma once

#include <driver/i2c_master.h>
#include <stdint.h>
#include <string>

// MPR121 12 通道电容触摸驱动。本项目只接一个头部电极，但驱动按 12 通道实现。
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
```

- [ ] **Step 6: 写 mpr121.cc**

```cpp
#include "mpr121.h"
#include "config.h"

#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include <cstdio>

#define TAG "Mpr121"

namespace {
constexpr uint8_t kRegTouchStatus = 0x00;
constexpr uint8_t kRegFiltered0 = 0x04;
constexpr uint8_t kRegBaseline0 = 0x1E;
constexpr uint8_t kRegThreshold0 = 0x41;  // 每个电极两字节：触摸、释放
constexpr uint8_t kRegDebounce = 0x5B;
constexpr uint8_t kRegConfig1 = 0x5C;
constexpr uint8_t kRegConfig2 = 0x5D;
constexpr uint8_t kRegEcr = 0x5E;
constexpr uint8_t kRegSoftReset = 0x80;

constexpr uint8_t kSoftResetMagic = 0x63;
constexpr uint8_t kEcrRun = 0x8F;  // 基线跟踪 + 启用全部 12 个电极
constexpr int kTimeoutMs = 1000;

// 基线滤波参数取自 NXP AN3944 的推荐配置。
constexpr uint8_t kBaselineFilter[][2] = {
    {0x2B, 0x01}, {0x2C, 0x01}, {0x2D, 0x00}, {0x2E, 0x00},
    {0x2F, 0x01}, {0x30, 0x05}, {0x31, 0x01}, {0x32, 0x00},
};
}  // namespace

Mpr121::Mpr121(i2c_master_bus_handle_t bus, uint8_t addr, uint32_t scl_hz) {
    i2c_device_config_t cfg = {};
    cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    cfg.device_address = addr;
    cfg.scl_speed_hz = scl_hz;
    esp_err_t err = i2c_master_bus_add_device(bus, &cfg, &dev_);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "挂载设备失败: %s", esp_err_to_name(err));
        dev_ = nullptr;
    }
}

Mpr121::~Mpr121() {
    if (dev_ != nullptr)
        i2c_master_bus_rm_device(dev_);
}

bool Mpr121::WriteReg(uint8_t reg, uint8_t value) {
    if (dev_ == nullptr)
        return false;
    uint8_t buf[2] = {reg, value};
    esp_err_t err = i2c_master_transmit(dev_, buf, sizeof(buf), kTimeoutMs);
    if (err != ESP_OK) {
        last_write_error_ = err;
        ESP_LOGE(TAG, "写寄存器 0x%02X 失败: %s", reg, esp_err_to_name(err));
        return false;
    }
    last_write_error_ = ESP_OK;
    return true;
}

bool Mpr121::ReadRegisters(uint8_t reg, uint8_t* data, size_t size) {
    if (dev_ == nullptr)
        return false;
    esp_err_t err = i2c_master_transmit_receive(dev_, &reg, 1, data, size, kTimeoutMs);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "读寄存器 0x%02X 失败: %s", reg, esp_err_to_name(err));
        return false;
    }
    return true;
}

bool Mpr121::Init() {
    if (dev_ == nullptr)
        return false;

    if (!WriteReg(kRegSoftReset, kSoftResetMagic))
        return false;
    vTaskDelay(pdMS_TO_TICKS(2));

    // 配置寄存器只在停机状态下可写，这是芯片的硬性要求
    if (!WriteReg(kRegEcr, 0x00))
        return false;

    for (const auto& pair : kBaselineFilter) {
        if (!WriteReg(pair[0], pair[1]))
            return false;
    }

    for (int ch = 0; ch < TOUCH_ELECTRODE_COUNT; ++ch) {
        const uint8_t base = kRegThreshold0 + 2 * ch;
        if (!WriteReg(base, TOUCH_PRESS_THRESHOLD) ||
            !WriteReg(base + 1, TOUCH_RELEASE_THRESHOLD))
            return false;
    }

    if (!WriteReg(kRegDebounce, 0x22))  // 触摸与释放各需连续 2 次采样一致
        return false;
    if (!WriteReg(kRegConfig1, 0x10) || !WriteReg(kRegConfig2, 0x20))
        return false;
    if (!WriteReg(kRegEcr, kEcrRun))
        return false;

    uint8_t back = 0;
    if (!ReadRegisters(kRegThreshold0, &back, 1) || back != TOUCH_PRESS_THRESHOLD) {
        ESP_LOGE(TAG, "阈值回读 0x%02X，期望 0x%02X —— 芯片未正确响应（接线或地址不对）",
                 back, TOUCH_PRESS_THRESHOLD);
        return false;
    }
    ESP_LOGI(TAG, "初始化完成，%d 电极，触摸阈值 0x%02X", TOUCH_ELECTRODE_COUNT,
             TOUCH_PRESS_THRESHOLD);
    return true;
}

uint16_t Mpr121::ReadTouchBits() {
    uint8_t raw[2] = {};
    if (!ReadRegisters(kRegTouchStatus, raw, sizeof(raw)))
        return 0;
    return (uint16_t)((raw[0] | (raw[1] << 8)) & 0x0FFF);
}

uint16_t Mpr121::ReadFiltered(int ch) {
    if (ch < 0 || ch >= TOUCH_ELECTRODE_COUNT)
        return 0;
    uint8_t raw[2] = {};
    if (!ReadRegisters((uint8_t)(kRegFiltered0 + 2 * ch), raw, sizeof(raw)))
        return 0;
    return (uint16_t)(raw[0] | (raw[1] << 8));
}

uint16_t Mpr121::ReadBaseline(int ch) {
    if (ch < 0 || ch >= TOUCH_ELECTRODE_COUNT)
        return 0;
    uint8_t raw = 0;
    if (!ReadRegisters((uint8_t)(kRegBaseline0 + ch), &raw, 1))
        return 0;
    return (uint16_t)(raw << 2);  // 寄存器存的是实际基线右移两位
}

std::string Mpr121::Diagnostics() {
    uint8_t ecr = 0;
    uint8_t threshold = 0;
    if (!ReadRegisters(kRegEcr, &ecr, 1) || !ReadRegisters(kRegThreshold0, &threshold, 1))
        return "read_failed";
    char result[160];
    std::snprintf(result, sizeof(result),
                  "ecr=0x%02X touch_threshold=0x%02X touch_bits=0x%03X "
                  "e0_filtered=%u e0_baseline=%u last_write_error=%s",
                  ecr, threshold, ReadTouchBits(), ReadFiltered(TOUCH_HEAD_ELECTRODE),
                  ReadBaseline(TOUCH_HEAD_ELECTRODE), esp_err_to_name(last_write_error_));
    return result;
}
```

- [ ] **Step 7: 跑测试确认通过**

```sh
cd main/boards/plush-toy/test && make clean && make test
```

预期：`all Mpr121 tests passed`，其余五个测试仍全绿。

- [ ] **Step 8: 提交**

```bash
git add main/boards/plush-toy/mpr121.h main/boards/plush-toy/mpr121.cc \
        main/boards/plush-toy/config.h main/boards/plush-toy/test/test_mpr121.cc \
        main/boards/plush-toy/test/Makefile main/boards/plush-toy/test/stubs/driver
git commit -m "feat(plush-toy): 新增 MPR121 触摸驱动"
```

---

### Task 2: TouchController 边沿检测与轮询任务

**Files:**
- Create: `main/boards/plush-toy/touch_controller.h`
- Create: `main/boards/plush-toy/touch_controller.cc`
- Test: `main/boards/plush-toy/test/test_touch_controller.cc`
- Modify: `main/boards/plush-toy/test/Makefile`
- Modify: `main/boards/plush-toy/test/stubs/freertos/task.h`

**Interfaces:**
- Consumes: Task 1 的 `Mpr121`
- Produces: `class TouchController`，构造 `TouchController(Mpr121* mpr)`；`void SetHandler(TouchHandler handler)`，其中 `using TouchHandler = std::function<void(int electrode, bool pressed)>`；`void Start()`；`void ApplyTouchBits(uint16_t bits)` 供测试与模拟触摸调用；`bool available() const`。

- [ ] **Step 1: 给 FreeRTOS stub 补 xTaskCreate**

`test/stubs/freertos/task.h` 追加（保留原有 `vTaskDelay`）：

```cpp
inline void vTaskDelay(int) {}

using TaskFunction_t = void (*)(void*);
// 主机侧不真的起任务：Start() 只需能编译链接，轮询逻辑通过 ApplyTouchBits 测。
inline int xTaskCreate(TaskFunction_t, const char*, int, void*, int, void*) { return 1; }
```

- [ ] **Step 2: 写失败测试**

创建 `test/test_touch_controller.cc`：

```cpp
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
    controller.SetHandler([&](int electrode, bool pressed) {
        events.push_back({electrode, pressed});
    });
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
    CHECK(events[0] == (Event{0, true}), "第一个事件是电极 0 按下");
    CHECK(events[1] == (Event{0, false}), "第二个事件是电极 0 松开");
}

// 多电极同时翻转必须逐个上报，否则接满 12 个电极后会丢事件。
static void TestSimultaneousBitsEachProduceAnEvent() {
    const auto events = Collect({0x000, 0x005});
    CHECK(events.size() == 2, "两位同时置位应产生两个事件");
    CHECK(events[0] == (Event{0, true}), "低位电极先上报");
    CHECK(events[1] == (Event{2, true}), "高位电极后上报");
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
```

- [ ] **Step 3: 加 Makefile 目标并跑测试确认失败**

`test/Makefile` 加入 `test_touch_controller` 到 `test:` 依赖、执行列表和 `clean`，并加规则：

```make
test_touch_controller: test_touch_controller.cc ../touch_controller.cc ../touch_controller.h ../mpr121.cc ../mpr121.h ../config.h
	$(CXX) $(CXXFLAGS) -o $@ test_touch_controller.cc ../touch_controller.cc ../mpr121.cc
```

注意这条规则会把 `mpr121.cc` 也链进来，因此本测试文件同样需要 fake I2C 符号。把 `test_mpr121.cc` 里那五个 fake 函数（`esp_err_to_name`、`i2c_master_bus_add_device`、`i2c_master_bus_rm_device`、`i2c_master_transmit`、`i2c_master_transmit_receive`）原样复制到 `test_touch_controller.cc` 顶部，用最简实现即可：

```cpp
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
```

跑：

```sh
cd main/boards/plush-toy/test && make test_touch_controller
```

预期：编译失败，`touch_controller.h: No such file or directory`。

- [ ] **Step 4: 写 touch_controller.h**

```cpp
#pragma once

#include "mpr121.h"

#include <functional>

// 触摸轮询与边沿检测。只回答「哪个电极刚被碰到 / 刚离开」，
// 不知道电极对应身体哪个部位，也不知道该做什么反应 —— 那是 PlushBehavior 的事。
//
// 没有 IRQ 引脚可用（引脚已用尽），因此靠固定周期轮询。去抖已由芯片的
// DEBOUNCE 寄存器完成，这里只比较状态位，不做第二重软件去抖。
class TouchController {
public:
    using TouchHandler = std::function<void(int electrode, bool pressed)>;

    explicit TouchController(Mpr121* mpr);

    bool available() const { return mpr_ != nullptr; }
    void SetHandler(TouchHandler handler) { handler_ = std::move(handler); }
    void Start();

    // 比较新状态位与上一次，逐位产出事件。
    // 公开是为了两个用途：主机侧单测，以及测试通道的模拟触摸。
    void ApplyTouchBits(uint16_t bits);

private:
    static void TaskEntry(void* arg);
    void Run();

    Mpr121* mpr_ = nullptr;
    TouchHandler handler_;
    uint16_t last_bits_ = 0;
};
```

- [ ] **Step 5: 写 touch_controller.cc**

```cpp
#include "touch_controller.h"
#include "config.h"

#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#define TAG "TouchController"

TouchController::TouchController(Mpr121* mpr) : mpr_(mpr) {}

void TouchController::Start() {
    if (mpr_ == nullptr) {
        ESP_LOGW(TAG, "MPR121 不可用，触摸感知已禁用");
        return;
    }
    xTaskCreate(TaskEntry, "touch", 3072, this, 3, nullptr);
    ESP_LOGI(TAG, "触摸轮询已启动，周期 %d ms", TOUCH_POLL_INTERVAL_MS);
}

void TouchController::TaskEntry(void* arg) { static_cast<TouchController*>(arg)->Run(); }

void TouchController::Run() {
    while (true) {
        // 读失败不重试也不退出：保留上一次状态，下个周期再读。
        // 共享 I2C 总线上偶发失败是正常的，为此杀掉任务得不偿失。
        ApplyTouchBits(mpr_->ReadTouchBits());
        vTaskDelay(pdMS_TO_TICKS(TOUCH_POLL_INTERVAL_MS));
    }
}

void TouchController::ApplyTouchBits(uint16_t bits) {
    const uint16_t changed = (uint16_t)(bits ^ last_bits_);
    last_bits_ = bits;
    if (changed == 0 || !handler_)
        return;
    for (int ch = 0; ch < TOUCH_ELECTRODE_COUNT; ++ch) {
        const uint16_t mask = (uint16_t)(1u << ch);
        if ((changed & mask) != 0)
            handler_(ch, (bits & mask) != 0);
    }
}
```

- [ ] **Step 6: 跑测试确认通过**

```sh
cd main/boards/plush-toy/test && make clean && make test
```

预期：`all TouchController tests passed`，七个测试全绿。

- [ ] **Step 7: 提交**

```bash
git add main/boards/plush-toy/touch_controller.h main/boards/plush-toy/touch_controller.cc \
        main/boards/plush-toy/test/test_touch_controller.cc \
        main/boards/plush-toy/test/test_mpr121.cc \
        main/boards/plush-toy/test/Makefile main/boards/plush-toy/test/stubs/freertos/task.h
git commit -m "feat(plush-toy): 新增触摸轮询与边沿检测"
```

---

### Task 3: 模式位掩码与行为分发

**Files:**
- Modify: `main/boards/plush-toy/config.h`
- Modify: `main/boards/plush-toy/plush_behavior.h`
- Modify: `main/boards/plush-toy/plush_behavior.cc`

**Interfaces:**
- Consumes: Task 2 的 `TouchController::TouchHandler` 签名
- Produces: `PlushBehavior::OnTouch(int electrode, bool pressed)`、`uint32_t touch_modes() const`、`void SetTouchModes(uint32_t modes)`。掩码常量在 `config.h`。

- [ ] **Step 1: 在 config.h 加模式位**

```c
// 触摸响应模式，可叠加。存 NVS 命名空间 plush 的 touch_modes 键，运行时可改。
#define TOUCH_MODE_REFLEX   0x01   // 本地反射：直接改眼睛、动手臂
#define TOUCH_MODE_WAKE     0x02   // 唤醒对话：进入聆听状态
#define TOUCH_MODE_REPORT   0x04   // 上报大模型：把触摸作为一句话送给服务端
#define TOUCH_MODE_DIAG     0x08   // 读值诊断：把原始计数放进 HTTP status 返回
#define TOUCH_MODES_DEFAULT (TOUCH_MODE_REFLEX | TOUCH_MODE_DIAG)
```

- [ ] **Step 2: 扩 plush_behavior.h**

在类的 public 区加：

```cpp
    // 由 TouchController 转发而来。按模式掩码分发，四条路径互不影响。
    void OnTouch(int electrode, bool pressed);

    uint32_t touch_modes() const { return touch_modes_; }
    // 立即生效并写回 NVS。
    void SetTouchModes(uint32_t modes);
```

private 区加：

```cpp
    uint32_t touch_modes_ = TOUCH_MODES_DEFAULT;
```

`Start()` 之外还需要在构造函数里从 NVS 载入，见下一步。

- [ ] **Step 3: 实现 OnTouch 与掩码持久化**

`plush_behavior.cc` 顶部补 `#include "config.h"` 与 `#include "settings.h"`，构造函数改为：

```cpp
PlushBehavior::PlushBehavior(LimbController* limbs, EyeDisplay* display)
    : limbs_(limbs), display_(display) {
    Settings settings("plush", false);
    touch_modes_ = (uint32_t)settings.GetInt("touch_modes", TOUCH_MODES_DEFAULT);
}

void PlushBehavior::SetTouchModes(uint32_t modes) {
    touch_modes_ = modes;
    Settings settings("plush", true);
    settings.SetInt("touch_modes", (int32_t)modes);
    ESP_LOGI(TAG, "触摸模式掩码改为 0x%02X", (unsigned)modes);
}
```

文件末尾加：

```cpp
void PlushBehavior::OnTouch(int electrode, bool pressed) {
    ESP_LOGI(TAG, "触摸 电极%d %s，掩码 0x%02X", electrode, pressed ? "按下" : "松开",
             (unsigned)touch_modes_);

    if ((touch_modes_ & TOUCH_MODE_REFLEX) != 0) {
        if (display_ != nullptr)
            display_->SetEmotion(pressed ? "happy" : "neutral");
        if (pressed && limbs_ != nullptr && limbs_->available())
            limbs_->Enqueue(Gesture::kCheer, 1);
    }

    // 松开不触发任何网络行为：一次触摸只该引起一轮对话，否则手指离开时会再来一轮。
    if (!pressed)
        return;

    auto& app = Application::GetInstance();
    if ((touch_modes_ & TOUCH_MODE_REPORT) != 0) {
        // WakeWordInvoke 会把这句话当作用户说的送给服务端，本身就带唤醒效果，
        // 因此它与 WAKE 位是包含关系，不能再叠加一次 StartListening。
        app.WakeWordInvoke("有人摸了摸我的头");
    } else if ((touch_modes_ & TOUCH_MODE_WAKE) != 0) {
        if (app.GetDeviceState() == kDeviceStateIdle)
            app.StartListening();
    }
}
```

`TOUCH_MODE_DIAG` 位不在这里消费，它只控制 HTTP status 是否带原始计数，见 Task 5。

- [ ] **Step 4: 编译验证**

主机测试不覆盖本任务（`plush_behavior.cc` 依赖 `Application`，主机侧无桩），因此用固件构建验证：

```sh
source ~/.espressif/tools/activate_idf_v6.1.sh && idf.py build
```

预期：编译通过，无新警告。

- [ ] **Step 5: 提交**

```bash
git add main/boards/plush-toy/config.h main/boards/plush-toy/plush_behavior.h \
        main/boards/plush-toy/plush_behavior.cc
git commit -m "feat(plush-toy): 触摸响应模式掩码与分发"
```

---

### Task 4: 板级接线

**Files:**
- Modify: `main/boards/plush-toy/plush_toy_board.cc`

**Interfaces:**
- Consumes: Task 1-3 的 `Mpr121`、`TouchController`、`PlushBehavior::OnTouch`
- Produces: 成员 `Mpr121* mpr121_`、`TouchController* touch_`，供 Task 5 的 status 与测试动作读取。

- [ ] **Step 1: 加 include 与成员**

`plush_toy_board.cc` 顶部 include 区按字母序插入：

```cpp
#include "mpr121.h"
#include "touch_controller.h"
```

私有成员区在 `behavior_` 之后加：

```cpp
    Mpr121* mpr121_ = nullptr;
    TouchController* touch_ = nullptr;
```

- [ ] **Step 2: 把 MPR121 挂到现有 I2C 总线上**

`InitializeServoBus()` 目前在局部变量里持有 `bus`，MPR121 需要同一条总线，因此把它提升为成员。在私有成员区加：

```cpp
    i2c_master_bus_handle_t servo_bus_ = nullptr;
```

`InitializeServoBus()` 中把 `i2c_master_bus_handle_t bus = nullptr;` 改为使用 `servo_bus_`，其余不变（探测失败时 `pca_` 仍保持 `nullptr`，但总线句柄要留着给 MPR121 用）。

新增方法，放在 `InitializeServoBus()` 之后：

```cpp
    // 触摸链路的任何失败都不得影响对话 —— 与舵机同一原则，只记日志不 ESP_ERROR_CHECK。
    void InitializeTouch() {
        if (servo_bus_ == nullptr)
            return;
        if (i2c_master_probe(servo_bus_, MPR121_ADDR, 100) != ESP_OK) {
            ESP_LOGE(TAG,
                     "MPR121(0x%02X) 无响应。请检查：VCC 是否接 3V3（接 5V 会把 "
                     "SDA/SCL 拉到 5V 并损坏引脚）、是否共地、ADDR 是否接地",
                     MPR121_ADDR);
            return;
        }
        mpr121_ = new Mpr121(servo_bus_, MPR121_ADDR, SERVO_I2C_HZ);
        if (!mpr121_->Init()) {
            delete mpr121_;
            mpr121_ = nullptr;
        }
    }
```

- [ ] **Step 3: 在构造函数里启动**

构造函数中 `behavior_->Start();` 之后、`if (display_ != nullptr)` 之前插入：

```cpp
        InitializeTouch();
        touch_ = new TouchController(mpr121_);
        auto* behavior = behavior_;
        touch_->SetHandler([behavior](int electrode, bool pressed) {
            behavior->OnTouch(electrode, pressed);
        });
        touch_->Start();
```

- [ ] **Step 4: 编译验证**

```sh
source ~/.espressif/tools/activate_idf_v6.1.sh && idf.py build
```

预期：编译通过。拔掉 MPR121 时应走探测失败分支，设备照常启动。

- [ ] **Step 5: 提交**

```bash
git add main/boards/plush-toy/plush_toy_board.cc
git commit -m "feat(plush-toy): 板级接入 MPR121 触摸"
```

---

### Task 5: HTTP 观测与测试动作

板子的应用层控制台完全静默，所以这一步不是锦上添花：没有它，阈值无法标定，四条响应路径也无法回归。

**Files:**
- Modify: `main/boards/plush-toy/test_http_channel.h`
- Modify: `main/boards/plush-toy/test_http_channel.cc`
- Modify: `main/boards/plush-toy/plush_toy_test_server.h`
- Modify: `main/boards/plush-toy/plush_toy_board.cc`
- Test: `main/boards/plush-toy/test/test_http_channel.cc`

**Interfaces:**
- Consumes: Task 4 的 `mpr121_`、`touch_`，Task 3 的 `touch_modes()` / `SetTouchModes()`
- Produces: 测试通道新动作 `touch_modes`（参数 `modes`，整数）与 `simulate_touch`（参数 `electrode` 整数、`pressed` 布尔）；`TestHttpChannel` 新增 `using StatusProvider = std::function<std::string()>` 与可选构造参数。

- [ ] **Step 1: 写失败测试**

`test/test_http_channel.cc` 中，在现有 emotion 断言之后加：

```cpp
    CHECK(channel.Dispatch("touch_modes", R"({"modes":5})"),
          "whitelisted touch_modes must dispatch");
    CHECK(scheduled_action == "touch_modes", "touch_modes must reach the scheduler");
    CHECK(channel.Dispatch("simulate_touch", R"({"electrode":0,"pressed":true})"),
          "whitelisted simulate_touch must dispatch");
    CHECK(channel.StatusJson().find("\"simulate_touch\"") != std::string::npos,
          "status must list simulate_touch");
```

再加一段验证 status provider：

```cpp
    TestHttpChannel probed("172.20.10.14", [](const std::string&, const std::string&) {},
                           []() { return std::string(R"("touch_bits":1)"); });
    CHECK(probed.StatusJson().find(R"("touch_bits":1)") != std::string::npos,
          "status must embed the board-provided fragment");
    CHECK(probed.StatusJson().find("\"ready\":true") != std::string::npos,
          "status must keep the ready flag");
```

- [ ] **Step 2: 跑测试确认失败**

```sh
cd main/boards/plush-toy/test && make test_http_channel && ./test_http_channel
```

预期：编译失败（三参数构造不存在）。

- [ ] **Step 3: 扩 TestHttpChannel**

`test_http_channel.h` 加：

```cpp
    using StatusProvider = std::function<std::string()>;
```

构造函数签名改为（第三个参数可选，现有两参数调用点不受影响）：

```cpp
    TestHttpChannel(std::string allowed_host, ScheduleAction schedule_action,
                    StatusProvider status_provider = nullptr);
```

`.cc` 中的定义同步改为：

```cpp
TestHttpChannel::TestHttpChannel(std::string allowed_host, ScheduleAction schedule_action,
                                 StatusProvider status_provider)
    : allowed_host_(std::move(allowed_host)),
      schedule_action_(std::move(schedule_action)),
      status_provider_(std::move(status_provider)) {}
```

并加私有成员 `StatusProvider status_provider_;`。

`test_http_channel.cc` 中 `IsAllowedAction` 加入两个新动作：

```cpp
    return action == "wave" || action == "hug" || action == "cheer" || action == "eyes" ||
           action == "emotion" || action == "touch_modes" || action == "simulate_touch" ||
           action == "diagnostics";
```

`StatusJson()` 改为拼接：

```cpp
std::string TestHttpChannel::StatusJson() const {
    std::string json =
        R"({"ready":true,"actions":["wave","hug","cheer","eyes","emotion","touch_modes",)"
        R"("simulate_touch","diagnostics"])";
    if (status_provider_) {
        const std::string fragment = status_provider_();
        if (!fragment.empty())
            json += "," + fragment;
    }
    return json + "}";
}
```

- [ ] **Step 4: 板级提供 status 片段与动作处理**

`plush_toy_board.cc` 的 `InitializeTestServer()` 中，给 `PlushToyTestServer` 传入第三个参数。`plush_toy_test_server.h` 的构造函数同步增加 `TestHttpChannel::StatusProvider` 参数并转发给 `channel_`。

板级实现：

```cpp
    // 控制台静默，原始计数只能从 HTTP 拿。DIAG 位关掉时省掉这段读 I2C 的开销。
    std::string TestStatusFragment() {
        std::string json = "\"touch_modes\":" +
                           std::to_string(behavior_ ? behavior_->touch_modes() : 0);
        json += ",\"touch_present\":";
        json += (mpr121_ != nullptr ? "true" : "false");
        json += ",\"servo_present\":";
        json += (pca_ != nullptr ? "true" : "false");
        if (pca_ != nullptr)
            json += ",\"servo_diagnostics\":\"" + pca_->Diagnostics() + "\"";
        if (mpr121_ != nullptr && behavior_ != nullptr &&
            (behavior_->touch_modes() & TOUCH_MODE_DIAG) != 0) {
            json += ",\"touch_bits\":" + std::to_string(mpr121_->ReadTouchBits());
            json += ",\"touch_filtered\":" +
                    std::to_string(mpr121_->ReadFiltered(TOUCH_HEAD_ELECTRODE));
            json += ",\"touch_baseline\":" +
                    std::to_string(mpr121_->ReadBaseline(TOUCH_HEAD_ELECTRODE));
        }
        return json;
    }
```

`ScheduleTestAction` 在 `diagnostics` 分支之前插入：

```cpp
            } else if (action == "touch_modes" && behavior_ != nullptr) {
                const auto* modes = cJSON_GetObjectItem(arguments, "modes");
                if (cJSON_IsNumber(modes))
                    behavior_->SetTouchModes((uint32_t)modes->valueint);
            } else if (action == "simulate_touch" && touch_ != nullptr) {
                // 不碰硬件就能验证四条响应路径。没有它，每跑一次回归都要有人
                // 真的伸手去摸，且结果依赖手指位置和力度，不可重复。
                const auto* electrode = cJSON_GetObjectItem(arguments, "electrode");
                const auto* pressed = cJSON_GetObjectItem(arguments, "pressed");
                const int ch = cJSON_IsNumber(electrode) ? electrode->valueint : 0;
                const bool down = cJSON_IsBool(pressed) ? cJSON_IsTrue(pressed) : true;
                touch_->ApplyTouchBits(down ? (uint16_t)(1u << ch) : 0);
```

- [ ] **Step 5: 跑测试确认通过**

```sh
cd main/boards/plush-toy/test && make clean && make test
source ~/.espressif/tools/activate_idf_v6.1.sh && cd - && idf.py build
```

预期：七个主机测试全绿，固件编译通过。

- [ ] **Step 6: 提交**

```bash
git add main/boards/plush-toy/test_http_channel.h main/boards/plush-toy/test_http_channel.cc \
        main/boards/plush-toy/plush_toy_test_server.h main/boards/plush-toy/plush_toy_board.cc \
        main/boards/plush-toy/test/test_http_channel.cc
git commit -m "feat(plush-toy): HTTP 通道暴露触摸状态与模拟触摸"
```

---

### Task 6: 测试脚本、回归与文档

**Files:**
- Modify: `tools/plush_toy_test.py`
- Modify: `main/boards/plush-toy/README.md`
- Modify: `docs/superpowers/plans/TODO.md`

**Interfaces:**
- Consumes: Task 5 的两个测试动作与扩展后的 status
- Produces: 命令行 `touch-modes <mask>` 与 `simulate-touch <electrode> [--release]`，回归用例新增触摸组。

- [ ] **Step 1: 加子命令**

`build_parser()` 中 emotion 之后加：

```python
    touch_modes = subparsers.add_parser("touch-modes", help="set the touch response mask")
    touch_modes.add_argument("modes", type=lambda v: int(v, 0),
                             help="bitmask: 1 reflex, 2 wake, 4 report, 8 diagnostics")
    simulate = subparsers.add_parser("simulate-touch", help="fake a touch without the sensor")
    simulate.add_argument("electrode", type=int, choices=range(0, 12), default=0, nargs="?")
    simulate.add_argument("--release", action="store_true", help="send release instead of press")
```

`command_to_call()` 中加：

```python
    if args.command == "touch-modes":
        return "touch_modes", {"modes": args.modes}
    if args.command == "simulate-touch":
        return "simulate_touch", {"electrode": args.electrode, "pressed": not args.release}
```

- [ ] **Step 2: 扩回归用例**

`REGRESSION_CASES` 的 `("diagnostics", {})` 之前插入：

```python
    # 触摸：先只开本地反射，验证眼睛和手臂；再开诊断位，让 status 带出原始计数。
    # 唤醒与上报两位不进回归 —— 它们会真的发起一轮对话，干扰后续用例。
    ("touch_modes", {"modes": 0x01}),
    ("simulate_touch", {"electrode": 0, "pressed": True}),
    ("simulate_touch", {"electrode": 0, "pressed": False}),
    ("touch_modes", {"modes": 0x09}),
```

- [ ] **Step 3: 本地验证脚本**

```sh
python3 -c "
import sys; sys.path.insert(0,'tools')
import plush_toy_test as t
print(t.command_to_call(['touch-modes','0x09']))
print(t.command_to_call(['simulate-touch','0','--release']))
print(len(t.REGRESSION_CASES),'cases')
"
```

预期：分别输出 `('touch_modes', {'modes': 9})`、`('simulate_touch', {'electrode': 0, 'pressed': False})`、22 条用例。

- [ ] **Step 4: 写 README 的触摸标定一节**

在「文本动作测试」之后新增一节，说明：模块 VCC 接 3V3 的警告；用 `status` 读 `touch_filtered` 与 `touch_baseline`，手指靠近时观察差值；把差值的约六成填回 `config.h` 的 `TOUCH_PRESS_THRESHOLD`、约三成填 `TOUCH_RELEASE_THRESHOLD`（释放阈值必须低于触摸阈值，否则会在临界点反复抖动）；四个模式位的含义与 `touch-modes` 用法。

- [ ] **Step 5: 更新 TODO**

`plans/TODO.md` 中把 D4（MPU6050）之外新增一条，记录触摸阈值仍待实机标定，并注明标定完成前 `TOUCH_PRESS_THRESHOLD` 是猜测值。

- [ ] **Step 6: 提交**

```bash
git add tools/plush_toy_test.py main/boards/plush-toy/README.md docs/superpowers/plans/TODO.md
git commit -m "feat(plush-toy): 触摸测试命令、回归用例与标定文档"
```

---

## 实机验收

烧录后按顺序执行，前一条不过不要往下走：

1. `status` 中 `touch_present` 为 true。为 false 说明 I2C 上探测不到 0x5A，先查接线和 VCC 电压。
2. `status` 中 `touch_filtered` 与 `touch_baseline` 有值，手指靠近电极时 `touch_filtered` 明显下降。这一条不过，阈值无从标定。
3. 按 README 的方法标定阈值并回填 `config.h`，重新烧录。
4. 真实触摸时 `touch_bits` 的 bit0 置位，手指离开后归零。
5. `touch-modes 0x01` 后触摸，眼睛变 happy、手臂欢呼一次，松开后眼睛回 neutral。
6. `touch-modes 0x02` 后触摸，设备进入聆听状态。
7. `touch-modes 0x04` 后触摸，服务端收到一句话并给出回应。
8. 触摸的同时连续做手臂动作，确认共享 I2C 总线上互不干扰。
9. 拔掉 MPR121 模块重启，确认设备仍能正常对话、动手臂、眨眼，且 `touch_present` 为 false。
