# 毛绒玩具肢体动作 实现计划（计划二 / 共二）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `plush-toy` 板型通过 PCA9685 驱动两个 SG90 舵机，具备状态反射动作、情绪联动手势与 LLM 可调用的手势工具。

**Architecture:** 三层。`Pca9685` 继承仓库既有的 `I2cDevice`，只管寄存器；`LimbController` 管角度、行程限制、动作队列串行化与泄力；`PlushBehavior` 起一个 50Hz 任务轮询设备状态，把状态与情绪翻译成手势。服务端零代码改动，仅配角色 prompt。

**Tech Stack:** ESP-IDF v6.1、`i2c_master` 新驱动、PCA9685、C++17

**Spec:** `docs/superpowers/specs/2026-09-05-plush-toy-design.md`

**前置：** 计划一 Task 1（板型骨架）已完成并提交（`737bdf7`、`83501ef`）。眼睛显示部分（计划一 Task 2–7）与本计划无依赖，可并行或后做。

## 构建环境（每次必须）

EIM 把 `idf.py` 定义成 **shell 函数**而非 PATH 上的可执行文件，`scripts/build.py` 内部用 `subprocess` 调它会报 `FileNotFoundError`。必须显式把 `$IDF_PATH/tools` 加进 PATH：

```bash
source ~/.espressif/tools/activate_idf_v6.1.sh
export PATH="$IDF_PATH/tools:$PATH"        # 缺这行 build.py 必失败
python3 scripts/build.py plush-toy          # 或 idf.py build
```

**新增 `.cc` 文件后必须 reconfigure**：`main/CMakeLists.txt:869` 用 `file(GLOB)` 收集板目录下的源文件，而 glob 只在 configure 时求值一次。新加的文件不会自动纳入编译，表现为链接期 `undefined reference`。执行 `idf.py reconfigure` 后再 build。

烧录与串口监看：

```bash
idf.py -p /dev/cu.usbmodem5C834268091 flash
```

## Global Constraints

以下常数均为 2026-09-07 实机验证所得，**不得改为推算值**：

- PCA9685 地址 `0x40`；`0x70` 是同一芯片的 ALLCALL 广播地址，非第二设备
- 50Hz 对应 `PRE_SCALE = 121`（写入后回读一致）
- 角度→计数：`us = 500 + (deg + 90) * 2000 / 180`；`count = us * 4096 / 20000`
- 工作行程 **±30°**，实测无卡滞；超出不得放开
- 舵机 I2C 走 **`I2C_NUM_0`**，SDA=GPIO44（丝印 `RX`）、SCL=GPIO3。摄像头 SCCB 占 `I2C_NUM_1`（由 `CONFIG_SCCB_HARDWARE_I2C_PORT1` 决定，`camera_config_t.sccb_i2c_port` 是死字段）。`plush_toy_board.cc` 有 `static_assert` 守住
- **供电硬约束（实测）**：双路**无间歇连续**摆动会触发 `BROWNOUT` 掉电重启（可复现两次）；双路**带 500ms 间歇**的摆动可通过。因此动作队列必须串行、动作之间必须有泄力间歇——这既是塑料齿保护，也是供电管理
- `SERVO_LEFT_CHANNEL = 0` / `SERVO_RIGHT_CHANNEL = 1` 为约定，装配后若装反只改这两行
- 不得修改板型目录以外的现有文件

---

### Task 1: Pca9685 驱动与启动自检

**Files:**
- Create: `main/boards/plush-toy/pca9685.h`
- Create: `main/boards/plush-toy/pca9685.cc`
- Modify: `main/boards/plush-toy/plush_toy_board.cc`

**Interfaces:**
- Consumes: `I2cDevice`（`main/boards/common/i2c_device.h`）
- Produces: `class Pca9685 : public I2cDevice`，方法 `bool Init(int freq_hz)`、`void SetPulseUs(int ch, int us)`、`void AllOff()`、`uint8_t ReadPrescale()`

- [ ] **Step 1: 写 `pca9685.h`**

```cpp
#pragma once

#include "i2c_device.h"

#include <stdint.h>

// PCA9685 16 路 PWM 驱动。本项目只用前两路驱动舵机。
// 寄存器操作已于 2026-09-07 在实机验证通过。
class Pca9685 : public I2cDevice {
public:
    Pca9685(i2c_master_bus_handle_t bus, uint8_t addr);

    // 设置 PWM 频率并唤醒芯片。返回 false 表示回读校验不通过。
    bool Init(int freq_hz);

    // 直接设置某路的脉宽（微秒）。ch 为 0-15。
    void SetPulseUs(int ch, int us);

    // 关闭全部 16 路输出，舵机泄力。
    void AllOff();

    // 回读 PRE_SCALE，用于验证芯片确实在响应而非 I2C 空写不报错。
    uint8_t ReadPrescale();
};
```

- [ ] **Step 2: 写 `pca9685.cc`**

`I2cDevice::WriteReg` 一次只写一字节。设置一路需要连写 4 个寄存器（ON_L/ON_H/OFF_L/OFF_H），用基类 protected 的 `i2c_device_` 句柄做一次突发写更高效，也避免中途被打断。

```cpp
#include "pca9685.h"

#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#define TAG "Pca9685"

namespace {
constexpr uint8_t kRegMode1      = 0x00;
constexpr uint8_t kRegMode2      = 0x01;
constexpr uint8_t kRegLed0OnL    = 0x06;
constexpr uint8_t kRegAllLedOnL  = 0xFA;
constexpr uint8_t kRegPrescale   = 0xFE;

constexpr uint8_t kMode1Restart  = 0x80;
constexpr uint8_t kMode1AutoInc  = 0x20;
constexpr uint8_t kMode1Sleep    = 0x10;
constexpr uint8_t kMode1AllCall  = 0x01;
constexpr uint8_t kMode2OutDrv   = 0x04;
}  // namespace

Pca9685::Pca9685(i2c_master_bus_handle_t bus, uint8_t addr) : I2cDevice(bus, addr) {}

bool Pca9685::Init(int freq_hz) {
    // 改 PRE_SCALE 前必须进睡眠，这是芯片的硬性要求
    WriteReg(kRegMode1, kMode1Sleep);
    vTaskDelay(pdMS_TO_TICKS(5));

    uint8_t prescale = (uint8_t)((25000000.0 / (4096.0 * freq_hz)) + 0.5) - 1;
    WriteReg(kRegPrescale, prescale);

    WriteReg(kRegMode1, kMode1AutoInc | kMode1AllCall);
    vTaskDelay(pdMS_TO_TICKS(5));
    WriteReg(kRegMode1, kMode1Restart | kMode1AutoInc | kMode1AllCall);
    WriteReg(kRegMode2, kMode2OutDrv);

    uint8_t back = ReadPrescale();
    if (back != prescale) {
        ESP_LOGE(TAG, "PRE_SCALE 回读 %u，期望 %u —— 芯片未正确响应", back, prescale);
        return false;
    }
    ESP_LOGI(TAG, "初始化完成，%d Hz，PRE_SCALE=%u", freq_hz, prescale);
    return true;
}

uint8_t Pca9685::ReadPrescale() {
    return ReadReg(kRegPrescale);
}

void Pca9685::SetPulseUs(int ch, int us) {
    // 一个 20000us 周期对应 4096 计数
    uint16_t off = (uint16_t)((us * 4096) / 20000);
    uint8_t buf[5] = {
        (uint8_t)(kRegLed0OnL + 4 * ch),
        0x00, 0x00,                        // ON 计数固定为 0
        (uint8_t)(off & 0xFF),
        (uint8_t)((off >> 8) & 0x0F),
    };
    i2c_master_transmit(i2c_device_, buf, sizeof(buf), 1000);
}

void Pca9685::AllOff() {
    // OFF_H 的 bit4 置 1 表示该路全关
    uint8_t buf[5] = {kRegAllLedOnL, 0x00, 0x00, 0x00, 0x10};
    i2c_master_transmit(i2c_device_, buf, sizeof(buf), 1000);
}
```

- [ ] **Step 3: 在板级代码建 I2C 总线并实例化**

`plush_toy_board.cc` 加 `#include "pca9685.h"` 与 `#include <driver/i2c_master.h>`，新增成员 `Pca9685* pca_ = nullptr;` 和：

```cpp
    void InitializeServoBus() {
        i2c_master_bus_config_t cfg = {};
        cfg.i2c_port = SERVO_I2C_PORT;
        cfg.sda_io_num = SERVO_I2C_SDA_PIN;
        cfg.scl_io_num = SERVO_I2C_SCL_PIN;
        cfg.clk_source = I2C_CLK_SRC_DEFAULT;
        cfg.glitch_ignore_cnt = 7;
        cfg.flags.enable_internal_pullup = true;
        i2c_master_bus_handle_t bus = nullptr;
        esp_err_t e = i2c_new_master_bus(&cfg, &bus);
        if (e != ESP_OK) {
            ESP_LOGE(TAG, "舵机 I2C 总线创建失败: %s（舵机将不可用）", esp_err_to_name(e));
            return;
        }
        if (i2c_master_probe(bus, PCA9685_ADDR, 100) != ESP_OK) {
            ESP_LOGE(TAG, "PCA9685(0x%02X) 无响应，检查 SDA/SCL 是否接反、VCC 是否接 3V3、是否共地",
                     PCA9685_ADDR);
            return;
        }
        pca_ = new Pca9685(bus, PCA9685_ADDR);
        if (!pca_->Init(SERVO_PWM_FREQ_HZ)) {
            delete pca_;
            pca_ = nullptr;
            return;
        }
        pca_->AllOff();
    }
```

在构造函数中 `InitializeCamera();` 之后调用。

**设计要点**：舵机不可用时**不得 `ESP_ERROR_CHECK` 崩溃**——玩具没有手臂仍应能正常对话。所有失败路径都只记日志并把 `pca_` 留为 `nullptr`。

- [ ] **Step 4: 编译**

```bash
source ~/.espressif/tools/activate_idf_v6.1.sh && export PATH="$IDF_PATH/tools:$PATH"
idf.py build
```

Expected: `Project build complete`

- [ ] **Step 5: 烧录并确认自检日志**

```bash
idf.py -p /dev/cu.usbmodem5C834268091 flash
```

Expected 串口出现：`Pca9685: 初始化完成，50 Hz，PRE_SCALE=121`

**已实测发生并已解决**：最初让 `Pca9685` 继承 `I2cDevice`，回读得到 **217** 而非 121。原因是 `I2cDevice` 构造函数把 `scl_speed_hz` 硬编码为 **400kHz**（`main/boards/common/i2c_device.cc:12`），在本项目的面包板飞线上会导致寄存器读写失真。

解决方案：`Pca9685` **不继承 `I2cDevice`**，自持 `i2c_master_dev_handle_t` 并使用 `SERVO_I2C_HZ`（100kHz）。改基类会影响全部 100+ 个板型，不可取。这是对仓库惯例的一处有意偏离，理由写在 `pca9685.h` 的类注释里。

降到 100kHz 后回读恢复 121。

- [ ] **Step 6: 提交**

```bash
git add main/boards/plush-toy/
git commit -m "feat(plush-toy): PCA9685 驱动与启动自检"
```

---

### Task 2: LimbController —— 角度、行程限制、串行队列与泄力

**Files:**
- Create: `main/boards/plush-toy/limb_controller.h`
- Create: `main/boards/plush-toy/limb_controller.cc`
- Modify: `main/boards/plush-toy/plush_toy_board.cc`

**Interfaces:**
- Consumes: `Pca9685`
- Produces: `class LimbController`，方法 `void Start()`、`bool Enqueue(Gesture g, int times)`、`void Home()`、`bool available() const`

- [ ] **Step 1: 写 `limb_controller.h`**

```cpp
#pragma once

#include "pca9685.h"

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>

enum class Gesture {
    kHome,        // 双臂归中并泄力
    kWaveLeft,    // 左手挥动
    kWaveRight,   // 右手挥动
    kWaveBoth,
    kHug,         // 双臂张开并保持
    kCheer,       // 双臂反相摆动
    kDroop,       // 双臂下垂
    kLean,        // 双臂微微前倾（聆听态）
};

class LimbController {
public:
    explicit LimbController(Pca9685* pca);

    void Start();                                  // 启动动作任务
    bool Enqueue(Gesture g, int times = 1);        // 入队；队列满时返回 false
    bool available() const { return pca_ != nullptr; }

private:
    static void TaskEntry(void* arg);
    void Run();
    void Perform(Gesture g, int times);
    void MoveTo(int left_deg, int right_deg, int step_ms);
    void Relax();                                  // 断输出泄力

    Pca9685* pca_;
    QueueHandle_t queue_ = nullptr;
    int left_deg_ = 0;
    int right_deg_ = 0;
};
```

- [ ] **Step 2: 实现 `limb_controller.cc` 的核心约束**

三条硬性规则，全部来自实测与 spec §4.4：

```cpp
#include "limb_controller.h"
#include "config.h"

#include <esp_log.h>
#include <algorithm>

#define TAG "LimbController"

namespace {
struct Item { Gesture g; int times; };

// 角度 → 脉宽。SG90：-90°=500us，+90°=2500us
inline int DegToUs(int deg) {
    deg = std::clamp(deg, -SERVO_MAX_ANGLE, SERVO_MAX_ANGLE);   // 行程硬限制
    return SERVO_MIN_PULSE_US +
           (deg + 90) * (SERVO_MAX_PULSE_US - SERVO_MIN_PULSE_US) / 180;
}
}  // namespace

LimbController::LimbController(Pca9685* pca) : pca_(pca) {
    queue_ = xQueueCreate(4, sizeof(Item));
}

void LimbController::Start() {
    if (pca_ == nullptr) {
        ESP_LOGW(TAG, "PCA9685 不可用，肢体动作已禁用");
        return;
    }
    xTaskCreate(TaskEntry, "limb", 3072, this, 3, nullptr);
}

bool LimbController::Enqueue(Gesture g, int times) {
    if (pca_ == nullptr || queue_ == nullptr) return false;
    Item it{g, times};
    // 不等待：队列满说明上一个动作还没做完，直接丢弃新动作。
    // 这是串行化的关键——绝不允许两个手势叠加，合成角度会超出机械限位。
    return xQueueSend(queue_, &it, 0) == pdTRUE;
}

void LimbController::TaskEntry(void* arg) {
    static_cast<LimbController*>(arg)->Run();
}

void LimbController::Run() {
    Item it;
    while (true) {
        if (xQueueReceive(queue_, &it, portMAX_DELAY) == pdTRUE) {
            Perform(it.g, it.times);
            // 每个动作结束后必然泄力。既保护 SG90 塑料齿（毛绒布料的持续
            // 回弹力是打齿主因），也是供电管理——实测双路无间歇连续动作
            // 会触发 BROWNOUT，间歇是必需的而非可选优化。
            vTaskDelay(pdMS_TO_TICKS(200));
            Relax();
            vTaskDelay(pdMS_TO_TICKS(300));   // 强制冷却，让电源轨恢复
        }
    }
}

void LimbController::MoveTo(int left_deg, int right_deg, int step_ms) {
    // 分步逼近，绝不瞬间大幅跳变——急转是电流尖峰的主要来源
    const int kStep = 2;
    while (left_deg_ != left_deg || right_deg_ != right_deg) {
        if (left_deg_ < left_deg)  left_deg_  = std::min(left_deg_ + kStep, left_deg);
        else if (left_deg_ > left_deg) left_deg_ = std::max(left_deg_ - kStep, left_deg);
        if (right_deg_ < right_deg) right_deg_ = std::min(right_deg_ + kStep, right_deg);
        else if (right_deg_ > right_deg) right_deg_ = std::max(right_deg_ - kStep, right_deg);

        pca_->SetPulseUs(SERVO_LEFT_CHANNEL,  DegToUs(left_deg_));
        pca_->SetPulseUs(SERVO_RIGHT_CHANNEL, DegToUs(right_deg_));
        vTaskDelay(pdMS_TO_TICKS(step_ms));
    }
}

void LimbController::Relax() {
    pca_->AllOff();
}
```

- [ ] **Step 3: 实现 `Perform` 的手势**

参数取自 spec §4.4。注意 `kCheer` 每个来回之间**必须有停顿**——这正是实测中区分「通过」与「BROWNOUT」的关键。

```cpp
void LimbController::Perform(Gesture g, int times) {
    switch (g) {
        case Gesture::kHome:
            MoveTo(0, 0, 16);
            break;
        case Gesture::kWaveLeft:
            for (int i = 0; i < times; i++) {
                MoveTo(25, right_deg_, 12);
                MoveTo(-10, right_deg_, 12);
            }
            MoveTo(0, right_deg_, 16);
            break;
        case Gesture::kWaveRight:
            for (int i = 0; i < times; i++) {
                MoveTo(left_deg_, 25, 12);
                MoveTo(left_deg_, -10, 12);
            }
            MoveTo(left_deg_, 0, 16);
            break;
        case Gesture::kWaveBoth:
            for (int i = 0; i < times; i++) {
                MoveTo(25, 25, 12);
                vTaskDelay(pdMS_TO_TICKS(120));   // 间歇：供电所需
                MoveTo(-10, -10, 12);
                vTaskDelay(pdMS_TO_TICKS(120));
            }
            MoveTo(0, 0, 16);
            break;
        case Gesture::kHug:
            MoveTo(30, 30, 18);
            vTaskDelay(pdMS_TO_TICKS(1200));      // 张开并保持
            MoveTo(0, 0, 18);
            break;
        case Gesture::kCheer:
            for (int i = 0; i < times; i++) {
                MoveTo(15, -15, 12);
                vTaskDelay(pdMS_TO_TICKS(150));   // 间歇：实测缺此项会 BROWNOUT
                MoveTo(-15, 15, 12);
                vTaskDelay(pdMS_TO_TICKS(150));
            }
            MoveTo(0, 0, 16);
            break;
        case Gesture::kDroop:
            MoveTo(-25, -25, 20);
            vTaskDelay(pdMS_TO_TICKS(800));
            break;
        case Gesture::kLean:
            MoveTo(15, 15, 20);
            vTaskDelay(pdMS_TO_TICKS(400));
            break;
    }
}
```

- [ ] **Step 4: 板级接入并加临时验证工具**

`plush_toy_board.cc` 新增成员 `LimbController* limbs_ = nullptr;`，在 `InitializeServoBus()` 之后：

```cpp
        limbs_ = new LimbController(pca_);
        limbs_->Start();
```

- [ ] **Step 5: 编译、烧录、观察**

烧录后若 PCA9685 在线，日志应有 `Pca9685: 初始化完成`；无舵机动作（还没人调用）。若 PCA9685 离线，应看到 `LimbController: PCA9685 不可用，肢体动作已禁用` 且**设备其余功能正常**。

- [ ] **Step 6: 提交**

```bash
git add main/boards/plush-toy/
git commit -m "feat(plush-toy): LimbController 手势编排、串行队列与泄力保护"
```

---

### Task 3: MCP 工具 —— 让 LLM 能调用手势

**Files:**
- Modify: `main/boards/plush-toy/plush_toy_board.cc`

**Interfaces:**
- Consumes: `LimbController::Enqueue`、`McpServer::AddTool`
- Produces: MCP 工具 `self.limbs.wave_hand`、`self.limbs.hug`、`self.limbs.cheer`

- [ ] **Step 1: 注册工具**

只暴露 3 个。otto-robot 暴露 28 个，工具过多会显著降低 LLM 的选择准确率。

签名以 `main/mcp_server.cc:55-64` 的现有写法为准：`Property(name, kPropertyTypeInteger, min, max)` 表示必填带范围，`Property(name, type, default)` 表示可选带默认值。

```cpp
    void InitializeTools() {
        if (limbs_ == nullptr || !limbs_->available()) {
            ESP_LOGW(TAG, "肢体不可用，跳过手势工具注册");
            return;
        }
        auto& mcp = McpServer::GetInstance();
        auto* limbs = limbs_;

        mcp.AddTool("self.limbs.wave_hand",
            "Wave the plush toy's hand to greet someone. Use when the user says hello, "
            "goodbye, or asks the toy to wave.",
            PropertyList({
                Property("side", kPropertyTypeString, std::string("both")),
                Property("times", kPropertyTypeInteger, 2, 1, 5)
            }),
            [limbs](const PropertyList& p) -> ReturnValue {
                auto side = p["side"].value<std::string>();
                Gesture g = (side == "left")  ? Gesture::kWaveLeft
                          : (side == "right") ? Gesture::kWaveRight
                                              : Gesture::kWaveBoth;
                return limbs->Enqueue(g, p["times"].value<int>());
            });

        mcp.AddTool("self.limbs.hug",
            "Open both arms for a hug. Use when the user asks for a hug or expresses "
            "affection toward the toy.",
            PropertyList(),
            [limbs](const PropertyList&) -> ReturnValue {
                return limbs->Enqueue(Gesture::kHug, 1);
            });

        mcp.AddTool("self.limbs.cheer",
            "Wiggle both arms happily. Use to express excitement or celebration.",
            PropertyList({ Property("times", kPropertyTypeInteger, 3, 1, 5) }),
            [limbs](const PropertyList& p) -> ReturnValue {
                return limbs->Enqueue(Gesture::kCheer, p["times"].value<int>());
            });
    }
```

在构造函数末尾调用 `InitializeTools();`，并加 `#include "mcp_server.h"`。

**工具描述必须写英文**：`main/mcp_server.cc` 中现有工具描述全是英文，且描述是直接喂给 LLM 的提示词，与服务端 LLM 的主要训练语言一致效果更好。

- [ ] **Step 2: 编译烧录，确认工具注册**

Expected 串口出现三行：

```
MCP: Add tool: self.limbs.wave_hand
MCP: Add tool: self.limbs.hug
MCP: Add tool: self.limbs.cheer
```

- [ ] **Step 3: 实机验证**

设备联网后，对它说「跟我挥挥手」。预期：服务端 LLM 调用 `self.limbs.wave_hand`，舵机执行挥手。

**若 LLM 不调用工具**：先在服务端确认工具已被发现。`core/providers/tools/device_mcp/` 负责拉取设备工具列表，检查服务端日志是否列出这三个工具名。若列出但不调用，是 prompt 问题，见 Task 6。

- [ ] **Step 4: 提交**

```bash
git add main/boards/plush-toy/
git commit -m "feat(plush-toy): 暴露 3 个手势 MCP 工具"
```

---

### Task 4: PlushBehavior —— 状态反射

**Files:**
- Create: `main/boards/plush-toy/plush_behavior.h`
- Create: `main/boards/plush-toy/plush_behavior.cc`
- Modify: `main/boards/plush-toy/plush_toy_board.cc`

**Interfaces:**
- Consumes: `LimbController`、`Application::GetDeviceState()`（`main/application.h:68`，public）
- Produces: `class PlushBehavior`，方法 `void Start()`

- [ ] **Step 1: 写 `plush_behavior.h`**

```cpp
#pragma once

#include "limb_controller.h"
#include "device_state.h"

class PlushBehavior {
public:
    explicit PlushBehavior(LimbController* limbs);
    void Start();

private:
    static void TaskEntry(void* arg);
    void Run();
    void OnStateChanged(DeviceState from, DeviceState to);

    LimbController* limbs_;
    DeviceState last_state_ = kDeviceStateUnknown;
};
```

- [ ] **Step 2: 实现轮询与状态映射**

**挂钩点选择**：`main/application.cc:247` 与 `:916` 有现成的 `led->OnStateChanged()` 回调，但把玩具行为伪装成 `Led` 语义别扭。改用 public 的 `GetDeviceState()` 轮询——本任务本就需要一个周期任务，顺手读一次状态即可，**零核心代码改动**。

```cpp
#include "plush_behavior.h"
#include "application.h"

#include <esp_log.h>

#define TAG "PlushBehavior"

PlushBehavior::PlushBehavior(LimbController* limbs) : limbs_(limbs) {}

void PlushBehavior::Start() {
    if (limbs_ == nullptr || !limbs_->available()) {
        ESP_LOGW(TAG, "肢体不可用，反射行为已禁用");
        return;
    }
    xTaskCreate(TaskEntry, "plush_behavior", 3072, this, 2, nullptr);
}

void PlushBehavior::TaskEntry(void* arg) {
    static_cast<PlushBehavior*>(arg)->Run();
}

void PlushBehavior::Run() {
    while (true) {
        auto now = Application::GetInstance().GetDeviceState();
        if (now != last_state_) {
            OnStateChanged(last_state_, now);
            last_state_ = now;
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

void PlushBehavior::OnStateChanged(DeviceState from, DeviceState to) {
    ESP_LOGI(TAG, "状态 %d -> %d", (int)from, (int)to);
    switch (to) {
        case kDeviceStateListening:
            limbs_->Enqueue(Gesture::kLean, 1);      // 微微前倾，像在专心听
            break;
        case kDeviceStateSpeaking:
            limbs_->Enqueue(Gesture::kCheer, 1);     // 说话时轻摆一次
            break;
        case kDeviceStateIdle:
            limbs_->Enqueue(Gesture::kHome, 1);      // 归中泄力
            break;
        default:
            break;
    }
}
```

**刻意不做的事**（YAGNI，spec §2.6）：不做音频波形驱动的节奏同步——需要从音频输出管线取实时幅度，耦合深、收益小；不做待机随机小动作——舵机频繁动作对塑料齿和供电都不友好，待机应当安静。

- [ ] **Step 3: 板级接入**

```cpp
        behavior_ = new PlushBehavior(limbs_);
        behavior_->Start();
```

- [ ] **Step 4: 编译烧录，实机观察**

按 BOOT 键触发对话，观察状态切换时手臂是否有对应动作，串口应打印 `PlushBehavior: 状态 x -> y`。

**重点观察是否出现 BROWNOUT**：`speaking` 触发 `kCheer` 时是双臂动作，若此时掉电，说明 `Perform` 里的间歇还不够，需要加大 `kCheer` 中的 `vTaskDelay`。

- [ ] **Step 5: 提交**

```bash
git add main/boards/plush-toy/
git commit -m "feat(plush-toy): PlushBehavior 状态反射动作"
```

---

### Task 5: emotion → 手势联动

**Files:**
- Modify: `main/boards/plush-toy/plush_behavior.h`
- Modify: `main/boards/plush-toy/plush_behavior.cc`
- Modify: `main/boards/plush-toy/plush_toy_board.cc`

**Interfaces:**
- Consumes: `Display::SetEmotion` 调用链（`main/application.cc:602-606`）
- Produces: `void PlushBehavior::OnEmotion(const char* emotion)`

- [ ] **Step 1: 理解现有通道**

`main/application.cc:602-606` 已把服务端下发的 `{"type":"llm","emotion":"happy"}` 直通到 `display->SetEmotion()`。**服务端零改动**。

当前板型的 `GetDisplay()` 返回基类 `NoDisplay`，其 `SetEmotion` 只打日志。计划一 Task 4 会换成 `EyeDisplay`。为让两个计划互不阻塞，本任务**不改 Display**，而是在板级包一层轻量子类。

- [ ] **Step 2: 在板级定义联动显示类**

`plush_toy_board.cc` 中：

```cpp
// 眼睛屏接上前的过渡实现：只把 emotion 转成手势。
// 计划一 Task 4 接入 EyeDisplay 后，把这里的逻辑移进 EyeDisplay::SetEmotion。
class LimbEmotionDisplay : public NoDisplay {
public:
    void SetBehavior(PlushBehavior* b) { behavior_ = b; }
    virtual void SetEmotion(const char* emotion) override {
        ESP_LOGI(TAG, "SetEmotion: %s", emotion ? emotion : "(null)");
        if (behavior_ != nullptr && emotion != nullptr) {
            behavior_->OnEmotion(emotion);
        }
    }
private:
    PlushBehavior* behavior_ = nullptr;
};
```

把成员 `NoDisplay display_;` 改为 `LimbEmotionDisplay display_;`，并在创建 `behavior_` 后调用 `display_.SetBehavior(behavior_);`。

- [ ] **Step 3: 实现情绪映射**

服务端 `EMOJI_MAP`（`core/utils/textUtils.py:8-30`）共 21 种。只映射有明确肢体表达的，其余不动作——**动作稀疏比动作滥用更自然**。

```cpp
void PlushBehavior::OnEmotion(const char* emotion) {
    std::string e(emotion);
    if (e == "happy" || e == "laughing" || e == "funny" || e == "silly") {
        limbs_->Enqueue(Gesture::kCheer, 2);
    } else if (e == "loving" || e == "kissy") {
        limbs_->Enqueue(Gesture::kHug, 1);
    } else if (e == "sad" || e == "crying") {
        limbs_->Enqueue(Gesture::kDroop, 1);
    } else if (e == "surprised" || e == "shocked") {
        limbs_->Enqueue(Gesture::kWaveBoth, 1);
    }
    // angry / thinking / sleepy 等刻意不动作：
    // 生气时静止不动比手舞足蹈更有张力，思考时动作会干扰"正在想"的表达
}
```

在 `plush_behavior.h` 的 public 区加 `void OnEmotion(const char* emotion);`，并 `#include <string>`。

- [ ] **Step 4: 编译烧录，实机验证**

对设备说一句能引发开心回应的话。预期串口打印 `SetEmotion: happy` 并触发 `kCheer`。

**若 `SetEmotion` 始终收到 `happy`**：这不是设备端问题，是服务端 prompt 没让 LLM 带 emoji，见 Task 6。

- [ ] **Step 5: 提交**

```bash
git add main/boards/plush-toy/
git commit -m "feat(plush-toy): emotion 通道联动手势"
```

---

### Task 6: 服务端角色 prompt

**Files:**
- Modify: `~/Workspace/xiaozhi-esp32-server` 的角色配置（不在本仓库）

**Interfaces:**
- Consumes: 无代码依赖
- Produces: 一份角色 prompt

- [ ] **Step 1: 理解为什么必须配**

`core/utils/textUtils.py:84-95` 的 `get_emotion()` 通过**扫描 LLM 回复文本中的 emoji 字符**判定情绪，默认值为 `"happy"`：

```python
emotion = "happy"          # 默认值
for char in text:
    if char in EMOJI_MAP:
        emotion = EMOJI_MAP[char]
        break
```

**LLM 回复不含 emoji 时，`emotion` 恒为 `"happy"`。** 玩具会永远做同一个动作。该失败模式极难排查——设备端代码与链路均正常。

- [ ] **Step 2: 写角色 prompt**

限定在 `EMOJI_MAP`（`textUtils.py:8-30`）支持的 21 种之内：

```
你是一只毛绒玩具里的小伙伴，性格温暖、活泼、话不多。

【表情规则】每次回复必须以一个 emoji 开头，且只能从下列中选择，
它决定了我的眼睛表情和肢体动作：
😂 😭 😠 😔 😍 😲 😱 🤔 😌 😴 😜 🙄 😶 🙂 😆 😳 😉 😎 🤤 😘 😏

【动作规则】以下情况主动调用工具，不要只用嘴说：
- 用户打招呼或告别 → self.limbs.wave_hand
- 用户要抱抱、表达喜爱 → self.limbs.hug
- 值得庆祝的事 → self.limbs.cheer
不要在每句话都调用工具，动作太频繁会显得聒噪。

【说话风格】每次回复控制在两句话以内，像小孩子说话，不要用书面语。
```

- [ ] **Step 3: 验证 emoji 不会被 TTS 朗读**

spec §7 遗留项。`get_string_no_punctuation_or_emoji()`（`textUtils.py:41`）负责剥离，需实测确认：

```bash
cd ~/Workspace/xiaozhi-esp32-server/main/xiaozhi-server
python3 -c "
import sys; sys.path.insert(0, '.')
from core.utils.textUtils import get_string_no_punctuation_or_emoji as f
print(repr(f('🙂 你好呀')))
"
```

Expected: 输出不含 emoji。若含，说明剥离发生在别处或未生效，需追查 TTS 调用链。

- [ ] **Step 4: 端到端验证**

对设备说「你好」，确认：① 服务端日志显示 LLM 回复带 emoji；② 设备串口打印对应的 `SetEmotion`；③ 舵机动作；④ 语音播报不含"笑脸"之类的字。

---

## 完成标准

- `idf.py build` 通过
- 舵机离线时设备仍能正常启动与对话（所有失败路径优雅降级）
- 对设备说「跟我挥挥手」，手臂动
- 说一句开心的话，`SetEmotion` 收到非 `happy` 的值并触发对应手势
- 全程无 `BROWNOUT`

## 待硬件条件满足后再做

- **舵机 trim 校准**：`0°` 是电气中位，装到手臂上后"自然下垂"未必对应 0°。该偏差需装配后测量，建议存 NVS `Settings` 以便在线调整而不重烧。
- **独立 5V 供电**：实测 USB 供电在双路无间歇动作下会 BROWNOUT。装进玩具后手臂带载，电流更大，独立电源与 1000µF 电容成为必需。
