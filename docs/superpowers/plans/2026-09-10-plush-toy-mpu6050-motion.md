# 毛绒玩具运动感知（MPU6050）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接入 MPU6050，让玩具感知摇晃与三种姿态，按独立的 `motion_modes` 掩码分发到眼睛、手臂、对话状态机和服务端。

**Architecture:** 三层，与 `Mpr121` → `TouchController` → `PlushBehavior` 同构。`Mpu6050` 只吐三轴原始加速度；`MotionController` 轮询并做姿态判定（带迟滞）与摇晃判定（带不应期），且接受一个抑制回调以屏蔽舵机自振；`PlushBehavior::OnMotion` 按掩码分发。并入现有 `I2C_NUM_0`，不占新 GPIO。

**Tech Stack:** ESP-IDF v6.1、FreeRTOS、`i2c_master` 新驱动、NVS `Settings` 封装、主机侧 g++ 单测。

**Spec:** `docs/superpowers/specs/2026-09-10-plush-toy-mpu6050-motion-design.md`

## Global Constraints

- MPU6050 地址 `0x68`，挂在 `SERVO_I2C_PORT`（`I2C_NUM_0`）上，速率 `SERVO_I2C_HZ`（100000）。不新增 GPIO，不接 INT。
- 模块 VCC 接 3V3。接 5V 会把 SDA(GPIO44)/SCL(GPIO3) 拉到 5V。
- 量程 ±4g（`ACCEL_CONFIG` = 0x08），灵敏度 8192 LSB/g。
- 运动链路任何失败只记状态、保持 `nullptr`，绝不 `ESP_ERROR_CHECK`。没有运动感知的玩具仍须能对话、动手臂、眨眼、感知触摸。
- **读失败用返回值报告，不用哨兵值。** 加速度的 0 是合法值。触摸侧 `ReadFiltered` 返回 0 已在实机标定时混进过假样本，不重蹈覆辙。
- 模式位与触摸同形状但**独立 NVS 键**：命名空间 `plush`，键名 `motion_modes`，位定义 `0x01` 反射、`0x02` 唤醒、`0x04` 上报、`0x08` 诊断，默认 `0x09`。
- 默认反射只用**现有**眼睛预设，不新增情绪。`eye_display.cc` 里没有 `dizzy`。
- 时间必须以参数注入判定逻辑，不得在其中直接读时钟 —— 否则主机侧无法确定性地测不应期与迟滞。
- 观测走 HTTP。应用层控制台静默，打日志的诊断拿不到结果。
- 每个任务结束时跑 `cd main/boards/plush-toy/test && make clean && make test`，全绿才提交。新增 `.cc` 后固件构建前须先 `idf.py reconfigure`，否则 `main/CMakeLists.txt` 的 glob 不会收录，链接期报 undefined reference。

---

### Task 1: Mpu6050 驱动

**Files:**
- Create: `main/boards/plush-toy/mpu6050.h`
- Create: `main/boards/plush-toy/mpu6050.cc`
- Test: `main/boards/plush-toy/test/test_mpu6050.cc`
- Modify: `main/boards/plush-toy/test/Makefile`
- Modify: `main/boards/plush-toy/config.h`

**Interfaces:**
- Consumes: 无
- Produces: `class Mpu6050`，构造 `Mpu6050(i2c_master_bus_handle_t bus, uint8_t addr, uint32_t scl_hz)`；`bool available() const`、`bool Init()`、`bool ReadAccel(int16_t& x, int16_t& y, int16_t& z)`、`std::string Diagnostics()`。

- [ ] **Step 1: 在 config.h 加常量**

紧接触摸那段之后：

```c
// ── 运动：MPU6050 并入同一条 I2C，不占新引脚 ──
// INT 引脚同样无处可接，改为 100ms 轮询。姿态与摇晃都不需要毫秒级响应。
//
// GY-521 板载 4.7k 上拉，比 PCA9685/MPR121 的 10k 低一倍。三块板并联后
// 总上拉约 2.4k。若接入后 I2C 读写失败，或触摸、舵机开始不稳，
// 第一件事是拆掉 GY-521 上那两颗上拉电阻。
#define MPU6050_ADDR             0x68   // AD0 接地或悬空
#define MOTION_POLL_INTERVAL_MS  100
// ±4g 量程。±2g 摇晃时削顶，±8g 以上牺牲静态姿态分辨率。
#define MOTION_ACCEL_FS_SEL      0x08
#define MOTION_LSB_PER_G         8192
```

- [ ] **Step 2: 写失败测试**

创建 `test/test_mpu6050.cc`。fake I2C 与冻结寄存器手法照抄 `test_mpr121.cc`：

```cpp
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
```

- [ ] **Step 3: 加 Makefile 目标并跑测试确认失败**

把 `test_mpu6050` 加进 `test:` 的依赖与执行列表、`clean` 的删除列表，并加规则：

```make
test_mpu6050: test_mpu6050.cc ../mpu6050.cc ../mpu6050.h ../config.h
	$(CXX) $(CXXFLAGS) -o $@ test_mpu6050.cc ../mpu6050.cc
```

跑 `make test_mpu6050`，预期编译失败：`mpu6050.h: No such file or directory`。

- [ ] **Step 4: 写 mpu6050.h**

```cpp
#pragma once

#include <driver/i2c_master.h>
#include <stdint.h>
#include <string>

// MPU6050 六轴传感器驱动。本项目只读加速度计。
//
// 【为什么不读陀螺仪】
// 姿态由重力方向得出，摇晃由加速度幅值判定，两者都不需要角速度。
// 少读 6 个字节，也少一组要标定的参数。寄存器随时可以加。
//
// 【为什么轮询】
// 引脚已用尽，INT 无处可接。姿态与摇晃都不需要毫秒级响应。
//
// 【为什么不继承 I2cDevice】
// 同 pca9685.h / mpr121.h：该基类把 scl_speed_hz 硬编码为 400kHz。
class Mpu6050 {
public:
    Mpu6050(i2c_master_bus_handle_t bus, uint8_t addr, uint32_t scl_hz);
    ~Mpu6050();

    bool available() const { return dev_ != nullptr; }

    // 复位、解除睡眠、设量程与低通，末尾校验 WHO_AM_I 并回读量程寄存器。
    // 只查 WHO_AM_I 不够 —— 它区分不了「能读不能写」。
    bool Init();

    // 一次突发读 6 字节，保证三轴来自同一采样时刻。
    // 失败返回 false 且不改写出参：加速度的 0 是合法值，不能用哨兵值报错。
    bool ReadAccel(int16_t& x, int16_t& y, int16_t& z);

    std::string Diagnostics();

private:
    bool WriteReg(uint8_t reg, uint8_t value);
    bool ReadRegisters(uint8_t reg, uint8_t* data, size_t size);

    i2c_master_dev_handle_t dev_ = nullptr;
    esp_err_t last_write_error_ = ESP_OK;
};
```

- [ ] **Step 5: 写 mpu6050.cc**

```cpp
#include "mpu6050.h"
#include "config.h"

#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include <cstdio>

#define TAG "Mpu6050"

namespace {
constexpr uint8_t kRegConfig = 0x1A;
constexpr uint8_t kRegAccelConfig = 0x1C;
constexpr uint8_t kRegAccelXoutH = 0x3B;
constexpr uint8_t kRegPwrMgmt1 = 0x6B;
constexpr uint8_t kRegWhoAmI = 0x75;

constexpr uint8_t kDeviceReset = 0x80;
constexpr uint8_t kWhoAmIExpected = 0x68;
// DLPF 44Hz：舵机振动的高频分量在进入判定之前就被滤掉一部分。
constexpr uint8_t kDlpf44Hz = 0x03;
constexpr int kTimeoutMs = 1000;
}  // namespace

Mpu6050::Mpu6050(i2c_master_bus_handle_t bus, uint8_t addr, uint32_t scl_hz) {
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

Mpu6050::~Mpu6050() {
    if (dev_ != nullptr)
        i2c_master_bus_rm_device(dev_);
}

bool Mpu6050::WriteReg(uint8_t reg, uint8_t value) {
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

bool Mpu6050::ReadRegisters(uint8_t reg, uint8_t* data, size_t size) {
    if (dev_ == nullptr)
        return false;
    esp_err_t err = i2c_master_transmit_receive(dev_, &reg, 1, data, size, kTimeoutMs);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "读寄存器 0x%02X 失败: %s", reg, esp_err_to_name(err));
        return false;
    }
    return true;
}

bool Mpu6050::Init() {
    if (dev_ == nullptr)
        return false;

    uint8_t who = 0;
    if (!ReadRegisters(kRegWhoAmI, &who, 1) || who != kWhoAmIExpected) {
        ESP_LOGE(TAG, "WHO_AM_I 读到 0x%02X，期望 0x%02X —— 地址不对或不是 MPU6050", who,
                 kWhoAmIExpected);
        return false;
    }

    if (!WriteReg(kRegPwrMgmt1, kDeviceReset))
        return false;
    vTaskDelay(pdMS_TO_TICKS(100));  // 复位后芯片需要时间稳定
    if (!WriteReg(kRegPwrMgmt1, 0x00))  // 解除睡眠
        return false;
    if (!WriteReg(kRegConfig, kDlpf44Hz))
        return false;
    if (!WriteReg(kRegAccelConfig, MOTION_ACCEL_FS_SEL))
        return false;

    uint8_t back = 0;
    if (!ReadRegisters(kRegAccelConfig, &back, 1) || back != MOTION_ACCEL_FS_SEL) {
        ESP_LOGE(TAG, "量程回读 0x%02X，期望 0x%02X —— 写通路不通", back, MOTION_ACCEL_FS_SEL);
        return false;
    }
    ESP_LOGI(TAG, "初始化完成，±4g，%d LSB/g", MOTION_LSB_PER_G);
    return true;
}

bool Mpu6050::ReadAccel(int16_t& x, int16_t& y, int16_t& z) {
    uint8_t raw[6] = {};
    if (!ReadRegisters(kRegAccelXoutH, raw, sizeof(raw)))
        return false;
    x = (int16_t)((raw[0] << 8) | raw[1]);  // MPU6050 是大端，与 MPR121 相反
    y = (int16_t)((raw[2] << 8) | raw[3]);
    z = (int16_t)((raw[4] << 8) | raw[5]);
    return true;
}

std::string Mpu6050::Diagnostics() {
    uint8_t who = 0;
    uint8_t range = 0;
    int16_t x = 0, y = 0, z = 0;
    if (!ReadRegisters(kRegWhoAmI, &who, 1) || !ReadRegisters(kRegAccelConfig, &range, 1) ||
        !ReadAccel(x, y, z))
        return "read_failed";
    char result[160];
    std::snprintf(result, sizeof(result),
                  "who_am_i=0x%02X range=0x%02X ax=%d ay=%d az=%d last_write_error=%s", who, range,
                  x, y, z, esp_err_to_name(last_write_error_));
    return result;
}
```

- [ ] **Step 6: 跑测试确认通过**

```sh
cd main/boards/plush-toy/test && make clean && make test
```

预期：`all Mpu6050 tests passed`，其余测试仍全绿。

- [ ] **Step 7: 提交**

```bash
git add main/boards/plush-toy/mpu6050.h main/boards/plush-toy/mpu6050.cc \
        main/boards/plush-toy/config.h main/boards/plush-toy/test/test_mpu6050.cc \
        main/boards/plush-toy/test/Makefile
git commit -m "feat(plush-toy): 新增 MPU6050 加速度驱动"
```

---

### Task 2: MotionController 判定逻辑

**Files:**
- Create: `main/boards/plush-toy/motion_controller.h`
- Create: `main/boards/plush-toy/motion_controller.cc`
- Test: `main/boards/plush-toy/test/test_motion_controller.cc`
- Modify: `main/boards/plush-toy/test/Makefile`
- Modify: `main/boards/plush-toy/config.h`

**Interfaces:**
- Consumes: Task 1 的 `Mpu6050`
- Produces: `enum class Orientation { kUnknown, kUpright, kLying, kInverted }`；`enum class MotionEvent { kShake, kOrientationChanged }`；`class MotionController`，构造 `MotionController(Mpu6050* mpu)`；`using MotionHandler = std::function<void(MotionEvent, Orientation)>`；`SetHandler`、`SetSuppressor(std::function<bool()>)`、`Start()`、`void ApplySample(int16_t ax, int16_t ay, int16_t az, int64_t now_ms)`、`Orientation orientation() const`、`int shake_hits() const`、`bool available() const`。

- [ ] **Step 1: 在 config.h 加判定参数**

```c
// 姿态门限（重力分量占比，单位 LSB）。进入与离开用不同门限 —— 没有迟滞
// 的话，玩具斜靠在沙发上会在两态边界反复横跳，每跳一次就改一次表情。
#define MOTION_UPRIGHT_ENTER   ((MOTION_LSB_PER_G * 7) / 10)   // +0.7g
#define MOTION_UPRIGHT_EXIT    ((MOTION_LSB_PER_G * 5) / 10)   // +0.5g
#define MOTION_INVERTED_ENTER  (-(MOTION_LSB_PER_G * 7) / 10)  // -0.7g
#define MOTION_INVERTED_EXIT   (-(MOTION_LSB_PER_G * 5) / 10)  // -0.5g

// 摇晃：合矢量对 1g 的偏离超过阈值算一次命中，窗口内命中够数才算摇晃，
// 之后进入不应期。没有不应期的话，一次持续摇晃会刷出几十个事件。
#define MOTION_SHAKE_DELTA     ((MOTION_LSB_PER_G * 35) / 100)  // 0.35g
#define MOTION_SHAKE_WINDOW_MS 1000
#define MOTION_SHAKE_HITS      3
#define MOTION_SHAKE_COOLDOWN_MS 1500

// 玩具竖立时哪一轴对着天。装配后若姿态判反，改这里而不是改判定逻辑。
#define MOTION_UP_AXIS_Z       1
```

- [ ] **Step 2: 写失败测试**

创建 `test/test_motion_controller.cc`。判定逻辑不碰硬件，直接喂样本与时间戳：

```cpp
#include "motion_controller.h"
#include "config.h"

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

// 本测试链接 mpu6050.cc，需要这些 I2C 符号；判定逻辑不碰硬件，给最简实现。
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

struct Record {
    MotionEvent event;
    Orientation orientation;
};

static const int kG = MOTION_LSB_PER_G;

// 竖直静置：Z 轴 +1g，其余为零。
static void FeedUpright(MotionController& c, int64_t& t, int samples) {
    for (int i = 0; i < samples; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(0, 0, kG, t);
}

static void TestSteadyUprightEmitsOneOrientationEvent() {
    std::vector<Record> log;
    MotionController c(nullptr);
    c.SetHandler([&](MotionEvent e, Orientation o) { log.push_back({e, o}); });
    int64_t t = 0;
    FeedUpright(c, t, 20);
    CHECK(log.size() == 1, "从未知态进入竖直只应产生一个事件");
    CHECK(!log.empty() && log[0].orientation == Orientation::kUpright, "首个事件必须是竖直");
    CHECK(c.orientation() == Orientation::kUpright, "当前姿态必须是竖直");
}

static void TestInvertedProducesOneMoreEvent() {
    std::vector<Record> log;
    MotionController c(nullptr);
    c.SetHandler([&](MotionEvent e, Orientation o) { log.push_back({e, o}); });
    int64_t t = 0;
    FeedUpright(c, t, 5);
    for (int i = 0; i < 5; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(0, 0, -kG, t);
    CHECK(log.size() == 2, "竖直转倒置应再产生一个事件");
    CHECK(log.size() == 2 && log[1].orientation == Orientation::kInverted, "第二个事件是倒置");
}

// 迟滞的意义：在门限附近抖动不得反复产生事件。
static void TestHysteresisSuppressesBoundaryChatter() {
    std::vector<Record> log;
    MotionController c(nullptr);
    c.SetHandler([&](MotionEvent e, Orientation o) { log.push_back({e, o}); });
    int64_t t = 0;
    FeedUpright(c, t, 5);
    const size_t after_upright = log.size();
    // 在 0.5g 与 0.7g 之间来回：已进入竖直态，且未跌破离开门限，不应有新事件
    for (int i = 0; i < 10; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(0, 0, (i % 2 == 0) ? (kG * 6) / 10 : (kG * 8) / 10, t);
    CHECK(log.size() == after_upright, "门限之间的抖动不得产生姿态事件");
}

static void TestShakeNeedsEnoughHits() {
    std::vector<Record> log;
    MotionController c(nullptr);
    c.SetHandler([&](MotionEvent e, Orientation o) { log.push_back({e, o}); });
    int64_t t = 0;
    FeedUpright(c, t, 5);
    const size_t before = log.size();
    // 只有两次剧烈样本，不够 MOTION_SHAKE_HITS
    for (int i = 0; i < 2; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(0, 0, kG * 2, t);
    CHECK(log.size() == before, "命中次数不足不得产生摇晃事件");
}

static void TestShakeCooldownCollapsesBurst() {
    std::vector<Record> log;
    MotionController c(nullptr);
    c.SetHandler([&](MotionEvent e, Orientation o) {
        if (e == MotionEvent::kShake)
            log.push_back({e, o});
    });
    int64_t t = 0;
    FeedUpright(c, t, 5);
    // 1.2 秒连续剧烈样本：短于不应期，必须塌缩成一个事件
    for (int i = 0; i < 12; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(0, 0, kG * 2, t);
    CHECK(log.size() == 1, "不应期内的连续剧烈样本只应产生一个摇晃事件");
}

// 不应期是限流不是封禁：过了就必须能再次触发，否则摇两次只响一次。
static void TestShakeFiresAgainAfterCooldown() {
    std::vector<Record> log;
    MotionController c(nullptr);
    c.SetHandler([&](MotionEvent e, Orientation o) {
        if (e == MotionEvent::kShake)
            log.push_back({e, o});
    });
    int64_t t = 0;
    FeedUpright(c, t, 5);
    for (int i = 0; i < 5; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(0, 0, kG * 2, t);
    CHECK(log.size() == 1, "第一阵摇晃产生一个事件");
    t += MOTION_SHAKE_COOLDOWN_MS + MOTION_POLL_INTERVAL_MS;  // 等过不应期
    for (int i = 0; i < 5; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(0, 0, kG * 2, t);
    CHECK(log.size() == 2, "不应期过后第二阵摇晃必须能再次触发");
}

// 舵机自振会被加速度计读到，且摇晃的默认反射是摆手，不抑制会自激。
static void TestSuppressorBlocksShakeButNotOrientation() {
    std::vector<Record> log;
    MotionController c(nullptr);
    c.SetSuppressor([] { return true; });
    c.SetHandler([&](MotionEvent e, Orientation o) { log.push_back({e, o}); });
    int64_t t = 0;
    for (int i = 0; i < 20; ++i, t += MOTION_POLL_INTERVAL_MS)
        c.ApplySample(0, 0, kG * 2, t);
    for (const auto& r : log)
        CHECK(r.event != MotionEvent::kShake, "抑制期间不得产生摇晃事件");
    int64_t t2 = t;
    FeedUpright(c, t2, 5);
    bool saw_orientation = false;
    for (const auto& r : log)
        if (r.event == MotionEvent::kOrientationChanged)
            saw_orientation = true;
    CHECK(saw_orientation, "抑制不得影响姿态判定");
}

static void TestHandlerIsOptional() {
    MotionController c(nullptr);
    c.ApplySample(0, 0, kG, 0);  // 未设 handler 不得崩溃
    CHECK(!c.available(), "驱动为空时 available 必须为 false");
}

int main() {
    TestSteadyUprightEmitsOneOrientationEvent();
    TestInvertedProducesOneMoreEvent();
    TestHysteresisSuppressesBoundaryChatter();
    TestShakeNeedsEnoughHits();
    TestShakeCooldownCollapsesBurst();
    TestShakeFiresAgainAfterCooldown();
    TestSuppressorBlocksShakeButNotOrientation();
    TestHandlerIsOptional();
    if (g_failures)
        return 1;
    std::puts("all MotionController tests passed");
    return 0;
}
```

- [ ] **Step 3: 加 Makefile 目标并跑测试确认失败**

```make
test_motion_controller: test_motion_controller.cc ../motion_controller.cc ../motion_controller.h ../mpu6050.cc ../mpu6050.h ../config.h
	$(CXX) $(CXXFLAGS) -o $@ test_motion_controller.cc ../motion_controller.cc ../mpu6050.cc
```

同样加进 `test:` 与 `clean`。跑 `make test_motion_controller`，预期编译失败：`motion_controller.h: No such file or directory`。

- [ ] **Step 4: 写 motion_controller.h**

```cpp
#pragma once

#include "mpu6050.h"

#include <functional>

enum class Orientation { kUnknown, kUpright, kLying, kInverted };
enum class MotionEvent { kShake, kOrientationChanged };

// 运动判定。只回答「刚被摇了」和「姿态刚变成什么」，
// 不知道该做什么反应 —— 那是 PlushBehavior 的事。
//
// 时间由调用方传入而非内部读时钟：不应期和迟滞必须能在主机侧确定性地测。
class MotionController {
public:
    using MotionHandler = std::function<void(MotionEvent, Orientation)>;
    // 返回 true 表示当前应抑制摇晃判定。舵机动作期间的机械振动会被加速度计
    // 读到，而摇晃的默认反射是摆手，不抑制会自激。
    using Suppressor = std::function<bool()>;

    explicit MotionController(Mpu6050* mpu);

    bool available() const { return mpu_ != nullptr; }
    void SetHandler(MotionHandler handler) { handler_ = std::move(handler); }
    void SetSuppressor(Suppressor suppressor) { suppressor_ = std::move(suppressor); }
    void Start();

    // 公开是为了三个用途：主机侧单测、测试通道的模拟运动、轮询任务自身。
    void ApplySample(int16_t ax, int16_t ay, int16_t az, int64_t now_ms);

    Orientation orientation() const { return orientation_; }
    int shake_hits() const { return shake_hits_; }

private:
    static void TaskEntry(void* arg);
    void Run();
    Orientation ClassifyOrientation(int16_t up_axis_value) const;
    void UpdateShake(int16_t ax, int16_t ay, int16_t az, int64_t now_ms);

    Mpu6050* mpu_ = nullptr;
    MotionHandler handler_;
    Suppressor suppressor_;
    Orientation orientation_ = Orientation::kUnknown;
    int shake_hits_ = 0;
    int64_t shake_window_start_ms_ = 0;
    int64_t shake_cooldown_until_ms_ = 0;
};
```

- [ ] **Step 5: 写 motion_controller.cc**

```cpp
#include "motion_controller.h"
#include "config.h"

#include <esp_log.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#define TAG "MotionController"

MotionController::MotionController(Mpu6050* mpu) : mpu_(mpu) {}

void MotionController::Start() {
    if (mpu_ == nullptr) {
        ESP_LOGW(TAG, "MPU6050 不可用，运动感知已禁用");
        return;
    }
    xTaskCreate(TaskEntry, "motion", 3072, this, 3, nullptr);
    ESP_LOGI(TAG, "运动轮询已启动，周期 %d ms", MOTION_POLL_INTERVAL_MS);
}

void MotionController::TaskEntry(void* arg) { static_cast<MotionController*>(arg)->Run(); }

void MotionController::Run() {
    while (true) {
        int16_t x = 0, y = 0, z = 0;
        // 读失败保留上一次判定，下个周期再读。共享总线上偶发失败是正常的。
        if (mpu_->ReadAccel(x, y, z))
            ApplySample(x, y, z, esp_timer_get_time() / 1000);
        vTaskDelay(pdMS_TO_TICKS(MOTION_POLL_INTERVAL_MS));
    }
}

Orientation MotionController::ClassifyOrientation(int16_t up) const {
    // 迟滞：已在某态时用较松的离开门限，未在该态时用较严的进入门限。
    if (orientation_ == Orientation::kUpright)
        return up > MOTION_UPRIGHT_EXIT ? Orientation::kUpright : Orientation::kLying;
    if (orientation_ == Orientation::kInverted)
        return up < MOTION_INVERTED_EXIT ? Orientation::kInverted : Orientation::kLying;
    if (up > MOTION_UPRIGHT_ENTER)
        return Orientation::kUpright;
    if (up < MOTION_INVERTED_ENTER)
        return Orientation::kInverted;
    return Orientation::kLying;
}

void MotionController::UpdateShake(int16_t ax, int16_t ay, int16_t az, int64_t now_ms) {
    if (now_ms < shake_cooldown_until_ms_)
        return;
    if (suppressor_ && suppressor_())
        return;

    // 用平方和比较，避免开方。阈值同样平方后比较。
    const int64_t magnitude_sq =
        (int64_t)ax * ax + (int64_t)ay * ay + (int64_t)az * az;
    const int64_t high_sq = (int64_t)(MOTION_LSB_PER_G + MOTION_SHAKE_DELTA) *
                            (MOTION_LSB_PER_G + MOTION_SHAKE_DELTA);
    const int64_t low_sq = (int64_t)(MOTION_LSB_PER_G - MOTION_SHAKE_DELTA) *
                           (MOTION_LSB_PER_G - MOTION_SHAKE_DELTA);
    const bool hit = magnitude_sq > high_sq || magnitude_sq < low_sq;

    if (now_ms - shake_window_start_ms_ > MOTION_SHAKE_WINDOW_MS) {
        shake_window_start_ms_ = now_ms;
        shake_hits_ = 0;
    }
    if (!hit)
        return;
    if (++shake_hits_ < MOTION_SHAKE_HITS)
        return;

    shake_hits_ = 0;
    shake_window_start_ms_ = now_ms;
    shake_cooldown_until_ms_ = now_ms + MOTION_SHAKE_COOLDOWN_MS;
    if (handler_)
        handler_(MotionEvent::kShake, orientation_);
}

void MotionController::ApplySample(int16_t ax, int16_t ay, int16_t az, int64_t now_ms) {
    const int16_t up = MOTION_UP_AXIS_Z ? az : ay;
    const Orientation next = ClassifyOrientation(up);
    if (next != orientation_) {
        orientation_ = next;
        if (handler_)
            handler_(MotionEvent::kOrientationChanged, orientation_);
    }
    UpdateShake(ax, ay, az, now_ms);
}
```

- [ ] **Step 6: 跑测试确认通过**

```sh
cd main/boards/plush-toy/test && make clean && make test
```

预期：`all MotionController tests passed`，其余全绿。

- [ ] **Step 7: 提交**

```bash
git add main/boards/plush-toy/motion_controller.h main/boards/plush-toy/motion_controller.cc \
        main/boards/plush-toy/config.h main/boards/plush-toy/test/test_motion_controller.cc \
        main/boards/plush-toy/test/Makefile
git commit -m "feat(plush-toy): 新增姿态与摇晃判定"
```

---

### Task 3: 舵机忙标志与行为分发

**Files:**
- Modify: `main/boards/plush-toy/limb_controller.h`
- Modify: `main/boards/plush-toy/limb_controller.cc`
- Modify: `main/boards/plush-toy/config.h`
- Modify: `main/boards/plush-toy/plush_behavior.h`
- Modify: `main/boards/plush-toy/plush_behavior.cc`

**Interfaces:**
- Consumes: Task 2 的 `MotionEvent`、`Orientation`
- Produces: `LimbController::busy()`；`PlushBehavior::OnMotion(MotionEvent, Orientation)`、`motion_modes()`、`SetMotionModes(uint32_t)`。

- [ ] **Step 1: config.h 加运动模式位与舵机沉降窗口**

```c
#define MOTION_MODE_REFLEX   0x01
#define MOTION_MODE_WAKE     0x02
#define MOTION_MODE_REPORT   0x04
#define MOTION_MODE_DIAG     0x08
#define MOTION_MODES_DEFAULT (MOTION_MODE_REFLEX | MOTION_MODE_DIAG)

// 动作结束后机械振动还会持续一小段，这段时间内继续抑制摇晃判定。
#define MOTION_SERVO_SETTLE_MS 400
```

- [ ] **Step 2: 给 LimbController 加 busy()**

`limb_controller.h` public 区加：

```cpp
    // 动作执行期间及结束后的沉降窗口内为 true。
    // 运动感知靠它屏蔽舵机自振，否则摆手会被判成摇晃、再触发摆手。
    bool busy() const;
```

private 区加：

```cpp
    int64_t busy_until_us_ = 0;
```

`limb_controller.cc` 顶部加 `#include <esp_timer.h>`，`Run()` 改为在动作前后维护该时间戳：

```cpp
void LimbController::Run() {
    Item it;
    while (true) {
        if (xQueueReceive(queue_, &it, portMAX_DELAY) == pdTRUE) {
            busy_until_us_ = INT64_MAX;   // 动作期间无条件为忙
            Perform(it.g, it.times);
            vTaskDelay(pdMS_TO_TICKS(200));
            Relax();
            vTaskDelay(pdMS_TO_TICKS(300));   // 强制冷却，让电源轨恢复
            busy_until_us_ = esp_timer_get_time() + MOTION_SERVO_SETTLE_MS * 1000;
        }
    }
}

bool LimbController::busy() const { return esp_timer_get_time() < busy_until_us_; }
```

`limb_controller.cc` 需要 `#include "config.h"`（已有）与 `<cstdint>`。

- [ ] **Step 3: 扩 plush_behavior.h**

public 区加：

```cpp
    // 由 MotionController 转发而来。按 motion_modes 掩码分发。
    void OnMotion(MotionEvent event, Orientation orientation);

    uint32_t motion_modes() const { return motion_modes_; }
    void SetMotionModes(uint32_t modes);
```

private 区加 `uint32_t motion_modes_ = MOTION_MODES_DEFAULT;`，文件顶部加 `#include "motion_controller.h"`。

- [ ] **Step 4: 实现 OnMotion 与持久化**

`plush_behavior.cc` 构造函数末尾追加载入：

```cpp
    motion_modes_ = (uint32_t)settings.GetInt("motion_modes", MOTION_MODES_DEFAULT);
```

新增：

```cpp
void PlushBehavior::SetMotionModes(uint32_t modes) {
    motion_modes_ = modes;
    Settings settings("plush", true);
    settings.SetInt("motion_modes", (int32_t)modes);
    ESP_LOGI(TAG, "运动模式掩码改为 0x%02X", (unsigned)modes);
}

void PlushBehavior::OnMotion(MotionEvent event, Orientation orientation) {
    ESP_LOGI(TAG, "运动事件 %d 姿态 %d，掩码 0x%02X", (int)event, (int)orientation,
             (unsigned)motion_modes_);

    if ((motion_modes_ & MOTION_MODE_REFLEX) != 0 && display_ != nullptr) {
        if (event == MotionEvent::kShake) {
            display_->SetEmotion("confused");
            if (limbs_ != nullptr && limbs_->available())
                limbs_->Enqueue(Gesture::kWaveBoth, 1);
        } else {
            // 姿态变化不带手臂动作：搬动玩具时动手臂容易卡住，还白费电流。
            switch (orientation) {
                case Orientation::kInverted: display_->SetEmotion("surprised"); break;
                case Orientation::kLying:    display_->SetEmotion("sleepy"); break;
                case Orientation::kUpright:  display_->SetEmotion("neutral"); break;
                default: break;
            }
        }
    }

    // 姿态变化不发起对话：搬动玩具太频繁，会把对话刷爆。只有摇晃才上行。
    if (event != MotionEvent::kShake)
        return;

    auto& app = Application::GetInstance();
    if ((motion_modes_ & MOTION_MODE_REPORT) != 0) {
        // 与 OnTouch 同理：WakeWordInvoke 自带唤醒，与 WAKE 位是包含关系。
        app.WakeWordInvoke("有人在摇晃我");
    } else if ((motion_modes_ & MOTION_MODE_WAKE) != 0) {
        if (app.GetDeviceState() == kDeviceStateIdle)
            app.StartListening();
    }
}
```

- [ ] **Step 5: 构建验证**

```sh
cd main/boards/plush-toy/test && make clean && make test
cd /Users/lianjia/Workspace/xiaozhi-esp32
source ~/.espressif/tools/activate_idf_v6.1.sh && idf.py reconfigure && idf.py build
```

预期：主机测试全绿，固件编译零错误零警告。

- [ ] **Step 6: 提交**

```bash
git add main/boards/plush-toy/limb_controller.h main/boards/plush-toy/limb_controller.cc \
        main/boards/plush-toy/config.h main/boards/plush-toy/plush_behavior.h \
        main/boards/plush-toy/plush_behavior.cc
git commit -m "feat(plush-toy): 运动模式掩码、默认反射与舵机自振抑制"
```

---

### Task 4: 板级接线

**Files:**
- Modify: `main/boards/plush-toy/plush_toy_board.cc`

**Interfaces:**
- Consumes: Task 1-3
- Produces: 成员 `Mpu6050* mpu6050_`、`MotionController* motion_`，供 Task 5 读取。

- [ ] **Step 1: include 与成员**

顶部按字母序插入 `#include "motion_controller.h"` 与 `#include "mpu6050.h"`。私有成员区在 `touch_` 之后加：

```cpp
    Mpu6050* mpu6050_ = nullptr;
    MotionController* motion_ = nullptr;
```

- [ ] **Step 2: 初始化方法**

放在 `InitializeTouch()` 之后：

```cpp
    // 运动链路的任何失败都不得影响对话 —— 与舵机、触摸同一原则。
    void InitializeMotion() {
        if (servo_bus_ == nullptr)
            return;
        if (i2c_master_probe(servo_bus_, MPU6050_ADDR, 100) != ESP_OK) {
            ESP_LOGE(TAG,
                     "MPU6050(0x%02X) 无响应。请检查：VCC 是否接 3V3、是否共地、"
                     "AD0 是否接地。若同时触摸或舵机也开始不稳，先拆掉 GY-521 "
                     "板载的 4.7k 上拉电阻",
                     MPU6050_ADDR);
            return;
        }
        mpu6050_ = new Mpu6050(servo_bus_, MPU6050_ADDR, SERVO_I2C_HZ);
        if (!mpu6050_->Init()) {
            delete mpu6050_;
            mpu6050_ = nullptr;
        }
    }
```

- [ ] **Step 3: 构造函数里启动**

在 `touch_->Start();` 之后插入：

```cpp
        InitializeMotion();
        motion_ = new MotionController(mpu6050_);
        auto* limbs = limbs_;
        motion_->SetSuppressor([limbs]() { return limbs != nullptr && limbs->busy(); });
        motion_->SetHandler([behavior](MotionEvent event, Orientation orientation) {
            behavior->OnMotion(event, orientation);
        });
        motion_->Start();
```

`behavior` 局部变量在触摸那段已经声明过，直接复用。

- [ ] **Step 4: 构建验证**

```sh
source ~/.espressif/tools/activate_idf_v6.1.sh && idf.py reconfigure && idf.py build
```

预期：编译通过。

- [ ] **Step 5: 提交**

```bash
git add main/boards/plush-toy/plush_toy_board.cc
git commit -m "feat(plush-toy): 板级接入 MPU6050 运动感知"
```

---

### Task 5: HTTP 观测与测试动作

**Files:**
- Modify: `main/boards/plush-toy/test_http_channel.cc`
- Modify: `main/boards/plush-toy/plush_toy_board.cc`
- Test: `main/boards/plush-toy/test/test_http_channel.cc`

**Interfaces:**
- Consumes: Task 4 的 `mpu6050_`、`motion_`，Task 3 的 `motion_modes()` / `SetMotionModes()`
- Produces: 测试动作 `motion_modes`（参数 `modes` 整数）与 `simulate_motion`（参数 `kind` 字符串，取值 `shake`、`upright`、`lying`、`inverted`）。

- [ ] **Step 1: 写失败测试**

`test/test_http_channel.cc` 在触摸相关断言之后加：

```cpp
    CHECK(channel.Dispatch("motion_modes", R"({"modes":9})"),
          "whitelisted motion_modes must dispatch");
    CHECK(scheduled_action == "motion_modes", "motion_modes must reach the scheduler");
    CHECK(channel.Dispatch("simulate_motion", R"({"kind":"shake"})"),
          "whitelisted simulate_motion must dispatch");
    CHECK(channel.StatusJson().find("\"simulate_motion\"") != std::string::npos,
          "status must list simulate_motion");
```

- [ ] **Step 2: 跑测试确认失败**

```sh
cd main/boards/plush-toy/test && make test_http_channel && ./test_http_channel
```

预期：`FAIL: whitelisted motion_modes must dispatch` 等三条。

- [ ] **Step 3: 白名单与动作列表**

`test_http_channel.cc` 的 `IsAllowedAction` 加入 `motion_modes` 与 `simulate_motion`；`StatusJson()` 的 actions 数组同步加入这两个名字。

- [ ] **Step 4: 板级 status 片段**

`TestStatusFragment()` 末尾、`return json;` 之前插入：

```cpp
        json += ",\"motion_modes\":" +
                std::to_string(behavior_ != nullptr ? behavior_->motion_modes() : 0);
        json += ",\"motion_present\":";
        json += (mpu6050_ != nullptr ? "true" : "false");
        if (mpu6050_ != nullptr && motion_ != nullptr && behavior_ != nullptr &&
            (behavior_->motion_modes() & MOTION_MODE_DIAG) != 0) {
            int16_t ax = 0, ay = 0, az = 0;
            // 读失败就不报这三个字段，而不是报 0 —— 0 是合法加速度值。
            if (mpu6050_->ReadAccel(ax, ay, az)) {
                json += ",\"accel\":[" + std::to_string(ax) + "," + std::to_string(ay) + "," +
                        std::to_string(az) + "]";
            }
            json += ",\"orientation\":" + std::to_string((int)motion_->orientation());
            json += ",\"shake_hits\":" + std::to_string(motion_->shake_hits());
        }
```

- [ ] **Step 5: 板级动作分支**

`ScheduleTestAction` 在 `diagnostics` 分支之前插入：

```cpp
            } else if (action == "motion_modes" && behavior_ != nullptr) {
                const auto* modes = cJSON_GetObjectItem(arguments, "modes");
                if (cJSON_IsNumber(modes))
                    behavior_->SetMotionModes((uint32_t)modes->valueint);
            } else if (action == "simulate_motion" && motion_ != nullptr) {
                // 不碰硬件验证四条响应路径。摇晃靠连喂剧烈样本，姿态靠喂重力方向，
                // 都走 ApplySample，与真实轮询同一条路径。
                const auto* kind = cJSON_GetObjectItem(arguments, "kind");
                const std::string value = cJSON_IsString(kind) ? kind->valuestring : "shake";
                int64_t now = esp_timer_get_time() / 1000;
                if (value == "shake") {
                    for (int i = 0; i < MOTION_SHAKE_HITS; ++i, now += MOTION_POLL_INTERVAL_MS)
                        motion_->ApplySample(0, 0, MOTION_LSB_PER_G * 2, now);
                } else if (value == "inverted") {
                    motion_->ApplySample(0, 0, -MOTION_LSB_PER_G, now);
                } else if (value == "lying") {
                    motion_->ApplySample(MOTION_LSB_PER_G, 0, 0, now);
                } else {
                    motion_->ApplySample(0, 0, MOTION_LSB_PER_G, now);
                }
```

`plush_toy_board.cc` 顶部需加 `#include <esp_timer.h>`。

- [ ] **Step 6: 验证并提交**

```sh
cd main/boards/plush-toy/test && make clean && make test
cd /Users/lianjia/Workspace/xiaozhi-esp32
source ~/.espressif/tools/activate_idf_v6.1.sh && idf.py build
```

```bash
git add main/boards/plush-toy/test_http_channel.cc main/boards/plush-toy/plush_toy_board.cc \
        main/boards/plush-toy/test/test_http_channel.cc
git commit -m "feat(plush-toy): HTTP 通道暴露运动状态与模拟运动"
```

---

### Task 6: 测试脚本、回归与文档

**Files:**
- Modify: `tools/plush_toy_test.py`
- Modify: `main/boards/plush-toy/README.md`
- Modify: `docs/superpowers/plans/TODO.md`

- [ ] **Step 1: 加子命令**

```python
    motion_modes = subparsers.add_parser("motion-modes", help="set the motion response mask")
    motion_modes.add_argument("modes", type=lambda v: int(v, 0),
                              help="bitmask: 1 reflex, 2 wake, 4 report, 8 diagnostics")
    simulate_motion = subparsers.add_parser("simulate-motion",
                                            help="fake a motion event without moving the toy")
    simulate_motion.add_argument("kind", choices=("shake", "upright", "lying", "inverted"),
                                 default="shake", nargs="?")
```

`command_to_call()` 加：

```python
    if args.command == "motion-modes":
        return "motion_modes", {"modes": args.modes}
    if args.command == "simulate-motion":
        return "simulate_motion", {"kind": args.kind}
```

- [ ] **Step 2: 扩回归用例**

在触摸那组之后、`("diagnostics", {})` 之前插入：

```python
    # 运动：同样只开本地反射与诊断。姿态按 竖→躺→倒→竖 走一圈，
    # 确认每次跨态都产生事件且能回到初态。
    ("motion_modes", {"modes": 0x01}),
    ("simulate_motion", {"kind": "shake"}),
    ("simulate_motion", {"kind": "lying"}),
    ("simulate_motion", {"kind": "inverted"}),
    ("simulate_motion", {"kind": "upright"}),
    ("motion_modes", {"modes": 0x09}),
```

- [ ] **Step 3: 本地验证**

```sh
python3 -c "
import sys; sys.path.insert(0,'tools')
import plush_toy_test as t
print(t.command_to_call(['motion-modes','0x09']))
print(t.command_to_call(['simulate-motion','inverted']))
print(len(t.REGRESSION_CASES),'cases')
"
```

预期：`('motion_modes', {'modes': 9})`、`('simulate_motion', {'kind': 'inverted'})`、28 条用例。

- [ ] **Step 4: README 新增「运动标定」一节**

内容需包含：接线图（VCC 接 3V3、AD0 接地、INT 与 XDA/XCL 不接）；GY-521 上拉并联导致总上拉降至约 2.4k 的风险与处置（拆掉它的上拉电阻）；用 `status` 的 `accel` 三轴确认静置时合矢量接近 8192；若姿态判反改 `MOTION_UP_AXIS_Z` 而不是改判定逻辑；四个模式位含义与 `motion-modes` 用法；`simulate-motion` 的四种取值。

- [ ] **Step 5: 更新 TODO**

把 D4 从「待接入」改为「代码已完成，阈值待实机标定」，并列出待标定项：`MOTION_SHAKE_DELTA`、`MOTION_SHAKE_HITS`、姿态四个门限、`MOTION_SERVO_SETTLE_MS`。

- [ ] **Step 6: 提交**

```bash
git add tools/plush_toy_test.py main/boards/plush-toy/README.md docs/superpowers/plans/TODO.md
git commit -m "feat(plush-toy): 运动测试命令、回归用例与标定文档"
```

---

## 实机验收

前一条不过不要往下走：

1. `status` 中 `motion_present` 为 true。为 false 先查接线与 VCC 电压。
2. `status` 中 `accel` 三轴随姿态变化，静置时合矢量接近 8192（1g）。这一条不过，阈值无从标定。
3. 玩具竖立，确认 `orientation` 为 1（竖直）。若为 3（倒置）说明装配方向相反，改 `MOTION_UP_AXIS_Z` 或轴符号。
4. 三种姿态各停留几秒，确认事件只在跨态时产生一次。
5. 玩具斜靠不同角度，确认没有反复横跳。
6. 手动摇晃，确认产生摇晃事件且一次摇晃只产生一个。
7. 触发一次手臂动作，确认**不**产生摇晃事件。这是抑制机制的关键验收。
8. 拔掉 MPU6050 重启，确认对话、手臂、眼睛、触摸全部照常。
9. 三块 I2C 设备同时工作，重跑触摸标定读数，确认未因总线上拉变化而退化。
