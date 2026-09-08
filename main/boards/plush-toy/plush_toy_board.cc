// 毛绒玩具板型
//
// 以 bread-compact-wifi-s3cam 为蓝本，两处关键差异：
//   1. 屏的 SPI 从 GPIO19/20 迁到 GPIO14/38，把原生 USB 还给烧录与日志
//   2. 舵机经 PCA9685 走 I2C 驱动，ESP32 不产生 PWM
//
// 本阶段显示用 NoDisplay 占位，双眼屏接好后再接入 EyeDisplay。

#include "wifi_board.h"
#include "codecs/no_audio_codec.h"
#include "display/display.h"
#include "application.h"
#include "button.h"
#include "config.h"
#include "led/single_led.h"
#include "esp32_camera.h"
#include "mcp_server.h"
#include "pca9685.h"
#include "limb_controller.h"
#include "plush_behavior.h"

#include <esp_log.h>
#include <driver/spi_common.h>
#include <driver/i2c_master.h>

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
    // 眼睛屏接上前的过渡实现：只把 emotion 转成手势。
    // 计划一 Task 4 接入 EyeDisplay 后，这段逻辑移进 EyeDisplay::SetEmotion。
    class LimbEmotionDisplay : public NoDisplay {
    public:
        void SetBehavior(PlushBehavior* b) { behavior_ = b; }
        virtual void SetEmotion(const char* emotion) override {
            ESP_LOGI(TAG, "SetEmotion: %s", emotion ? emotion : "(null)");
            if (behavior_ != nullptr) {
                behavior_->OnEmotion(emotion);
            }
        }
    private:
        PlushBehavior* behavior_ = nullptr;
    };

    LimbEmotionDisplay display_;
    Pca9685* pca_ = nullptr;
    LimbController* limbs_ = nullptr;
    PlushBehavior* behavior_ = nullptr;

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

        i2c_master_bus_handle_t bus = nullptr;
        esp_err_t err = i2c_new_master_bus(&cfg, &bus);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "舵机 I2C 总线创建失败: %s（肢体动作将不可用）", esp_err_to_name(err));
            return;
        }

        if (i2c_master_probe(bus, PCA9685_ADDR, 100) != ESP_OK) {
            ESP_LOGE(TAG, "PCA9685(0x%02X) 无响应。请检查："
                          "SDA(GPIO%d) 与 SCL(GPIO%d) 是否接反、VCC 是否接 3V3、是否共地",
                     PCA9685_ADDR, SERVO_I2C_SDA_PIN, SERVO_I2C_SCL_PIN);
            return;
        }

        pca_ = new Pca9685(bus, PCA9685_ADDR, SERVO_I2C_HZ);
        if (!pca_->Init(SERVO_PWM_FREQ_HZ)) {
            delete pca_;
            pca_ = nullptr;
            return;
        }
        pca_->AllOff();   // 上电即泄力，避免舵机顶着未知角度堵转
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
        if (limbs_ == nullptr || !limbs_->available()) {
            ESP_LOGW(TAG, "肢体不可用，跳过手势工具注册");
            return;
        }
        auto& mcp = McpServer::GetInstance();
        auto* limbs = limbs_;

        mcp.AddTool("self.limbs.wave_hand",
            "Wave the plush toy's hand to greet someone. Use when the user says hello, "
            "goodbye, or explicitly asks the toy to wave.",
            PropertyList({
                Property("side", kPropertyTypeString, std::string("both")),
                Property("times", kPropertyTypeInteger, 2, 1, 5)
            }),
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
            PropertyList(),
            [limbs](const PropertyList&) -> ReturnValue {
                return limbs->Enqueue(Gesture::kHug, 1);
            });

        mcp.AddTool("self.limbs.cheer",
            "Wiggle both arms happily. Use to express excitement or celebration.",
            PropertyList({
                Property("times", kPropertyTypeInteger, 3, 1, 5)
            }),
            [limbs](const PropertyList& properties) -> ReturnValue {
                return limbs->Enqueue(Gesture::kCheer, properties["times"].value<int>());
            });
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
        InitializeButtons();
        InitializeCamera();
        InitializeServoBus();   // 必须在摄像头之后：SCCB 先占掉它那个 I2C 端口
        limbs_ = new LimbController(pca_);
        limbs_->Start();

        behavior_ = new PlushBehavior(limbs_);
        behavior_->Start();
        display_.SetBehavior(behavior_);

        InitializeTools();
    }

    virtual Led* GetLed() override {
        static SingleLed led(BUILTIN_LED_GPIO);
        return &led;
    }

    virtual AudioCodec* GetAudioCodec() override {
#ifdef AUDIO_I2S_METHOD_SIMPLEX
        static NoAudioCodecSimplex audio_codec(AUDIO_INPUT_SAMPLE_RATE, AUDIO_OUTPUT_SAMPLE_RATE,
            AUDIO_I2S_SPK_GPIO_BCLK, AUDIO_I2S_SPK_GPIO_LRCK, AUDIO_I2S_SPK_GPIO_DOUT,
            AUDIO_I2S_MIC_GPIO_SCK, AUDIO_I2S_MIC_GPIO_WS, AUDIO_I2S_MIC_GPIO_DIN);
#else
        static NoAudioCodecDuplex audio_codec(AUDIO_INPUT_SAMPLE_RATE, AUDIO_OUTPUT_SAMPLE_RATE,
            AUDIO_I2S_GPIO_BCLK, AUDIO_I2S_GPIO_WS, AUDIO_I2S_GPIO_DOUT, AUDIO_I2S_GPIO_DIN);
#endif
        return &audio_codec;
    }

    virtual Display* GetDisplay() override {
        return &display_;
    }

    virtual Camera* GetCamera() override {
        return camera_;
    }
};

DECLARE_BOARD(PlushToyBoard);
