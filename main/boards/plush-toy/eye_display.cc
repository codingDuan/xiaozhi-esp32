#include "eye_display.h"
#include "eye_theme.h"
#include "overlay_qr.h"
#include "overlay_renderer.h"
#include "plush_behavior.h"
#include "settings.h"

#include <esp_heap_caps.h>
#include <esp_log.h>
#include <esp_random.h>
#include <freertos/task.h>

#include <algorithm>
#include <cstring>
#include <string>

#define TAG "EyeDisplay"

namespace {

// 情绪 → 眼睛参数。取值来自交互式原型（spec §2.2.1），已在原型里逐个调过。
// 服务端 EMOJI_MAP（textUtils.py:8-30）共 21 种，这里覆盖有明确表情的，
// 其余回落 neutral —— 服务端的 get_emotion 未命中白名单时会下发 "happy"，
// 所以这里不会收到未知值，但仍保留兜底。
struct EmotionPreset {
    const char* name;
    EyeState state;
};

const EmotionPreset kPresets[] = {
    {"neutral", {0.94f, 0.0f, 0.00f, 1.00f, 0.0f, 0.00f, 0x363E}},
    {"happy", {0.62f, 0.0f, 0.05f, 1.00f, 0.0f, 0.85f, 0x363E}},
    {"laughing", {0.34f, 0.0f, 0.10f, 0.95f, 0.0f, 1.00f, 0x363E}},
    {"funny", {0.45f, 0.0f, 0.08f, 1.00f, 0.0f, 0.90f, 0x363E}},
    {"silly", {0.55f, 0.3f, 0.10f, 1.05f, -6.0f, 0.70f, 0x363E}},
    {"sad", {0.58f, 0.0f, 0.34f, 1.00f, 19.0f, -0.40f, 0x363E}},
    {"crying", {0.30f, 0.0f, 0.50f, 1.10f, 24.0f, -0.70f, 0x363E}},
    {"angry", {0.68f, 0.0f, -0.10f, 0.82f, -27.0f, -0.25f, 0x363E}},
    {"surprised", {1.00f, 0.0f, 0.00f, 1.45f, 0.0f, 0.00f, 0x363E}},
    {"shocked", {1.00f, 0.0f, -0.05f, 1.55f, 0.0f, 0.00f, 0x363E}},
    {"thinking", {0.78f, -0.62f, -0.40f, 1.00f, -9.0f, 0.00f, 0x363E}},
    {"sleepy", {0.18f, 0.0f, 0.25f, 1.00f, 6.0f, -0.15f, 0x363E}},
    {"relaxed", {0.70f, 0.0f, 0.05f, 1.00f, 0.0f, 0.55f, 0x363E}},
    {"loving", {0.66f, 0.0f, 0.05f, 1.25f, 0.0f, 0.80f, 0xF97A}},
    {"kissy", {0.60f, 0.0f, 0.05f, 1.20f, 0.0f, 0.85f, 0xF97A}},
    {"confused", {0.90f, 0.0f, -0.70f, 1.00f, -5.0f, 0.00f, 0x363E}},
    {"embarrassed", {0.55f, 0.25f, 0.30f, 1.10f, 8.0f, 0.30f, 0xF97A}},
    {"winking", {0.85f, 0.0f, 0.00f, 1.00f, 0.0f, 0.40f, 0x363E}},
    {"cool", {0.60f, 0.0f, -0.05f, 0.90f, -12.0f, 0.20f, 0x363E}},
    {"confident", {0.65f, 0.0f, -0.08f, 0.95f, -10.0f, 0.30f, 0x363E}},
    {"delicious", {0.50f, 0.0f, 0.15f, 1.10f, 0.0f, 0.75f, 0x363E}},
};

const EyeState& LookupEmotion(const char* name) {
    if (name != nullptr) {
        for (const auto& p : kPresets) {
            if (std::strcmp(p.name, name) == 0)
                return p.state;
        }
    }
    return kPresets[0].state;  // neutral 兜底
}

inline uint32_t RandRange(uint32_t lo, uint32_t hi) { return lo + (esp_random() % (hi - lo + 1)); }

}  // namespace

// ISR 上下文。只 give 一次信号量，不做别的。
bool EyeDisplay::OnColorTransDone(esp_lcd_panel_io_handle_t, esp_lcd_panel_io_event_data_t*,
                                  void* ctx) {
    auto* self = static_cast<EyeDisplay*>(ctx);
    BaseType_t woken = pdFALSE;
    xSemaphoreGiveFromISR(self->blit_done_, &woken);
    return woken == pdTRUE;
}

EyeDisplay::EyeDisplay(esp_lcd_panel_handle_t left, esp_lcd_panel_handle_t right,
                       esp_lcd_panel_io_handle_t io_left, esp_lcd_panel_io_handle_t io_right)
    : left_(left), right_(right) {
    mutex_ = xSemaphoreCreateMutex();
    // 上限取整屏交错传输的条数：ceil(240/16) * 2 只眼 = 30，留一倍余量
    blit_done_ = xSemaphoreCreateCounting(64, 0);
    const esp_lcd_panel_io_callbacks_t cbs = {.on_color_trans_done = OnColorTransDone};
    esp_lcd_panel_io_register_event_callbacks(io_left, &cbs, this);
    esp_lcd_panel_io_register_event_callbacks(io_right, &cbs, this);
    const size_t n = (size_t)EyeRenderer::kSize * EyeRenderer::kSize;
    buf_left_ = (uint16_t*)heap_caps_malloc(n * 2, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    buf_right_ = (uint16_t*)heap_caps_malloc(n * 2, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (buf_left_ == nullptr || buf_right_ == nullptr) {
        ESP_LOGE(TAG, "PSRAM 分配失败（每块需 %u 字节），眼睛不可用", (unsigned)(n * 2));
        return;
    }
    {
        Settings s("plush_eye", false);
        EyeRenderer::SetSwapRB(s.GetInt("swap_rb", 0) != 0);
        theme_selection_ = EyeThemeSelection(static_cast<uint8_t>(s.GetInt("theme_id", 0)));
    }
    // 【临时】日系虹膜调参期间强制上电即用 anime-sky。板子连的是手机热点、
    // 开发机连的是另一个 WiFi，HTTP 测试通道够不着，换主题只能靠重烧。
    // 这里只覆盖内存里的选择、不写 NVS，删掉本行即恢复由 NVS 决定。
    theme_selection_.Select("anime-sky");
    base_ = state_ = LookupEmotion("neutral");
    Flush(EyeRenderer::FullRect());
    ESP_LOGI(TAG, "双眼初始化完成");
}

EyeDisplay::~EyeDisplay() {
    if (buf_left_)
        heap_caps_free(buf_left_);
    if (buf_right_)
        heap_caps_free(buf_right_);
    if (mutex_)
        vSemaphoreDelete(mutex_);
    if (blit_done_)
        vSemaphoreDelete(blit_done_);
}

bool EyeDisplay::Lock(int timeout_ms) {
    if (mutex_ == nullptr)
        return false;
    TickType_t wait = (timeout_ms <= 0) ? portMAX_DELAY : pdMS_TO_TICKS(timeout_ms);
    return xSemaphoreTake(mutex_, wait) == pdTRUE;
}

void EyeDisplay::Unlock() {
    if (mutex_ != nullptr)
        xSemaphoreGive(mutex_);
}

void EyeDisplay::Flush(DirtyRect r) {
    if (buf_left_ == nullptr || buf_right_ == nullptr)
        return;
    if (r.w <= 0 || r.h <= 0)
        return;

    xSemaphoreTake(mutex_, portMAX_DELAY);

    // SetEyeState may have started before an overlay and waited here while the
    // overlay was being drawn. Re-check after acquiring the display lock so a
    // queued idle-animation frame cannot immediately cover the overlay.
    if (mode_.load(std::memory_order_relaxed) != Mode::kEyes) {
        xSemaphoreGive(mutex_);
        return;
    }

    // 双眼不对称偏移在此施加，不放进 EyeRenderer —— 渲染器保持可精确镜像测试。
    // 完全对称的眼睛看起来像机器。
    EyeState l = state_;
    l.pupil_x += 0.045f;
    const EyeTheme& theme = theme_selection_.theme();
    EyeRenderer::Render(buf_left_, l, theme, +1, r);

    EyeState rr = state_;
    rr.pupil_x -= 0.045f;
    EyeRenderer::Render(buf_right_, rr, theme, -1, r);

    BlitInterleaved(r);

    xSemaphoreGive(mutex_);
}

// 分条传输。帧缓冲在 PSRAM，而 SPI DMA 从 PSRAM 取数时需要在内部 RAM 里
// 分配一块与本次传输等大的弹跳缓冲（spicommon_dma_setup_priv_buffer）。
// 整屏 115KB 一次传会分配失败，并且把内部 RAM 挤干导致 WiFi 事件循环都起不来
// —— 实测现象。拆成 16 行一条（7.7KB）后弹跳缓冲小到可稳定分配。
//
// 无竞态：各条读的是同一块 PSRAM 缓冲的不同区域，传输期间内容不变。
//
// 【必须交错，不能一只眼传完再传另一只】
// 眨眼的脏矩形约 204x204 = 83KB，10MHz 下单眼传输约 66ms。若顺序传输，
// 右眼会整整落后左眼 66ms，而一次眨眼总共才 150ms —— 肉眼可见的错位（实测）。
// 按条交错后最大偏差降到一条（约 6ms），看起来就是同时眨。
//
// 【必须等传完再返回】
// draw_bitmap 是异步的，只把传输排进队列就返回。若不等待，下一帧的 Render 会在
// DMA 仍在读 PSRAM 帧缓冲时把它改写。左眼总是先渲染，于是它更早被改掉，两只眼睛
// 显示出不同帧的眼睑位置 —— 表现为眨眼时左右有先后（实测）。
void EyeDisplay::BlitInterleaved(DirtyRect r) {
    constexpr int kStripRows = 16;
    int pending = 0;
    for (int y = 0; y < r.h; y += kStripRows) {
        const int h = (y + kStripRows <= r.h) ? kStripRows : (r.h - y);
        const size_t off = (size_t)y * r.w;
        esp_lcd_panel_draw_bitmap(left_, r.x, r.y + y, r.x + r.w, r.y + y + h, buf_left_ + off);
        esp_lcd_panel_draw_bitmap(right_, r.x, r.y + y, r.x + r.w, r.y + y + h, buf_right_ + off);
        pending += 2;
    }
    // 超时兜底：宁可漏掉一次等待，也不能让显示任务永久卡死
    while (pending-- > 0) {
        if (xSemaphoreTake(blit_done_, pdMS_TO_TICKS(500)) != pdTRUE) {
            ESP_LOGW(TAG, "等待屏幕传输完成超时，剩余 %d 条", pending + 1);
            break;
        }
    }
}

void EyeDisplay::SetEyeState(const EyeState& s) {
    if (mode_.load(std::memory_order_relaxed) != Mode::kEyes) {
        state_ = s;
        return;
    }
    DirtyRect r = EyeRenderer::ComputeDirty(state_, s);
    state_ = s;
    Flush(r);  // r 为空时 Flush 直接返回，不浪费 SPI 带宽
}

void EyeDisplay::SetEmotion(const char* emotion) {
    ESP_LOGI(TAG, "SetEmotion: %s", emotion ? emotion : "(null)");
    base_ = LookupEmotion(emotion);
    if (mode_.load(std::memory_order_relaxed) == Mode::kOverlay) {
        // Overlay lifetime follows the device state. Remember the latest emotion,
        // but do not let an alert/emotion callback hide provisioning or OTA status.
        state_ = base_;
    } else {
        SetEyeState(base_);
    }
    if (behavior_ != nullptr) {
        behavior_->OnEmotion(emotion);  // 同一次调用同时驱动眼睛与手势
    }
}

void EyeDisplay::SetDownloadProgress(int progress, size_t speed) {
    Display::SetDownloadProgress(progress, speed);
    if (buf_left_ == nullptr || buf_right_ == nullptr)
        return;

    mode_.store(Mode::kOverlay, std::memory_order_relaxed);
    xSemaphoreTake(mutex_, portMAX_DELAY);
    OverlayRenderer::RenderProgress(buf_left_, progress);
    OverlayRenderer::RenderProgress(buf_right_, progress);
    BlitInterleaved(EyeRenderer::FullRect());
    xSemaphoreGive(mutex_);
}

void EyeDisplay::ShowQrCode(const char* text) {
    std::vector<uint8_t> modules;
    int side = 0;
    if (!OverlayQr::Encode(text, modules, side)) {
        ESP_LOGE(TAG, "二维码编码失败");
        return;
    }
    if (buf_left_ == nullptr || buf_right_ == nullptr)
        return;

    const Mode previous_mode = mode_.exchange(Mode::kOverlay, std::memory_order_relaxed);
    xSemaphoreTake(mutex_, portMAX_DELAY);
    if (!OverlayRenderer::RenderQr(buf_left_, modules, side)) {
        mode_.store(previous_mode, std::memory_order_relaxed);
        xSemaphoreGive(mutex_);
        ESP_LOGE(TAG, "二维码渲染失败，side=%d", side);
        return;
    }
    OverlayRenderer::RenderWaitIcon(buf_right_);
    BlitInterleaved(EyeRenderer::FullRect());
    xSemaphoreGive(mutex_);
    ESP_LOGI(TAG, "配网二维码已显示，side=%d", side);
}

void EyeDisplay::ShowEyes() {
    mode_.store(Mode::kEyes, std::memory_order_relaxed);
    Flush(EyeRenderer::FullRect());
}

void EyeDisplay::SetSwapRB(bool on) {
    Settings s("plush_eye", true);
    s.SetInt("swap_rb", on ? 1 : 0);
    EyeRenderer::SetSwapRB(on);
    Flush(EyeRenderer::FullRect());  // 通道换了，整屏重绘
    ESP_LOGI(TAG, "红蓝通道互换 = %s（已存 NVS）", on ? "开" : "关");
}

bool EyeDisplay::swap_rb() const { return EyeRenderer::swap_rb(); }

bool EyeDisplay::ChangeTheme(const char* requested_name, std::string& selected_name) {
    const std::string_view requested = requested_name != nullptr ? requested_name : "";

    xSemaphoreTake(mutex_, portMAX_DELAY);
    if (!theme_selection_.Select(requested)) {
        xSemaphoreGive(mutex_);
        return false;
    }
    selected_name = std::string(theme_selection_.theme().name);
    const int selected_id = theme_selection_.id();
    xSemaphoreGive(mutex_);

    Settings settings("plush_eye", true);
    settings.SetInt("theme_id", selected_id);
    Flush(EyeRenderer::FullRect());
    ESP_LOGI(TAG, "眼睛主题 = %s（已存 NVS）", selected_name.c_str());
    return true;
}

void EyeDisplay::StartIdleAnimation() {
    if (!available() || buf_left_ == nullptr) {
        ESP_LOGW(TAG, "眼睛不可用，待机动画未启动");
        return;
    }
    xTaskCreate(IdleTaskEntry, "eye_idle", 4096, this, 2, nullptr);
    ESP_LOGI(TAG, "待机动画已启动（随机眨眼 + 瞳孔游走）");
}

void EyeDisplay::IdleTaskEntry(void* arg) { static_cast<EyeDisplay*>(arg)->IdleLoop(); }

// 眨眼与注视。这是"有生命感"的主要来源，且完全本地、零延迟、断网可用。
//
// 【眼睛不会漂，只会跳】
// 原来是每 50ms 朝目标做一次指数平滑（系数 0.06，时间常数约 800ms），瞳孔
// 一直在缓慢滑动，看着发飘、发呆。真实眼球运动是扫视：七十到一百四十毫秒内
// 快速跳到新目标，然后完全静止注视，其间只有极小幅度的微扫视。
// 这个节奏顺带把待机 SPI 流量降到接近零 —— 注视期一帧都不重绘，
// 而原来每 50ms 就要传一次瞳孔区域。
void EyeDisplay::IdleLoop() {
    const int32_t kTick = 50;

    float gaze_x = 0.0f, gaze_y = 0.0f;
    int32_t to_blink = RandRange(2500, 6000);
    int32_t to_saccade = RandRange(700, 2500);
    int32_t to_micro = RandRange(300, 900);

    // 把当前注视点连同基准情绪推给显示层
    auto push = [this](float gx, float gy, float openness_k) {
        EyeState s = base_;
        s.pupil_x += gx;
        s.pupil_y += gy;
        if (openness_k > 0.0f)
            s.openness = base_.openness * (1.0f - openness_k) + 0.04f * openness_k;
        SetEyeState(s);
        taskYIELD();
    };

    while (true) {
        vTaskDelay(pdMS_TO_TICKS(kTick));
        to_blink -= kTick;
        to_saccade -= kTick;
        to_micro -= kTick;

        if (to_blink <= 0) {
            // 闭得快、睁得慢，真实眨眼就是这个节奏。
            // 每一帧都是 166KB 的双眼同步传输，帧数直接等于时长：三帧太跳，
            // 五帧顺，再多就拖了。原来是 6 帧三角波外加每帧 25ms 固定延时，
            // BlitInterleaved 改成等传输完成后那 25ms 纯属叠加，已去掉。
            static const float kBlinkPhase[] = {0.70f, 1.0f, 0.80f, 0.45f, 0.0f};
            for (float k : kBlinkPhase)
                push(gaze_x, gaze_y, k);
            to_blink = RandRange(2500, 6000);
            to_saccade = RandRange(700, 2500);
            to_micro = RandRange(300, 900);
            continue;
        }

        if (to_saccade <= 0) {
            // 三帧跳到位。瞳孔区的脏矩形远小于眨眼，单帧约 20ms，
            // 三帧合计接近真实扫视的时长。缓动前快后慢，落点不回弹。
            const float from_x = gaze_x, from_y = gaze_y;
            const float to_x = ((int)RandRange(0, 100) - 50) / 125.0f;   // ±0.40
            const float to_y = ((int)RandRange(0, 100) - 50) / 227.0f;   // ±0.22
            static const float kSaccadeEase[] = {0.58f, 0.88f, 1.0f};
            for (float t : kSaccadeEase) {
                gaze_x = from_x + (to_x - from_x) * t;
                gaze_y = from_y + (to_y - from_y) * t;
                push(gaze_x, gaze_y, 0.0f);
            }
            to_saccade = RandRange(700, 2500);
            to_micro = RandRange(300, 900);
            continue;
        }

        if (to_micro <= 0) {
            // 微扫视：注视期内极小幅度的一次位移。没有它，注视期是彻底冻住的，
            // 反而不像活物。幅度控制在一两个像素，只花一帧。
            // 微扫视是累加的，夹一下防止连续几次同向漂出注视范围
            gaze_x = std::clamp(gaze_x + ((int)RandRange(0, 100) - 50) / 2000.0f, -0.5f, 0.5f);
            gaze_y = std::clamp(gaze_y + ((int)RandRange(0, 100) - 50) / 3000.0f, -0.3f, 0.3f);
            push(gaze_x, gaze_y, 0.0f);
            to_micro = RandRange(300, 900);
        }
        // 注视期不重绘
    }
}
