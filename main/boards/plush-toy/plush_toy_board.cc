// 毛绒玩具板型
//
// 以 bread-compact-wifi-s3cam 为蓝本，两处关键差异：
//   1. 屏的 SPI 从 GPIO19/20 迁到 GPIO14/38，把原生 USB 还给烧录与日志
//   2. 舵机经 PCA9685 走 I2C 驱动，ESP32 不产生 PWM
//
//   3. 双 GC9A01 圆屏做眼睛，参数化直绘（不走 LVGL）

#include "application.h"
#include "button.h"
#include "codecs/no_audio_codec.h"
#include "config.h"
#include "display/display.h"
#include "esp32_camera.h"
#include "eye_display.h"
#include "led/single_led.h"
#include "limb_controller.h"
#include "mcp_server.h"
#include "motion_controller.h"
#include "mpr121.h"
#include "mpu6050.h"
#include "pca9685.h"
#include "plush_behavior.h"
#include "plush_toy_test_server.h"
#include "settings.h"
#include "touch_controller.h"
#include "wifi_board.h"

#include <esp_lcd_gc9a01.h>
#include <esp_lcd_panel_io.h>
#include <esp_lcd_panel_vendor.h>

#include <driver/i2c_master.h>
#include <driver/spi_common.h>
#include <esp_log.h>
#include <esp_timer.h>
#include <cJSON.h>

#include <algorithm>

#define TAG "PlushToyBoard"

// 摄像头 SCCB 占用哪个 I2C 端口，由 Kconfig 决定而非 camera_config_t 字段。
// 舵机的 PCA9685 必须避开它，否则 i2c_new_master_bus 会失败、舵机全哑。
// 这条约束曾经被写反过（误以为摄像头占 port 0），故用编译期断言钉死。
#if CONFIG_SCCB_HARDWARE_I2C_PORT1
#define CAMERA_SCCB_I2C_PORT I2C_NUM_1
#else
#define CAMERA_SCCB_I2C_PORT I2C_NUM_0
#endif

static_assert(SERVO_I2C_PORT != CAMERA_SCCB_I2C_PORT,
              "舵机与摄像头 SCCB 抢同一个 I2C 端口："
              "改 config.h 的 SERVO_I2C_PORT，或改 CONFIG_SCCB_HARDWARE_I2C_PORT1");

class PlushToyBoard : public WifiBoard {
private:
    Button boot_button_;
    Esp32Camera* camera_ = nullptr;
    EyeDisplay* display_ = nullptr;
    Pca9685* pca_ = nullptr;
    LimbController* limbs_ = nullptr;
    PlushBehavior* behavior_ = nullptr;
    PlushToyTestServer* test_server_ = nullptr;
    Mpr121* mpr121_ = nullptr;
    TouchController* touch_ = nullptr;
    Mpu6050* mpu6050_ = nullptr;
    MotionController* motion_ = nullptr;
    // MPR121 要挂在同一条总线上，因此句柄必须活过 InitializeServoBus()
    i2c_master_bus_handle_t servo_bus_ = nullptr;

    static std::string ExtractWebsocketHost(const std::string& url) {
        const auto scheme_end = url.find("://");
        const auto host_begin = scheme_end == std::string::npos ? 0 : scheme_end + 3;
        const auto host_end = url.find(':', host_begin);
        return url.substr(
            host_begin, host_end == std::string::npos ? std::string::npos : host_end - host_begin);
    }

    void ScheduleTestAction(const std::string& action, const std::string& arguments_json) {
        Application::GetInstance().Schedule([this, action, arguments_json]() {
            cJSON* arguments = cJSON_Parse(arguments_json.c_str());
            if (action == "wave" && limbs_ != nullptr) {
                const auto* side = cJSON_GetObjectItem(arguments, "side");
                const auto* times = cJSON_GetObjectItem(arguments, "times");
                const int count = std::clamp(cJSON_IsNumber(times) ? times->valueint : 1, 1, 5);
                const std::string value = cJSON_IsString(side) ? side->valuestring : "both";
                limbs_->Enqueue(value == "left"    ? Gesture::kWaveLeft
                                : value == "right" ? Gesture::kWaveRight
                                                   : Gesture::kWaveBoth,
                                count);
            } else if (action == "hug" && limbs_ != nullptr) {
                limbs_->Enqueue(Gesture::kHug, 1);
            } else if (action == "cheer" && limbs_ != nullptr) {
                const auto* times = cJSON_GetObjectItem(arguments, "times");
                limbs_->Enqueue(Gesture::kCheer,
                                std::clamp(cJSON_IsNumber(times) ? times->valueint : 1, 1, 5));
            } else if (action == "eyes" && display_ != nullptr) {
                const auto* theme = cJSON_GetObjectItem(arguments, "theme");
                std::string selected;
                display_->ChangeTheme(cJSON_IsString(theme) ? theme->valuestring : "", selected);
            } else if (action == "emotion" && display_ != nullptr) {
                // 走 SetEmotion 而不是分别驱动眼睛和手势 —— 这正是服务端 emotion
                // 通道的入口，联动行为必须和线上完全同一条路径才有回归价值。
                const auto* emotion = cJSON_GetObjectItem(arguments, "emotion");
                display_->SetEmotion(cJSON_IsString(emotion) ? emotion->valuestring : "neutral");
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
            } else if (action == "diagnostics" && pca_ != nullptr) {
                ESP_LOGI(TAG, "test diagnostics: %s", pca_->Diagnostics().c_str());
            }
            if (arguments != nullptr)
                cJSON_Delete(arguments);
        });
    }

    // 控制台静默，原始计数只能从 HTTP 拿。DIAG 位关掉时省掉这段读 I2C 的开销。
    std::string TestStatusFragment() {
        std::string json =
            "\"touch_modes\":" + std::to_string(behavior_ != nullptr ? behavior_->touch_modes() : 0);
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
            // 全部 12 路的读数。标定时要靠它确认线到底接在哪个电极上 ——
            // 只报一路的话，接错脚和电极失效这两种情况长得一模一样。
            json += ",\"touch_all_filtered\":[";
            for (int ch = 0; ch < TOUCH_ELECTRODE_COUNT; ++ch) {
                if (ch != 0)
                    json += ",";
                json += std::to_string(mpr121_->ReadFiltered(ch));
            }
            json += "],\"touch_all_baseline\":[";
            for (int ch = 0; ch < TOUCH_ELECTRODE_COUNT; ++ch) {
                if (ch != 0)
                    json += ",";
                json += std::to_string(mpr121_->ReadBaseline(ch));
            }
            json += "]";
        }

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
        return json;
    }

    void InitializeTestServer() {
        if (test_server_ != nullptr)
            return;
        Settings settings("websocket", false);
        const auto host = ExtractWebsocketHost(settings.GetString("url"));
        test_server_ = new PlushToyTestServer(
            host,
            [this](const std::string& action, const std::string& arguments) {
                ScheduleTestAction(action, arguments);
            },
            [this]() { return TestStatusFragment(); });
        if (!test_server_->Start())
            ESP_LOGW(TAG, "独立 HTTP 测试通道未启动");
    }

    // 舵机链路的任何一步失败都不得让设备崩溃 —— 没有手臂的玩具仍应能正常对话。
    // 因此全部失败路径只记日志并让 pca_ 保持 nullptr，不用 ESP_ERROR_CHECK。
    void InitializeServoBus() {
        i2c_master_bus_config_t cfg = {};
        cfg.i2c_port = SERVO_I2C_PORT;
        cfg.sda_io_num = SERVO_I2C_SDA_PIN;
        cfg.scl_io_num = SERVO_I2C_SCL_PIN;
        cfg.clk_source = I2C_CLK_SRC_DEFAULT;
        cfg.glitch_ignore_cnt = 7;
        cfg.flags.enable_internal_pullup = true;

        esp_err_t err = i2c_new_master_bus(&cfg, &servo_bus_);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "舵机 I2C 总线创建失败: %s（肢体动作将不可用）", esp_err_to_name(err));
            return;
        }

        if (i2c_master_probe(servo_bus_, PCA9685_ADDR, 100) != ESP_OK) {
            ESP_LOGE(TAG,
                     "PCA9685(0x%02X) 无响应。请检查："
                     "SDA(GPIO%d) 与 SCL(GPIO%d) 是否接反、VCC 是否接 3V3、是否共地",
                     PCA9685_ADDR, SERVO_I2C_SDA_PIN, SERVO_I2C_SCL_PIN);
            return;
        }

        pca_ = new Pca9685(servo_bus_, PCA9685_ADDR, SERVO_I2C_HZ);
        if (!pca_->Init(SERVO_PWM_FREQ_HZ)) {
            delete pca_;
            pca_ = nullptr;
            return;
        }
        pca_->AllOff();  // 上电即泄力，避免舵机顶着未知角度堵转
    }

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
        // 刻意不设 config.sccb_i2c_port：该字段是死的，sccb-ng.c:123 会用
        // Kconfig 的 SCCB_I2C_PORT_DEFAULT 无条件覆盖。真正的端口由
        // CONFIG_SCCB_HARDWARE_I2C_PORT1 决定，见文件顶部的 static_assert。
        config.pin_pwdn = CAMERA_PIN_PWDN;
        config.pin_reset = CAMERA_PIN_RESET;
        config.xclk_freq_hz = XCLK_FREQ_HZ;
        // 显式声明 LEDC 占用。原板型靠零初始化拿到 TIMER_0/CHANNEL_0，
        // 隐式默认容易被后来者悄悄覆盖，这里写明避免踩坑。
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

    // 只暴露 3 个手势工具。otto-robot 暴露了 28 个，工具过多会显著降低
    // LLM 的选择准确率。描述写英文 —— 它是直接喂给 LLM 的提示词，
    // 且与 mcp_server.cc 中现有工具的风格一致。
    void InitializeTools() {
        auto& mcp = McpServer::GetInstance();

        // 眼睛颜色校正：GC9A01 模块的 RGB/BGR 排列因厂而异，配错时虹膜
        // 会从青蓝变成橙红。做成在线开关，省掉"改宏→重编→重烧"一整轮。
        if (display_ != nullptr) {
            auto* eyes = display_;
            mcp.AddTool("self.eyes.swap_colors",
                        "Swap the red and blue channels of the eyes. Use when the user says the "
                        "eye color looks wrong or inverted (for example the iris looks orange/red "
                        "instead of cyan blue). The setting is persisted.",
                        PropertyList({Property("enabled", kPropertyTypeBoolean)}),
                        [eyes](const PropertyList& properties) -> ReturnValue {
                            eyes->SetSwapRB(properties["enabled"].value<bool>());
                            return true;
                        });

            mcp.AddTool(
                "self.eyes.change_theme",
                "Change the eye theme. When the user says 换眼睛 without naming a style, call "
                "this with an empty theme to cycle to the next theme. For a named style, use "
                "one of: ocean, emerald, violet, amber, rose, ice, copper, jade, midnight, "
                "pearl, void-blue, void-purple, void-rose, dragon-amber, dragon-emerald, "
                "dragon-violet, cat-gold, cat-jade, cat-ice, cat-rose, uncanny-human, "
                "uncanny-dragon, anime-sky, anime-rose, anime-gold, anime-violet.",
                PropertyList({Property("theme", kPropertyTypeString, std::string(""))}),
                [eyes](const PropertyList& properties) -> ReturnValue {
                    std::string selected;
                    const auto requested = properties["theme"].value<std::string>();
                    if (!eyes->ChangeTheme(requested.c_str(), selected))
                        return std::string("unknown eye theme");
                    return selected;
                });
        }

        if (limbs_ == nullptr || !limbs_->available()) {
            ESP_LOGW(TAG, "肢体不可用，跳过手势工具注册");
            return;
        }
        auto* limbs = limbs_;

        mcp.AddTool("self.limbs.wave_hand",
                    "Wave the plush toy's hand to greet someone. Use when the user says hello, "
                    "goodbye, or explicitly asks the toy to wave.",
                    PropertyList({Property("side", kPropertyTypeString, std::string("both")),
                                  Property("times", kPropertyTypeInteger, 2, 1, 5)}),
                    [limbs](const PropertyList& properties) -> ReturnValue {
                        auto side = properties["side"].value<std::string>();
                        Gesture g = (side == "left")    ? Gesture::kWaveLeft
                                    : (side == "right") ? Gesture::kWaveRight
                                                        : Gesture::kWaveBoth;
                        return limbs->Enqueue(g, properties["times"].value<int>());
                    });

        mcp.AddTool("self.limbs.hug",
                    "Open both arms for a hug. Use when the user asks for a hug or expresses "
                    "affection toward the toy.",
                    PropertyList(), [limbs](const PropertyList&) -> ReturnValue {
                        return limbs->Enqueue(Gesture::kHug, 1);
                    });

        mcp.AddTool("self.limbs.cheer",
                    "Wiggle both arms happily. Use to express excitement or celebration.",
                    PropertyList({Property("times", kPropertyTypeInteger, 3, 1, 5)}),
                    [limbs](const PropertyList& properties) -> ReturnValue {
                        return limbs->Enqueue(Gesture::kCheer, properties["times"].value<int>());
                    });

        auto* pca = pca_;
        mcp.AddTool("self.limbs.get_diagnostics",
                    "Read the arm PWM driver's registers without moving the arms. Use when the "
                    "user reports that the arms or servos do not move and asks to diagnose them.",
                    PropertyList(),
                    [pca](const PropertyList&) -> ReturnValue { return pca->Diagnostics(); });
    }

    esp_lcd_panel_handle_t NewPanel(gpio_num_t cs, bool owns_reset,
                                    esp_lcd_panel_io_handle_t* out_io) {
        esp_lcd_panel_io_handle_t io = nullptr;
        esp_lcd_panel_io_spi_config_t io_cfg = {};
        io_cfg.cs_gpio_num = cs;
        io_cfg.dc_gpio_num = DISPLAY_DC_PIN;
        io_cfg.spi_mode = DISPLAY_SPI_MODE;
        io_cfg.pclk_hz = DISPLAY_PCLK_HZ;
        io_cfg.trans_queue_depth = 10;
        io_cfg.lcd_cmd_bits = 8;
        io_cfg.lcd_param_bits = 8;
        if (esp_lcd_new_panel_io_spi(DISPLAY_SPI_HOST, &io_cfg, &io) != ESP_OK) {
            ESP_LOGE(TAG, "CS=GPIO%d 创建 panel_io 失败", cs);
            return nullptr;
        }

        esp_lcd_panel_handle_t panel = nullptr;
        esp_lcd_panel_dev_config_t dev_cfg = {};
        // 两屏共用一根 RST，只让第一块负责复位，第二块传 NC 避免重复拉低
        dev_cfg.reset_gpio_num = owns_reset ? DISPLAY_RST_PIN : GPIO_NUM_NC;
        dev_cfg.rgb_ele_order = DISPLAY_RGB_ORDER;
        dev_cfg.bits_per_pixel = 16;
        if (esp_lcd_new_panel_gc9a01(io, &dev_cfg, &panel) != ESP_OK) {
            ESP_LOGE(TAG, "CS=GPIO%d 创建 gc9a01 面板失败", cs);
            return nullptr;
        }
        esp_lcd_panel_reset(panel);
        esp_lcd_panel_init(panel);
        esp_lcd_panel_invert_color(panel, DISPLAY_INVERT_COLOR);
        esp_lcd_panel_swap_xy(panel, DISPLAY_SWAP_XY);
        esp_lcd_panel_mirror(panel, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y);
        esp_lcd_panel_disp_on_off(panel, true);
        ESP_LOGI(TAG, "CS=GPIO%d 面板就绪", cs);
        *out_io = io;
        return panel;
    }

    void InitializeEyes() {
        esp_lcd_panel_io_handle_t io_left = nullptr, io_right = nullptr;
        auto left = NewPanel(DISPLAY_CS_LEFT_PIN, true, &io_left);
        auto right = NewPanel(DISPLAY_CS_RIGHT_PIN, false, &io_right);
        if (left == nullptr || right == nullptr) {
            ESP_LOGE(TAG, "眼睛不可用，设备其余功能不受影响");
            return;
        }
        display_ = new EyeDisplay(left, right, io_left, io_right);
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
        InitializeEyes();
        InitializeButtons();
        InitializeCamera();
        InitializeServoBus();  // 必须在摄像头之后：SCCB 先占掉它那个 I2C 端口
        limbs_ = new LimbController(pca_);
        limbs_->Start();

        behavior_ = new PlushBehavior(limbs_, display_);
        behavior_->Start();

        InitializeTouch();
        touch_ = new TouchController(mpr121_);
        auto* behavior = behavior_;
        touch_->SetHandler([behavior](int electrode, bool pressed) {
            behavior->OnTouch(electrode, pressed);
        });
        touch_->Start();

        InitializeMotion();
        motion_ = new MotionController(mpu6050_);
        auto* limbs = limbs_;
        motion_->SetSuppressor([limbs]() { return limbs != nullptr && limbs->busy(); });
        motion_->SetHandler([behavior](MotionEvent event, Orientation orientation) {
            behavior->OnMotion(event, orientation);
        });
        motion_->Start();
        if (display_ != nullptr) {
            display_->SetBehavior(behavior_);
            display_->StartIdleAnimation();
        }

        InitializeTools();
    }

    void SetNetworkEventCallback(NetworkEventCallback callback) override {
        WifiBoard::SetNetworkEventCallback(
            [this, callback = std::move(callback)](NetworkEvent event, const std::string& data) {
                if (event == NetworkEvent::Connected) {
                    Application::GetInstance().Schedule([this]() { InitializeTestServer(); });
                }
                callback(event, data);
            });
    }

    virtual Led* GetLed() override {
        static SingleLed led(BUILTIN_LED_GPIO);
        return &led;
    }

    virtual AudioCodec* GetAudioCodec() override {
#ifdef AUDIO_I2S_METHOD_SIMPLEX
        static NoAudioCodecSimplex audio_codec(AUDIO_INPUT_SAMPLE_RATE, AUDIO_OUTPUT_SAMPLE_RATE,
                                               AUDIO_I2S_SPK_GPIO_BCLK, AUDIO_I2S_SPK_GPIO_LRCK,
                                               AUDIO_I2S_SPK_GPIO_DOUT, AUDIO_I2S_MIC_GPIO_SCK,
                                               AUDIO_I2S_MIC_GPIO_WS, AUDIO_I2S_MIC_GPIO_DIN);
#else
        static NoAudioCodecDuplex audio_codec(AUDIO_INPUT_SAMPLE_RATE, AUDIO_OUTPUT_SAMPLE_RATE,
                                              AUDIO_I2S_GPIO_BCLK, AUDIO_I2S_GPIO_WS,
                                              AUDIO_I2S_GPIO_DOUT, AUDIO_I2S_GPIO_DIN);
#endif
        return &audio_codec;
    }

    virtual Display* GetDisplay() override {
        // 眼睛初始化失败时回落到 NoDisplay，状态文本仍走串口，设备照常可用
        if (display_ != nullptr)
            return display_;
        static NoDisplay fallback;
        return &fallback;
    }

    virtual Camera* GetCamera() override { return camera_; }
};

DECLARE_BOARD(PlushToyBoard);
