#pragma once

#include "display.h"
#include "eye_renderer.h"
#include "eye_theme.h"

#include <esp_lcd_panel_ops.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

#include <atomic>
#include <string>

class PlushBehavior;

// 双圆屏眼睛显示。
//
// 只重写 SetEmotion；SetChatMessage / SetStatus / ShowNotification 刻意不重写，
// 让它们落到 display.cc:25-37 的基类实现打到串口 —— 移除主屏后这就是调试通道。
class EyeDisplay : public Display {
public:
    EyeDisplay(esp_lcd_panel_handle_t left, esp_lcd_panel_handle_t right);
    virtual ~EyeDisplay();

    virtual void SetEmotion(const char* emotion) override;
    virtual void SetDownloadProgress(int progress, size_t speed) override;

    enum class Mode { kEyes, kOverlay };

    // Show a Wi-Fi provisioning QR code in the left eye and a wait icon in the right.
    void ShowQrCode(const char* text);

    // Return from a provisioning/upgrade overlay and redraw both eyes.
    void ShowEyes();

    // 情绪之外的直接控制（眨眼、注视方向等由行为层驱动）
    void SetEyeState(const EyeState& s);
    EyeState GetEyeState() const { return state_; }

    // 手势联动：SetEmotion 时同时通知行为层做对应动作
    void SetBehavior(PlushBehavior* b) { behavior_ = b; }

    // 启动眨眼与待机微动任务
    void StartIdleAnimation();

    // 红蓝通道互换，用于修正 GC9A01 模块的 RGB/BGR 差异。
    // 存 NVS 并立即整屏重绘，无需重编固件。
    void SetSwapRB(bool on);
    bool swap_rb() const;

    // 空名称表示顺序切换；非空名称必须是目录中的规范主题名。
    bool ChangeTheme(const char* requested_name, std::string& selected_name);

    bool available() const { return left_ != nullptr && right_ != nullptr; }

private:
    // Display 的纯虚接口。眼睛渲染自带互斥量，这里复用它。
    virtual bool Lock(int timeout_ms = 0) override;
    virtual void Unlock() override;

    static void IdleTaskEntry(void* arg);
    void IdleLoop();
    void Flush(DirtyRect r);
    void BlitInterleaved(DirtyRect r);

    esp_lcd_panel_handle_t left_ = nullptr;
    esp_lcd_panel_handle_t right_ = nullptr;

    // 两块独立缓冲。esp_lcd_panel_draw_bitmap 是异步的，共用一块会让右眼的
    // 渲染覆盖左眼尚未传完的数据（表现为左眼偶发花屏）。
    // 单块 240x240 RGB565 仅 115KB，8MB PSRAM 下为正确性花这份内存很划算。
    uint16_t* buf_left_ = nullptr;
    uint16_t* buf_right_ = nullptr;

    EyeState state_;
    EyeState base_;  // 眨眼/微动的基准，情绪切换时更新
    EyeThemeSelection theme_selection_;
    // Idle animation runs in its own FreeRTOS task while application callbacks may
    // switch overlays, so mode must not be a plain cross-task variable.
    std::atomic<Mode> mode_{Mode::kEyes};
    PlushBehavior* behavior_ = nullptr;
    SemaphoreHandle_t mutex_ = nullptr;
};
