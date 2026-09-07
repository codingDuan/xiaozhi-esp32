# 毛绒玩具眼睛显示 实现计划（计划一 / 共二）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建 `plush-toy` 板型，用两块 GC9A01 圆屏参数化绘制双眼表情，并以二维码承接原主屏移除后的配网提示。

**Architecture:** 眼睛渲染拆成两层——`EyeRenderer` 是不接触硬件的纯计算模块（`EyeState` → RGB565 像素矩形），可在开发机上编译测试；`EyeDisplay` 继承 `Display`，持有两块 panel，负责脏矩形调度与双模态切换。两块屏共用一条 SPI 总线，仅片选独立。

**Tech Stack:** ESP-IDF v6.1、esp_lcd + `espressif/esp_lcd_gc9a01`、C++17、主机端 g++ 测试

**Spec:** `docs/superpowers/specs/2026-09-05-plush-toy-design.md`

**范围：** 本计划**全部任务不需要实物元件**，可在元件到货前完成并通过编译与主机端测试。舵机动作层、反射协调器、MCP 工具与服务端 prompt 见计划二。

## Global Constraints

- 目标芯片 `esp32s3`；PSRAM 为八线模式（`CONFIG_SPIRAM_MODE_OCT=y`），GPIO33–37 不可用
- 摄像头保留，占用 GPIO4–13、15–18，且占用 `LEDC_TIMER_0` + `LEDC_CHANNEL_0`
- 屏幕 SPI 时钟**必须 ≤ 20MHz**（面包板飞线 + 双屏并联），初值取 10MHz
- 两块屏均为 GC9A01 240×240 圆形，共用 MOSI/CLK/DC/RST，仅 CS 独立
- 实物屏模块为 7 针 `RST/CS/DC/SDA/SCL/GND/VCC`，**无 BL 引脚**（背光内部直连 VCC 常亮）；`DISPLAY_BACKLIGHT_PIN` 恒为 `GPIO_NUM_NC`。屏 VCC 接开发板 3V3，不接 5V
- `lid_tilt` 左眼取 `+t`、右眼取 `-t`，任何渲染路径都不得违反
- 不得修改 `main/` 下板型目录以外的现有文件，`main/CMakeLists.txt` 与 `main/Kconfig.projbuild` 除外（仅新增分支）
- 主机端测试代码放在 `main/boards/plush-toy/test/`；该子目录不会被固件构建 glob 收录（`main/CMakeLists.txt:869` 的 glob 不递归）

---

### Task 1: 板型骨架与编译基线

新建板型目录并让它编译通过。此时还没有眼睛，先用基类 `NoDisplay` 占位，确保引脚、Kconfig、CMake 三处接线正确。

**Files:**
- Create: `main/boards/plush-toy/config.h`
- Create: `main/boards/plush-toy/config.json`
- Create: `main/boards/plush-toy/plush_toy_board.cc`
- Modify: `main/Kconfig.projbuild:177`（在 `BOARD_TYPE_BREAD_COMPACT_WIFI_CAM` 之后新增一项）
- Modify: `main/CMakeLists.txt:110`（在 `BOARD_TYPE_BREAD_COMPACT_ESP32_LCD` 分支之后新增分支）

**Interfaces:**
- Consumes: 无
- Produces: 板型 `plush-toy`；宏 `DISPLAY_CS_LEFT_PIN`、`DISPLAY_CS_RIGHT_PIN`、`SERVO_LEFT_PIN`、`SERVO_RIGHT_PIN`、`DISPLAY_SPI_HOST`、`DISPLAY_PCLK_HZ`；类 `PlushToyBoard`

- [ ] **Step 1: 写 `config.h`**

引脚依据 spec §3.1。GC9A01 常量直接硬编码，不走 `Kconfig` 的 `DISPLAY_LCD_TYPE` choice（那个 choice 绑死在特定板型上，改它的依赖列表会污染其他板）。

```c
#ifndef _BOARD_CONFIG_H_
#define _BOARD_CONFIG_H_

#include <driver/gpio.h>

#define AUDIO_INPUT_SAMPLE_RATE  16000
#define AUDIO_OUTPUT_SAMPLE_RATE 24000

#define AUDIO_I2S_METHOD_SIMPLEX

#define AUDIO_I2S_MIC_GPIO_WS   GPIO_NUM_1
#define AUDIO_I2S_MIC_GPIO_SCK  GPIO_NUM_2
#define AUDIO_I2S_MIC_GPIO_DIN  GPIO_NUM_42
#define AUDIO_I2S_SPK_GPIO_DOUT GPIO_NUM_39
#define AUDIO_I2S_SPK_GPIO_BCLK GPIO_NUM_40
#define AUDIO_I2S_SPK_GPIO_LRCK GPIO_NUM_41

#define BUILTIN_LED_GPIO        GPIO_NUM_48
#define BOOT_BUTTON_GPIO        GPIO_NUM_0
#define TOUCH_BUTTON_GPIO       GPIO_NUM_NC
#define VOLUME_UP_BUTTON_GPIO   GPIO_NUM_NC
#define VOLUME_DOWN_BUTTON_GPIO GPIO_NUM_NC

// 摄像头：沿用 bread-compact-wifi-s3cam，引脚不变
#define CAMERA_PIN_D0 GPIO_NUM_11
#define CAMERA_PIN_D1 GPIO_NUM_9
#define CAMERA_PIN_D2 GPIO_NUM_8
#define CAMERA_PIN_D3 GPIO_NUM_10
#define CAMERA_PIN_D4 GPIO_NUM_12
#define CAMERA_PIN_D5 GPIO_NUM_18
#define CAMERA_PIN_D6 GPIO_NUM_17
#define CAMERA_PIN_D7 GPIO_NUM_16
#define CAMERA_PIN_XCLK  GPIO_NUM_15
#define CAMERA_PIN_PCLK  GPIO_NUM_13
#define CAMERA_PIN_VSYNC GPIO_NUM_6
#define CAMERA_PIN_HREF  GPIO_NUM_7
#define CAMERA_PIN_SIOC  GPIO_NUM_5
#define CAMERA_PIN_SIOD  GPIO_NUM_4
#define CAMERA_PIN_PWDN  GPIO_NUM_NC
#define CAMERA_PIN_RESET GPIO_NUM_NC
#define XCLK_FREQ_HZ 20000000

// 双眼屏：MOSI/CLK 已从 GPIO20/19 迁走，把原生 USB 还给烧录与日志
#define DISPLAY_BACKLIGHT_PIN GPIO_NUM_NC   // 模块无 BL 引脚，背光内部常亮
#define DISPLAY_MOSI_PIN      GPIO_NUM_14
#define DISPLAY_CLK_PIN       GPIO_NUM_38
#define DISPLAY_DC_PIN        GPIO_NUM_47
#define DISPLAY_RST_PIN       GPIO_NUM_21
#define DISPLAY_CS_LEFT_PIN   GPIO_NUM_45
#define DISPLAY_CS_RIGHT_PIN  GPIO_NUM_43

// 舵机（计划二使用，引脚在此统一声明避免与屏冲突）
#define SERVO_LEFT_PIN        GPIO_NUM_46
#define SERVO_RIGHT_PIN       GPIO_NUM_44

#define DISPLAY_SPI_HOST      SPI3_HOST
// 面包板飞线 + 双屏并联，先跑通再提速；上限 20MHz
#define DISPLAY_PCLK_HZ       (10 * 1000 * 1000)

// GC9A01 240x240 圆屏，硬编码不走 Kconfig choice
#define DISPLAY_WIDTH   240
#define DISPLAY_HEIGHT  240
#define DISPLAY_MIRROR_X true
#define DISPLAY_MIRROR_Y false
#define DISPLAY_SWAP_XY false
#define DISPLAY_INVERT_COLOR true
#define DISPLAY_RGB_ORDER LCD_RGB_ELEMENT_ORDER_BGR
#define DISPLAY_OFFSET_X 0
#define DISPLAY_OFFSET_Y 0
#define DISPLAY_SPI_MODE 0

#endif // _BOARD_CONFIG_H_
```

- [ ] **Step 2: 写 `config.json`**

不设 `DEFAULT_EMOJI_COLLECTION`，因此不打包 emoji 图片资源。

```json
{
    "type": "plush-toy",
    "target": "esp32s3",
    "builds": [
        {
            "name": "plush-toy",
            "build_options": {
                "camera_hmirror": false,
                "camera_vflip": false
            }
        }
    ]
}
```

- [ ] **Step 3: 在 `main/Kconfig.projbuild` 注册板型**

在第 177 行 `config BOARD_TYPE_BREAD_COMPACT_WIFI_CAM` 那一项的 `depends on IDF_TARGET_ESP32S3` 之后插入：

```
    config BOARD_TYPE_PLUSH_TOY
        bool "Plush Toy 毛绒玩具 (双圆屏 + 舵机)"
        depends on IDF_TARGET_ESP32S3
```

- [ ] **Step 4: 在 `main/CMakeLists.txt` 注册板目录**

在第 110 行 `elseif(CONFIG_BOARD_TYPE_BREAD_COMPACT_ESP32_LCD)` 分支块之后插入。**不设** `BUILTIN_TEXT_FONT` / `BUILTIN_ICON_FONT` / `DEFAULT_EMOJI_COLLECTION`——本板无文字显示。

```cmake
elseif(CONFIG_BOARD_TYPE_PLUSH_TOY)
    set(BOARD_DIR "plush-toy")
```

- [ ] **Step 5: 写 `plush_toy_board.cc`**

以 `main/boards/bread-compact-wifi-s3cam/compact_wifi_board_s3cam.cc` 为蓝本。本步只搭骨架：音频、摄像头、按键、LED 齐全，`GetDisplay()` 先返回基类 `NoDisplay`（`main/display/display.h:81`），双屏在 Task 4 接入。

**摄像头的 LEDC 占用必须显式写出**（spec §4.1）——原板型靠零初始化拿到 `LEDC_TIMER_0` / `LEDC_CHANNEL_0`，隐式默认会让计划二的舵机悄悄覆盖它。

```cpp
#include "wifi_board.h"
#include "codecs/no_audio_codec.h"
#include "display/display.h"
#include "application.h"
#include "button.h"
#include "config.h"
#include "mcp_server.h"
#include "led/single_led.h"
#include "esp32_camera.h"

#include <esp_log.h>
#include <driver/spi_common.h>

#define TAG "PlushToyBoard"

class PlushToyBoard : public WifiBoard {
private:
    Button boot_button_;
    Esp32Camera* camera_ = nullptr;
    NoDisplay display_;

    void InitializeSpi() {
        spi_bus_config_t buscfg = {};
        buscfg.mosi_io_num = DISPLAY_MOSI_PIN;
        buscfg.miso_io_num = GPIO_NUM_NC;
        buscfg.sclk_io_num = DISPLAY_CLK_PIN;
        buscfg.quadwp_io_num = GPIO_NUM_NC;
        buscfg.quadhd_io_num = GPIO_NUM_NC;
        buscfg.max_transfer_sz = DISPLAY_WIDTH * DISPLAY_HEIGHT * sizeof(uint16_t);
        ESP_ERROR_CHECK(spi_bus_initialize(DISPLAY_SPI_HOST, &buscfg, SPI_DMA_CH_AUTO));
    }

    void InitializeCamera() {
        camera_config_t config = {};
        config.pin_d0 = CAMERA_PIN_D0;
        config.pin_d1 = CAMERA_PIN_D1;
        config.pin_d2 = CAMERA_PIN_D2;
        config.pin_d3 = CAMERA_PIN_D3;
        config.pin_d4 = CAMERA_PIN_D4;
        config.pin_d5 = CAMERA_PIN_D5;
        config.pin_d6 = CAMERA_PIN_D6;
        config.pin_d7 = CAMERA_PIN_D7;
        config.pin_xclk = CAMERA_PIN_XCLK;
        config.pin_pclk = CAMERA_PIN_PCLK;
        config.pin_vsync = CAMERA_PIN_VSYNC;
        config.pin_href = CAMERA_PIN_HREF;
        config.pin_sccb_sda = CAMERA_PIN_SIOD;
        config.pin_sccb_scl = CAMERA_PIN_SIOC;
        config.sccb_i2c_port = 0;
        config.pin_pwdn = CAMERA_PIN_PWDN;
        config.pin_reset = CAMERA_PIN_RESET;
        config.xclk_freq_hz = XCLK_FREQ_HZ;
        // 显式声明 LEDC 占用：舵机（计划二）从 LEDC_CHANNEL_2 起分配，不得与此冲突
        config.ledc_timer = LEDC_TIMER_0;
        config.ledc_channel = LEDC_CHANNEL_0;
        config.pixel_format = PIXFORMAT_RGB565;
        config.frame_size = FRAMESIZE_VGA;
        config.jpeg_quality = 12;
        config.fb_count = 1;
        config.fb_location = CAMERA_FB_IN_PSRAM;
        config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
        camera_ = new Esp32Camera(config);
    }

    void InitializeButtons() {
        boot_button_.OnClick([this]() {
            auto& app = Application::GetInstance();
            if (app.GetDeviceState() == kDeviceStateStarting) {
                EnterWifiConfigMode();
                return;
            }
            app.ToggleChatState();
        });
    }

public:
    PlushToyBoard() : boot_button_(BOOT_BUTTON_GPIO) {
        InitializeSpi();
        InitializeCamera();
        InitializeButtons();
    }

    virtual Led* GetLed() override {
        static SingleLed led(BUILTIN_LED_GPIO);
        return &led;
    }

    virtual AudioCodec* GetAudioCodec() override {
        static NoAudioCodecSimplex audio_codec(
            AUDIO_INPUT_SAMPLE_RATE, AUDIO_OUTPUT_SAMPLE_RATE,
            AUDIO_I2S_SPK_GPIO_BCLK, AUDIO_I2S_SPK_GPIO_LRCK, AUDIO_I2S_SPK_GPIO_DOUT,
            AUDIO_I2S_MIC_GPIO_SCK, AUDIO_I2S_MIC_GPIO_WS, AUDIO_I2S_MIC_GPIO_DIN);
        return &audio_codec;
    }

    virtual Display* GetDisplay() override { return &display_; }

    virtual Camera* GetCamera() override { return camera_; }
};

DECLARE_BOARD(PlushToyBoard);
```

- [ ] **Step 6: 选中板型并编译**

```bash
idf.py set-target esp32s3
idf.py -D BOARD_TYPE=PLUSH_TOY reconfigure 2>/dev/null || true
```

若上一条不适用，用 menuconfig 选 `Xiaozhi Assistant → Board Type → Plush Toy 毛绒玩具`，然后：

```bash
idf.py build
```

Expected: 编译成功，末尾输出 `Project build complete`。

若报 `The selected board does not define BOARD_DIR`，说明 Step 4 的 CMake 分支没生效——检查 `CONFIG_BOARD_TYPE_PLUSH_TOY` 拼写是否与 Kconfig 中一致。

- [ ] **Step 7: 确认 `NoAudioCodecSimplex` 构造参数顺序**

不同 IDF 版本下该类签名可能不同。如果 Step 6 报参数不匹配，以 `main/boards/bread-compact-wifi-s3cam/compact_wifi_board_s3cam.cc:185-195` 的实际调用为准照抄，不要自行猜测。

- [ ] **Step 8: 提交**

```bash
git add main/boards/plush-toy/ main/Kconfig.projbuild main/CMakeLists.txt
git commit -m "feat(plush-toy): 新增板型骨架，显式声明摄像头 LEDC 占用"
```

---

### Task 2: EyeRenderer 主机端测试基建与最小渲染

先把不接触硬件的纯计算模块立起来，连同能在开发机上跑的测试。此时只渲染巩膜与瞳孔，眼睑留到 Task 3。

**Files:**
- Create: `main/boards/plush-toy/eye_renderer.h`
- Create: `main/boards/plush-toy/eye_renderer.cc`
- Create: `main/boards/plush-toy/test/Makefile`
- Create: `main/boards/plush-toy/test/test_eye_renderer.cc`

**Interfaces:**
- Consumes: 无
- Produces: `struct EyeState`、`struct DirtyRect`、`EyeRenderer::Render(uint16_t* out, const EyeState& s, int side, DirtyRect r)`、`EyeRenderer::kSize`、`EyeRenderer::FullRect()`

- [ ] **Step 1: 写 `eye_renderer.h`**

`side` 参数是镜像规则的唯一落点：`+1` 左眼、`-1` 右眼，内部对 `lid_tilt` 取符号。双眼不对称偏移**不在**此处，放在 `EyeDisplay`，以保证渲染器可被精确镜像测试。

```cpp
#pragma once

#include <stdint.h>

struct EyeState {
    float openness    = 0.94f;   // 0 全闭 ~ 1 全睁
    float pupil_x     = 0.0f;    // -1 ~ 1
    float pupil_y     = 0.0f;    // -1 ~ 1
    float pupil_scale = 1.0f;    // 0.5 ~ 1.6
    float lid_tilt    = 0.0f;    // 度，左眼取值；右眼由 side 取负
    float curve       = 0.0f;    // -1 下垂 ~ +1 上拱
    uint16_t iris_color = 0x363E; // RGB565，#35C7F5
};

struct DirtyRect {
    int x = 0, y = 0, w = 0, h = 0;
};

class EyeRenderer {
public:
    static constexpr int kSize = 240;

    // out 指向 r.w * r.h 个 RGB565 像素，行连续（stride == r.w）
    // side: +1 左眼，-1 右眼
    static void Render(uint16_t* out, const EyeState& s, int side, DirtyRect r);

    static DirtyRect FullRect() { return DirtyRect{0, 0, kSize, kSize}; }
};
```

- [ ] **Step 2: 写 `test/Makefile`**

```make
CXX ?= g++
CXXFLAGS := -std=c++17 -O2 -Wall -Wextra -I..

.PHONY: test clean

test: test_eye_renderer
	./test_eye_renderer

test_eye_renderer: test_eye_renderer.cc ../eye_renderer.cc ../eye_renderer.h
	$(CXX) $(CXXFLAGS) -o $@ test_eye_renderer.cc ../eye_renderer.cc -lm

clean:
	rm -f test_eye_renderer *.ppm
```

- [ ] **Step 3: 写失败的测试**

`test/test_eye_renderer.cc`：

```cpp
#include "eye_renderer.h"

#include <cstdio>
#include <cstdlib>
#include <vector>

static int g_failures = 0;

#define CHECK(cond, msg)                                            \
    do {                                                            \
        if (!(cond)) {                                              \
            std::printf("FAIL: %s (%s:%d)\n", msg, __FILE__, __LINE__); \
            ++g_failures;                                           \
        }                                                           \
    } while (0)

static std::vector<uint16_t> RenderFull(const EyeState& s, int side) {
    std::vector<uint16_t> buf(EyeRenderer::kSize * EyeRenderer::kSize, 0xFFFF);
    EyeRenderer::Render(buf.data(), s, side, EyeRenderer::FullRect());
    return buf;
}

static uint16_t At(const std::vector<uint16_t>& b, int x, int y) {
    return b[y * EyeRenderer::kSize + x];
}

// 圆屏之外必须是黑的，否则会在屏边缘出现半个亮块
static void TestOutsideCircleIsBlack() {
    EyeState s;
    auto b = RenderFull(s, +1);
    CHECK(At(b, 2, 2) == 0x0000, "圆屏外左上角应为黑");
    CHECK(At(b, 237, 237) == 0x0000, "圆屏外右下角应为黑");
}

// 睁眼时中心是瞳孔（暗），其上方是巩膜（亮）
static void TestOpenEyeHasBrightScleraAndDarkPupil() {
    EyeState s;
    s.openness = 1.0f;
    auto b = RenderFull(s, +1);
    CHECK(At(b, 120, 120) < 0x2104, "全睁时中心应为瞳孔，接近黑");
    CHECK(At(b, 120, 52) > 0x8410, "全睁时中心上方应为巩膜，接近白");
}

int main() {
    TestOutsideCircleIsBlack();
    TestOpenEyeHasBrightScleraAndDarkPupil();
    if (g_failures == 0) {
        std::printf("所有测试通过\n");
        return 0;
    }
    std::printf("%d 项测试失败\n", g_failures);
    return 1;
}
```

- [ ] **Step 4: 运行测试确认失败**

```bash
cd main/boards/plush-toy/test && make test
```

Expected: 编译失败，报 `undefined reference to EyeRenderer::Render`（`eye_renderer.cc` 尚不存在，需先建空文件才能到链接错误；若报找不到源文件，先 `touch ../eye_renderer.cc`）。

- [ ] **Step 5: 写最小实现**

`eye_renderer.cc`。几何参数取自已归档的原型（spec §8）：屏心 `(120,120)`，巩膜半径 100，虹膜半径 44，瞳孔半径 21×`pupil_scale`，瞳孔偏移 `pupil_x*36` / `pupil_y*30`。

```cpp
#include "eye_renderer.h"

#include <math.h>

namespace {

constexpr int kC = EyeRenderer::kSize / 2;   // 120，屏心
constexpr float kScleraR = 100.0f;
constexpr float kIrisR   = 44.0f;
constexpr float kPupilR  = 21.0f;

inline uint16_t Rgb565(int r, int g, int b) {
    return (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}

// 把 RGB565 按比例调暗/调亮，用于虹膜径向渐变
inline uint16_t Shade(uint16_t c, float f) {
    int r = ((c >> 11) & 0x1F) * 255 / 31;
    int g = ((c >> 5) & 0x3F) * 255 / 63;
    int b = (c & 0x1F) * 255 / 31;
    auto cl = [](float v) { return (int)(v < 0 ? 0 : (v > 255 ? 255 : v)); };
    return Rgb565(cl(r * f), cl(g * f), cl(b * f));
}

}  // namespace

void EyeRenderer::Render(uint16_t* out, const EyeState& s, int side, DirtyRect r) {
    const float px = kC + s.pupil_x * 36.0f;
    const float py = kC + s.pupil_y * 30.0f;
    const float pupil_r = kPupilR * s.pupil_scale;
    const float iris_r = kIrisR * (0.9f + 0.1f * s.pupil_scale);
    (void)side;   // 眼睑在 Task 3 接入后才用到

    for (int yy = 0; yy < r.h; ++yy) {
        const int y = r.y + yy;
        for (int xx = 0; xx < r.w; ++xx) {
            const int x = r.x + xx;
            uint16_t c = 0x0000;

            const float dxs = (float)(x - kC), dys = (float)(y - kC);
            const float ds = sqrtf(dxs * dxs + dys * dys);

            if (ds <= kC && ds <= kScleraR) {
                // 巩膜：中心偏上略亮的径向渐变
                const float t = ds / kScleraR;
                const int v = (int)(255.0f - 44.0f * t);
                c = Rgb565(v, v, (int)(v * 0.98f));

                const float dxp = (float)x - px, dyp = (float)y - py;
                const float dp = sqrtf(dxp * dxp + dyp * dyp);

                if (dp <= iris_r) {
                    const float k = dp / iris_r;
                    c = Shade(s.iris_color, 1.35f - 0.93f * k);
                }
                if (dp <= pupil_r) {
                    c = Rgb565(7, 9, 12);
                }
                // 主高光
                const float hx = (float)x - (px - 15.0f), hy = (float)y - (py - 17.0f);
                if (hx * hx + hy * hy <= 9.5f * 9.5f) {
                    c = 0xFFFF;
                }
            }

            out[yy * r.w + xx] = c;
        }
    }
}
```

- [ ] **Step 6: 运行测试确认通过**

```bash
cd main/boards/plush-toy/test && make test
```

Expected: `所有测试通过`

- [ ] **Step 7: 提交**

```bash
git add main/boards/plush-toy/eye_renderer.h main/boards/plush-toy/eye_renderer.cc main/boards/plush-toy/test/
git commit -m "feat(plush-toy): EyeRenderer 巩膜/虹膜/瞳孔渲染与主机端测试"
```

---

### Task 3: 眼睑、curve 与左右镜像

补上眼睑裁切。这是表情的主要载体，也是 spec §2.2.1 三条约束的落点。

**Files:**
- Modify: `main/boards/plush-toy/eye_renderer.cc`
- Modify: `main/boards/plush-toy/test/test_eye_renderer.cc`

**Interfaces:**
- Consumes: Task 2 的 `EyeRenderer::Render`、`EyeState`
- Produces: 同一签名，行为扩展为受 `openness` / `lid_tilt` / `curve` / `side` 控制

- [ ] **Step 1: 写失败的测试**

追加到 `test_eye_renderer.cc`，并在 `main()` 中调用。

```cpp
static int CountLit(const std::vector<uint16_t>& b) {
    int n = 0;
    for (uint16_t v : b) if (v != 0x0000) ++n;
    return n;
}

static int CountLitInBand(const std::vector<uint16_t>& b, int y0, int y1) {
    int n = 0;
    for (int y = y0; y < y1; ++y)
        for (int x = 0; x < EyeRenderer::kSize; ++x)
            if (At(b, x, y) != 0x0000) ++n;
    return n;
}

// 全闭时整块屏必须是黑的
static void TestClosedEyeIsBlank() {
    EyeState s;
    s.openness = 0.0f;
    auto b = RenderFull(s, +1);
    CHECK(CountLit(b) == 0, "openness=0 时应全黑");
}

// 镜像规则：左眼 +t 与右眼 -t 必须逐像素相等
static void TestLidTiltMirrorsBetweenEyes() {
    EyeState l; l.lid_tilt = 20.0f; l.openness = 0.7f;
    EyeState r = l; r.lid_tilt = -20.0f;
    auto bl = RenderFull(l, +1);
    auto br = RenderFull(r, -1);
    bool same = true;
    for (size_t i = 0; i < bl.size(); ++i) if (bl[i] != br[i]) { same = false; break; }
    CHECK(same, "左眼 +t 与右眼 -t 应渲染出完全相同的像素");
}

// curve > 0 表示下眼睑上拱（笑眼），下半部分点亮像素应减少
static void TestPositiveCurveRaisesLowerLid() {
    EyeState flat; flat.openness = 0.62f; flat.curve = 0.0f;
    EyeState smile = flat; smile.curve = 0.85f;
    auto bf = RenderFull(flat, +1);
    auto bs = RenderFull(smile, +1);
    const int lo = CountLitInBand(bf, 130, 200);
    const int hi = CountLitInBand(bs, 130, 200);
    CHECK(hi < lo, "curve>0 应让下半部分点亮像素减少");
}
```

在 `main()` 中加入：

```cpp
    TestClosedEyeIsBlank();
    TestLidTiltMirrorsBetweenEyes();
    TestPositiveCurveRaisesLowerLid();
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd main/boards/plush-toy/test && make test
```

Expected: 三项新测试全部 FAIL——`openness=0 时应全黑`、`curve>0 应让下半部分点亮像素减少` 必失败（当前实现忽略这两个参数）。

- [ ] **Step 3: 实现眼睑裁切**

在 `eye_renderer.cc` 的匿名 namespace 中加入眼睑判定，并在像素循环里先做眼睑测试再画眼球。

上睑是一条带倾角的直线，下睑是一条二次曲线，与原型一致（半宽 106、半高 100）。

```cpp
constexpr float kLidHalfW = 106.0f;
constexpr float kLidHalfH = 100.0f;

// 判断像素是否落在睁开的眼缝内
inline bool InsideLids(float x, float y, const EyeState& s, int side) {
    const float open = s.openness < 0 ? 0 : (s.openness > 1 ? 1 : s.openness);
    if (open <= 0.0f) return false;

    const float tilt = (s.lid_tilt * (float)side) * (float)M_PI / 180.0f;
    const float top = kC - open * kLidHalfH;
    const float bot = kC + open * kLidHalfH;
    const float bow = s.curve * kLidHalfH * 0.95f;

    // 上睑：绕屏心旋转 tilt 的直线，位于 top 高度
    const float dx = x - kC;
    if (y < top + tanf(tilt) * dx) return false;

    // 下睑：二次贝塞尔的近似——用抛物线，顶点比 bot 高 bow
    const float u = dx / (kLidHalfW * 1.5f);          // -1 ~ 1
    const float lower = bot - bow * (1.0f - u * u);
    if (y > lower) return false;

    return true;
}
```

在 `Render` 的内层循环里，把原来的 `if (ds <= kC && ds <= kScleraR)` 改成：

```cpp
            if (ds <= kC && ds <= kScleraR &&
                InsideLids((float)x, (float)y, s, side)) {
```

同时删掉 `(void)side;` 那一行。

- [ ] **Step 4: 运行测试确认通过**

```bash
cd main/boards/plush-toy/test && make test
```

Expected: `所有测试通过`

若 `TestLidTiltMirrorsBetweenEyes` 仍失败，检查 `InsideLids` 里 `tilt` 是否确实乘了 `side`，以及 `Render` 是否把 `side` 透传了进去。

- [ ] **Step 5: 提交**

```bash
git add main/boards/plush-toy/eye_renderer.cc main/boards/plush-toy/test/test_eye_renderer.cc
git commit -m "feat(plush-toy): 眼睑裁切、curve 曲率与左右眼镜像"
```

---

### Task 4: EyeDisplay 接管双屏

把渲染器接到两块真实 panel 上。此时全屏重绘，脏矩形在 Task 5 加。

**Files:**
- Create: `main/boards/plush-toy/eye_display.h`
- Create: `main/boards/plush-toy/eye_display.cc`
- Modify: `main/boards/plush-toy/plush_toy_board.cc`

**Interfaces:**
- Consumes: `EyeRenderer::Render`、`EyeState`、`DirtyRect`
- Produces: `class EyeDisplay : public Display`，构造签名 `EyeDisplay(esp_lcd_panel_handle_t left, esp_lcd_panel_handle_t right)`；方法 `void SetEyeState(const EyeState& s)`、`const EyeState& GetEyeState() const`

- [ ] **Step 1: 写 `eye_display.h`**

只重写 `SetEmotion`。`SetChatMessage` / `SetStatus` / `ShowNotification` **刻意不重写**，让它们落到 `main/display/display.cc:25-37` 的基类实现打到串口——这是移除主屏后的调试通道（spec §2.3）。

```cpp
#pragma once

#include "display.h"
#include "eye_renderer.h"

#include <esp_lcd_panel_ops.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <vector>

class EyeDisplay : public Display {
public:
    EyeDisplay(esp_lcd_panel_handle_t left, esp_lcd_panel_handle_t right);
    virtual ~EyeDisplay();

    virtual void SetEmotion(const char* emotion) override;

    void SetEyeState(const EyeState& s);
    const EyeState& GetEyeState() const { return state_; }

private:
    void Flush(DirtyRect r);

    esp_lcd_panel_handle_t left_ = nullptr;
    esp_lcd_panel_handle_t right_ = nullptr;
    EyeState state_;
    uint16_t* buf_ = nullptr;      // kSize*kSize，两眼共用，在 PSRAM
    SemaphoreHandle_t mutex_ = nullptr;
};
```

- [ ] **Step 2: 写 `eye_display.cc`**

双眼不对称在此处施加（`pupil_x` ±0.045），使 `EyeRenderer` 保持可镜像测试。

```cpp
#include "eye_display.h"

#include <esp_heap_caps.h>
#include <esp_log.h>
#include <cstring>

#define TAG "EyeDisplay"

EyeDisplay::EyeDisplay(esp_lcd_panel_handle_t left, esp_lcd_panel_handle_t right)
    : left_(left), right_(right) {
    mutex_ = xSemaphoreCreateMutex();
    const size_t n = (size_t)EyeRenderer::kSize * EyeRenderer::kSize;
    buf_ = (uint16_t*)heap_caps_malloc(n * sizeof(uint16_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (buf_ == nullptr) {
        ESP_LOGE(TAG, "PSRAM 分配 %u 字节失败", (unsigned)(n * sizeof(uint16_t)));
        return;
    }
    Flush(EyeRenderer::FullRect());
}

EyeDisplay::~EyeDisplay() {
    if (buf_ != nullptr) heap_caps_free(buf_);
    if (mutex_ != nullptr) vSemaphoreDelete(mutex_);
}

void EyeDisplay::SetEyeState(const EyeState& s) {
    state_ = s;
    Flush(EyeRenderer::FullRect());
}

void EyeDisplay::Flush(DirtyRect r) {
    if (buf_ == nullptr || r.w <= 0 || r.h <= 0) return;
    xSemaphoreTake(mutex_, portMAX_DELAY);

    // 左眼 side=+1，右眼 side=-1；不对称偏移在此施加，渲染器保持纯净
    EyeState l = state_; l.pupil_x += 0.045f;
    EyeRenderer::Render(buf_, l, +1, r);
    esp_lcd_panel_draw_bitmap(left_, r.x, r.y, r.x + r.w, r.y + r.h, buf_);

    EyeState rr = state_; rr.pupil_x -= 0.045f;
    EyeRenderer::Render(buf_, rr, -1, r);
    esp_lcd_panel_draw_bitmap(right_, r.x, r.y, r.x + r.w, r.y + r.h, buf_);

    xSemaphoreGive(mutex_);
}

void EyeDisplay::SetEmotion(const char* emotion) {
    // 完整情绪映射在计划二实现；此处先记录，保证链路可观测
    ESP_LOGI(TAG, "SetEmotion: %s", emotion ? emotion : "(null)");
}
```

> **注意**：`esp_lcd_panel_draw_bitmap` 是异步的，两次调用共用 `buf_` 会导致右眼覆盖左眼尚未传完的数据。**本步先接受这个缺陷**（表现为左眼偶发花屏），Task 5 用 `esp_lcd_panel_io_register_event_callbacks` 的传输完成回调修正。此处记录以免被误当作渲染 bug。

- [ ] **Step 3: 在板型里创建两块 panel**

修改 `plush_toy_board.cc`：删除 `NoDisplay display_;`，改为 `EyeDisplay* display_ = nullptr;`，加入头文件 `#include "eye_display.h"` 与 `#include <esp_lcd_gc9a01.h>`，并新增：

```cpp
    esp_lcd_panel_handle_t NewPanel(gpio_num_t cs) {
        esp_lcd_panel_io_handle_t io = nullptr;
        esp_lcd_panel_io_spi_config_t io_config = {};
        io_config.cs_gpio_num = cs;
        io_config.dc_gpio_num = DISPLAY_DC_PIN;
        io_config.spi_mode = DISPLAY_SPI_MODE;
        io_config.pclk_hz = DISPLAY_PCLK_HZ;
        io_config.trans_queue_depth = 10;
        io_config.lcd_cmd_bits = 8;
        io_config.lcd_param_bits = 8;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(DISPLAY_SPI_HOST, &io_config, &io));

        esp_lcd_panel_handle_t panel = nullptr;
        esp_lcd_panel_dev_config_t panel_config = {};
        // 两块屏共用一根 RST，只有第一块负责复位，第二块传 NC 避免重复拉低
        panel_config.reset_gpio_num = (cs == DISPLAY_CS_LEFT_PIN) ? DISPLAY_RST_PIN : GPIO_NUM_NC;
        panel_config.rgb_ele_order = DISPLAY_RGB_ORDER;
        panel_config.bits_per_pixel = 16;
        ESP_ERROR_CHECK(esp_lcd_new_panel_gc9a01(io, &panel_config, &panel));

        esp_lcd_panel_reset(panel);
        esp_lcd_panel_init(panel);
        esp_lcd_panel_invert_color(panel, DISPLAY_INVERT_COLOR);
        esp_lcd_panel_swap_xy(panel, DISPLAY_SWAP_XY);
        esp_lcd_panel_mirror(panel, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y);
        esp_lcd_panel_disp_on_off(panel, true);
        return panel;
    }

    void InitializeDisplay() {
        auto left = NewPanel(DISPLAY_CS_LEFT_PIN);
        auto right = NewPanel(DISPLAY_CS_RIGHT_PIN);
        display_ = new EyeDisplay(left, right);
    }
```

在构造函数中 `InitializeCamera();` 之前插入 `InitializeDisplay();`，并把 `GetDisplay()` 改为 `return display_;`。

- [ ] **Step 4: 编译**

```bash
idf.py build
```

Expected: `Project build complete`。

若报找不到 `esp_lcd_gc9a01.h`，确认 `main/idf_component.yml:5` 的 `espressif/esp_lcd_gc9a01` 仍在依赖中，并执行 `idf.py reconfigure`。

- [ ] **Step 5: 提交**

```bash
git add main/boards/plush-toy/eye_display.h main/boards/plush-toy/eye_display.cc main/boards/plush-toy/plush_toy_board.cc
git commit -m "feat(plush-toy): EyeDisplay 驱动双 GC9A01，共用 SPI 总线"
```

---

### Task 5: 脏矩形刷新与传输同步

spec §4.3 把脏矩形定为必需项：20MHz 下双眼全屏重绘只有 11fps。同时修掉 Task 4 遗留的缓冲区竞争。

**Files:**
- Modify: `main/boards/plush-toy/eye_renderer.h`
- Modify: `main/boards/plush-toy/eye_renderer.cc`
- Modify: `main/boards/plush-toy/eye_display.h`
- Modify: `main/boards/plush-toy/eye_display.cc`
- Modify: `main/boards/plush-toy/test/test_eye_renderer.cc`

**Interfaces:**
- Consumes: Task 3 的渲染器
- Produces: `EyeRenderer::ComputeDirty(const EyeState& a, const EyeState& b)` → `DirtyRect`

- [ ] **Step 1: 写失败的测试**

追加到 `test_eye_renderer.cc` 并在 `main()` 调用：

```cpp
// 相同状态之间无需重绘
static void TestNoChangeYieldsEmptyRect() {
    EyeState a;
    DirtyRect r = EyeRenderer::ComputeDirty(a, a);
    CHECK(r.w == 0 && r.h == 0, "状态未变时脏矩形应为空");
}

// 只有瞳孔平移时，脏矩形必须显著小于全屏
static void TestPupilMoveYieldsSmallRect() {
    EyeState a;
    EyeState b = a; b.pupil_x = 0.3f;
    DirtyRect r = EyeRenderer::ComputeDirty(a, b);
    CHECK(r.w > 0 && r.h > 0, "瞳孔移动应产生非空脏矩形");
    CHECK(r.w * r.h < EyeRenderer::kSize * EyeRenderer::kSize / 2,
          "瞳孔移动的脏矩形应小于半屏");
}

// openness 变化会牵动眼睑，脏矩形必须覆盖整个眼睛纵向范围
static void TestOpennessChangeYieldsTallRect() {
    EyeState a; a.openness = 1.0f;
    EyeState b = a; b.openness = 0.2f;
    DirtyRect r = EyeRenderer::ComputeDirty(a, b);
    CHECK(r.h >= 200, "眼睑变化应产生纵向接近全屏的脏矩形");
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd main/boards/plush-toy/test && make test
```

Expected: 编译失败，`ComputeDirty` 未声明。

- [ ] **Step 3: 声明并实现 `ComputeDirty`**

在 `eye_renderer.h` 的 public 区加入：

```cpp
    // 计算两状态之间需要重绘的最小矩形；无变化时返回 {0,0,0,0}
    static DirtyRect ComputeDirty(const EyeState& a, const EyeState& b);
```

在 `eye_renderer.cc` 末尾实现。策略：眼睑类参数变化牵动全眼纵向，退化为整个眼球外接矩形；仅瞳孔变化时取两个瞳孔圆的并集加余量。

```cpp
DirtyRect EyeRenderer::ComputeDirty(const EyeState& a, const EyeState& b) {
    auto ne = [](float x, float y) { return fabsf(x - y) > 1e-4f; };

    const bool lids_changed =
        ne(a.openness, b.openness) || ne(a.lid_tilt, b.lid_tilt) || ne(a.curve, b.curve);
    const bool pupil_changed =
        ne(a.pupil_x, b.pupil_x) || ne(a.pupil_y, b.pupil_y) ||
        ne(a.pupil_scale, b.pupil_scale) || a.iris_color != b.iris_color;

    if (!lids_changed && !pupil_changed) return DirtyRect{0, 0, 0, 0};

    if (lids_changed) {
        // 眼睑扫过整个眼球，退化为外接矩形
        const int x0 = kC - (int)kScleraR - 2;
        const int y0 = kC - (int)kLidHalfH - 2;
        const int w = 2 * ((int)kScleraR + 2);
        const int h = 2 * ((int)kLidHalfH + 2);
        return DirtyRect{x0 < 0 ? 0 : x0, y0 < 0 ? 0 : y0,
                         w > kSize ? kSize : w, h > kSize ? kSize : h};
    }

    // 仅瞳孔/虹膜变化：取两帧虹膜圆的并集
    const float r = kIrisR * 1.1f + 4.0f;
    const float ax = kC + a.pupil_x * 36.0f, ay = kC + a.pupil_y * 30.0f;
    const float bx = kC + b.pupil_x * 36.0f, by = kC + b.pupil_y * 30.0f;
    int x0 = (int)floorf(fminf(ax, bx) - r);
    int y0 = (int)floorf(fminf(ay, by) - r);
    int x1 = (int)ceilf(fmaxf(ax, bx) + r);
    int y1 = (int)ceilf(fmaxf(ay, by) + r);
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > kSize) x1 = kSize;
    if (y1 > kSize) y1 = kSize;
    return DirtyRect{x0, y0, x1 - x0, y1 - y0};
}
```

`kC` / `kScleraR` / `kIrisR` / `kLidHalfH` 位于匿名 namespace，`ComputeDirty` 定义在同一文件内可直接访问。

- [ ] **Step 4: 运行测试确认通过**

```bash
cd main/boards/plush-toy/test && make test
```

Expected: `所有测试通过`

- [ ] **Step 5: 修掉双眼共用缓冲区的竞争**

`esp_lcd_panel_draw_bitmap` 异步返回，两眼共用 `buf_` 会让右眼的渲染覆盖左眼未传完的数据。改为**两块缓冲区**——单块 240×240 仅 115KB，PSRAM 有 8MB，为正确性花这份内存是划算的。

`eye_display.h` 中把 `uint16_t* buf_` 换成：

```cpp
    uint16_t* buf_left_ = nullptr;
    uint16_t* buf_right_ = nullptr;
```

`eye_display.cc` 构造函数中分配两块，析构中各自释放，`Flush` 改为分别写入对应缓冲区。同时把 `SetEyeState` 改为按需刷新：

```cpp
void EyeDisplay::SetEyeState(const EyeState& s) {
    DirtyRect r = EyeRenderer::ComputeDirty(state_, s);
    state_ = s;
    Flush(r);   // r 为空时 Flush 直接返回
}
```

- [ ] **Step 6: 编译**

```bash
idf.py build
```

Expected: `Project build complete`

- [ ] **Step 7: 提交**

```bash
git add main/boards/plush-toy/
git commit -m "feat(plush-toy): 脏矩形刷新，双眼独立缓冲区消除传输竞争"
```

---

### Task 6: 二维码生成

配网提示的载体。纯计算模块，可在开发机上测。

**Files:**
- Create: `main/boards/plush-toy/overlay_qr.h`
- Create: `main/boards/plush-toy/overlay_qr.cc`
- Create: `main/boards/plush-toy/test/test_overlay_qr.cc`
- Modify: `main/boards/plush-toy/test/Makefile`
- Modify: `main/idf_component.yml`

**Interfaces:**
- Consumes: 无
- Produces: `bool OverlayQr::Encode(const char* text, std::vector<uint8_t>& modules, int& side)`——`modules` 为 `side*side` 的 0/1 数组，行优先

- [ ] **Step 1: 确认二维码组件可用性**

spec §7 第 1 项。先查乐鑫组件库：

```bash
compote component list --name qrcode 2>/dev/null || \
  curl -s "https://components.espressif.com/api/components/espressif/qrcode" | head -c 400
```

若可用，在 `main/idf_component.yml` 的 `dependencies:` 下加入 `espressif/qrcode: "^0.1.0"`（版本以查询结果为准），`OverlayQr::Encode` 包一层该组件的 `esp_qrcode_generate`。

若不可用，改为自实现最小编码器：仅支持 Version 3、纠错等级 L、字节模式，足够容纳 `WIFI:S:Xiaozhi-XXXX;T:nopass;;`（约 30 字节，Version 3-L 上限 53 字节）。

**无论走哪条路，`OverlayQr::Encode` 的签名保持不变**，Task 7 只依赖签名。

- [ ] **Step 2: 写 `overlay_qr.h`**

```cpp
#pragma once

#include <stdint.h>
#include <vector>

class OverlayQr {
public:
    // 把 text 编码为二维码模块阵列
    // modules: 输出 side*side 个 0/1，行优先；side: 输出边长（模块数）
    // 返回 false 表示文本过长或编码失败
    static bool Encode(const char* text, std::vector<uint8_t>& modules, int& side);
};
```

- [ ] **Step 3: 写失败的测试**

`test/test_overlay_qr.cc`：

```cpp
#include "overlay_qr.h"

#include <cstdio>
#include <cstring>
#include <vector>

static int g_failures = 0;

#define CHECK(cond, msg)                                            \
    do {                                                            \
        if (!(cond)) {                                              \
            std::printf("FAIL: %s (%s:%d)\n", msg, __FILE__, __LINE__); \
            ++g_failures;                                           \
        }                                                           \
    } while (0)

// 典型配网串必须能编码，且边长能塞进圆屏内接正方形
static void TestEncodesWifiString() {
    std::vector<uint8_t> m;
    int side = 0;
    bool ok = OverlayQr::Encode("WIFI:S:Xiaozhi-A1B2;T:nopass;;", m, side);
    CHECK(ok, "标准配网串应编码成功");
    CHECK(side >= 21 && side <= 33, "版本应落在 1~4，边长 21~33 模块");
    CHECK((int)m.size() == side * side, "模块数组长度应为 side*side");
}

// 定位图案：三个角上 7x7 的定位符，左上角 (0,0) 必为暗模块
static void TestFinderPatternPresent() {
    std::vector<uint8_t> m;
    int side = 0;
    OverlayQr::Encode("WIFI:S:Xiaozhi-A1B2;T:nopass;;", m, side);
    CHECK(m[0] == 1, "左上角应为暗模块");
    CHECK(m[side - 1] == 1, "右上角应为暗模块");
    CHECK(m[(side - 1) * side] == 1, "左下角应为暗模块");
}

// 圆屏内接正方形约 170px；side 模块按 5px 渲染必须放得下
static void TestFitsInRoundScreen() {
    std::vector<uint8_t> m;
    int side = 0;
    OverlayQr::Encode("WIFI:S:Xiaozhi-A1B2;T:nopass;;", m, side);
    CHECK((side + 8) * 5 <= 170, "含静默区按 5px/模块应放得进 170px");
}

int main() {
    TestEncodesWifiString();
    TestFinderPatternPresent();
    TestFitsInRoundScreen();
    if (g_failures == 0) { std::printf("所有测试通过\n"); return 0; }
    std::printf("%d 项测试失败\n", g_failures);
    return 1;
}
```

- [ ] **Step 4: 扩展 Makefile**

```make
test: test_eye_renderer test_overlay_qr
	./test_eye_renderer
	./test_overlay_qr

test_overlay_qr: test_overlay_qr.cc ../overlay_qr.cc ../overlay_qr.h
	$(CXX) $(CXXFLAGS) -o $@ test_overlay_qr.cc ../overlay_qr.cc -lm
```

并把 `clean` 的 `rm -f` 加上 `test_overlay_qr`。

- [ ] **Step 5: 运行测试确认失败**

```bash
cd main/boards/plush-toy/test && make test
```

Expected: 链接失败，`OverlayQr::Encode` 未定义。

- [ ] **Step 6: 引入 qrcodegen 并实现 `overlay_qr.cc`**

**不要手写二维码编码器。** 纠错码的 Reed-Solomon 计算、掩码评分、版本容量表极易写错，而错误表现是"手机扫不出来"——在没有硬件时根本无法察觉。

也**不要用 `espressif/qrcode` 组件**：它依赖 ESP-IDF 头文件，主机端测试链接不了，会直接毁掉本模块可离线测试这个核心优势。Step 1 的查询结果仅用于了解现状，不影响此处决策。

正确做法是 vendored 一份不依赖任何平台的单文件实现——Nayuki 的 **qrcodegen**（MIT 许可，纯 C99，无外部依赖，两个文件）：

```bash
cd main/boards/plush-toy
curl -sL -o qrcodegen.c https://raw.githubusercontent.com/nayuki/QR-Code-generator/master/c/qrcodegen.c
curl -sL -o qrcodegen.h https://raw.githubusercontent.com/nayuki/QR-Code-generator/master/c/qrcodegen.h
head -20 qrcodegen.h   # 确认顶部 MIT 许可声明存在
```

该文件会被 `main/CMakeLists.txt:870` 的 `*.c` glob 自动纳入固件编译，无需额外注册。

`overlay_qr.cc`：

```cpp
#include "overlay_qr.h"

extern "C" {
#include "qrcodegen.h"
}

#include <cstring>

bool OverlayQr::Encode(const char* text, std::vector<uint8_t>& modules, int& side) {
    if (text == nullptr || text[0] == '\0') return false;

    uint8_t qr[qrcodegen_BUFFER_LEN_FOR_VERSION(6)];
    uint8_t tmp[qrcodegen_BUFFER_LEN_FOR_VERSION(6)];

    // 纠错等级 L：容量最大。二维码贴在屏上不会被遮挡，不需要高纠错
    const bool ok = qrcodegen_encodeText(
        text, tmp, qr, qrcodegen_Ecc_LOW,
        qrcodegen_VERSION_MIN, 6, qrcodegen_Mask_AUTO, true);
    if (!ok) return false;

    side = qrcodegen_getSize(qr);
    modules.assign((size_t)side * side, 0);
    for (int y = 0; y < side; ++y) {
        for (int x = 0; x < side; ++x) {
            modules[(size_t)y * side + x] = qrcodegen_getModule(qr, x, y) ? 1 : 0;
        }
    }
    return true;
}
```

版本上限取 6（41×41 模块）而非默认的 40：41 模块按 4px 渲染是 164px，仍能塞进圆屏内接的 169px；再高的版本模块会小到扫不出来，不如直接编码失败让上层察觉。

同时更新 Makefile 的链接目标，把 `qrcodegen.c` 一并编进主机测试：

```make
test_overlay_qr: test_overlay_qr.cc ../overlay_qr.cc ../qrcodegen.c ../overlay_qr.h
	$(CXX) $(CXXFLAGS) -x c++ -o $@ test_overlay_qr.cc ../overlay_qr.cc ../qrcodegen.c -lm
```

（`-x c++` 让 g++ 按 C++ 编译 `qrcodegen.c`；qrcodegen 是 C99 但兼容 C++ 编译。若报错，改为分两步编译：先 `gcc -c ../qrcodegen.c` 再链接 `.o`。）

- [ ] **Step 7: 运行测试确认通过**

```bash
cd main/boards/plush-toy/test && make test
```

Expected: 两个测试程序都输出 `所有测试通过`

- [ ] **Step 8: 提交**

```bash
git add main/boards/plush-toy/overlay_qr.h main/boards/plush-toy/overlay_qr.cc main/boards/plush-toy/test/
git commit -m "feat(plush-toy): 二维码编码模块与主机端测试"
```

---

### Task 7: Overlay 模式与配网二维码接入

把二维码显示到眼睛上，并挂到设备的配网状态。

**Files:**
- Modify: `main/boards/plush-toy/eye_display.h`
- Modify: `main/boards/plush-toy/eye_display.cc`
- Modify: `main/boards/plush-toy/plush_toy_board.cc`

**Interfaces:**
- Consumes: `OverlayQr::Encode`、`EyeDisplay`
- Produces: `void EyeDisplay::ShowQrCode(const char* text)`、`void EyeDisplay::ShowEyes()`

- [ ] **Step 1: 扩展 `eye_display.h`**

```cpp
    enum Mode { kModeEyes, kModeOverlay };

    // 左眼显示二维码，右眼显示静态"待配网"图标
    void ShowQrCode(const char* text);
    // 切回眼睛模式并立即重绘
    void ShowEyes();

private:
    void DrawQrToBuffer(const std::vector<uint8_t>& modules, int side, uint16_t* out);
    void DrawWaitIconToBuffer(uint16_t* out);
    Mode mode_ = kModeEyes;
```

- [ ] **Step 2: 实现 `ShowQrCode`**

先在 `eye_display.cc` 顶部加入 `#include "overlay_qr.h"`。

二维码必须是**深色模块画在浅色底上**才能被手机识别——不能直接在黑底上画亮模块。所以先把整块屏填白，再画黑模块。

```cpp
void EyeDisplay::ShowQrCode(const char* text) {
    std::vector<uint8_t> modules;
    int side = 0;
    if (!OverlayQr::Encode(text, modules, side)) {
        ESP_LOGE(TAG, "二维码编码失败: %s", text ? text : "(null)");
        return;
    }
    mode_ = kModeOverlay;

    xSemaphoreTake(mutex_, portMAX_DELAY);
    DrawQrToBuffer(modules, side, buf_left_);
    esp_lcd_panel_draw_bitmap(left_, 0, 0, EyeRenderer::kSize, EyeRenderer::kSize, buf_left_);
    DrawWaitIconToBuffer(buf_right_);
    esp_lcd_panel_draw_bitmap(right_, 0, 0, EyeRenderer::kSize, EyeRenderer::kSize, buf_right_);
    xSemaphoreGive(mutex_);
}

void EyeDisplay::DrawQrToBuffer(const std::vector<uint8_t>& modules, int side, uint16_t* out) {
    const int kN = EyeRenderer::kSize;
    // 白底：二维码需要浅色背景 + 深色模块
    for (int i = 0; i < kN * kN; ++i) out[i] = 0xFFFF;

    // 圆屏内接正方形边长 = 240/√2 ≈ 169，留 4 模块静默区
    const int usable = 169;
    const int scale = usable / (side + 8);
    const int px = scale * side;
    const int ox = (kN - px) / 2, oy = (kN - px) / 2;

    for (int my = 0; my < side; ++my) {
        for (int mx = 0; mx < side; ++mx) {
            if (modules[my * side + mx] == 0) continue;
            for (int dy = 0; dy < scale; ++dy) {
                uint16_t* row = out + (oy + my * scale + dy) * kN + ox + mx * scale;
                for (int dx = 0; dx < scale; ++dx) row[dx] = 0x0000;
            }
        }
    }
}
```

`DrawWaitIconToBuffer` 画一个简单图形即可——黑底 + 居中的青色空心圆环（与眼睛虹膜同色 `0x363E`），直径 120px、线宽 10px，表示"等待中"。用与 `EyeRenderer` 相同的圆形距离判定：`ds` 落在 `[55, 65]` 之间的像素涂色，其余为黑。

- [ ] **Step 3: 实现 `ShowEyes`**

```cpp
void EyeDisplay::ShowEyes() {
    mode_ = kModeEyes;
    Flush(EyeRenderer::FullRect());
}
```

并在 `SetEyeState` 开头加守卫，避免 Overlay 期间被眼睛刷新覆盖：

```cpp
    if (mode_ != kModeEyes) { state_ = s; return; }
```

- [ ] **Step 4: 挂到配网状态**

`plush_toy_board.cc` 中重写 `StartNetwork`前后的时机不易把握，改为在板类里重写 `EnterWifiConfigMode`（`main/boards/common/wifi_board.cc:195` 为基类实现）之外的更简单做法：在板构造完成后由 `PlushBehavior` 轮询设备状态切换（计划二）。

**本任务范围内**，先加一个可手动触发的 MCP 工具用于验证渲染正确，避免在没有硬件时无法确认：

```cpp
    void InitializeTools() {
        auto& mcp = McpServer::GetInstance();
        mcp.AddTool("self.eyes.show_qr",
                    "在左眼显示指定文本的二维码，右眼显示等待图标；用于配网提示的渲染验证",
                    PropertyList({Property("text", kPropertyTypeString)}),
                    [this](const PropertyList& p) -> ReturnValue {
                        display_->ShowQrCode(p["text"].value<std::string>().c_str());
                        return true;
                    });
        mcp.AddTool("self.eyes.show_eyes", "切回眼睛显示模式",
                    PropertyList(), [this](const PropertyList&) -> ReturnValue {
                        display_->ShowEyes();
                        return true;
                    });
    }
```

在构造函数末尾调用 `InitializeTools();`，并 `#include "mcp_server.h"`。

> `PropertyList` / `Property` / `ReturnValue` 的确切用法以 `main/mcp_server.cc:45-100` 中现有工具的写法为准，照抄其形式，不要自行推测构造参数。

- [ ] **Step 5: 编译**

```bash
idf.py build
```

Expected: `Project build complete`

- [ ] **Step 6: 提交**

```bash
git add main/boards/plush-toy/
git commit -m "feat(plush-toy): Overlay 模式与配网二维码显示"
```

---

## 完成标准

全部 7 个任务完成后：

- `idf.py build` 通过，产出 `plush-toy` 板型固件
- `cd main/boards/plush-toy/test && make test` 全部通过
- 未触碰任何现有板型；对 `main/CMakeLists.txt` 与 `main/Kconfig.projbuild` 只有新增分支

**仍需实物验证的事项**（元件到货后处理，属计划二范围）：SPI 实际可用时钟、双屏同总线稳定性、GC9A01 的 `MIRROR_X` / `INVERT_COLOR` 取值是否与手上模块匹配、二维码在真屏上能否被手机扫出。

## 已知偏差

spec §6 称"不再需要 LVGL 与 emoji 图片资源"。实际情况：**emoji 图片资源确实不再打包**（`config.json` 未设 `DEFAULT_EMOJI_COLLECTION`，这是 flash 占用的大头）；但 LVGL 相关的 `.cc` 文件在 `main/CMakeLists.txt:20-31` 中是无条件加入 `SOURCES` 的，代码仍会被编译进来，只能依赖链接器裁剪未引用符号。若后续需要进一步压缩固件体积，需单独评估把这批源文件改为按板型条件加入——该改动会影响所有板型，不在本计划范围内。
