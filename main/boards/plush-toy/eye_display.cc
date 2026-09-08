#include "eye_display.h"
#include "plush_behavior.h"
#include "settings.h"

#include <esp_heap_caps.h>
#include <esp_log.h>
#include <esp_random.h>
#include <freertos/task.h>

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
    {"neutral",   {0.94f, 0.0f,  0.00f, 1.00f,   0.0f,  0.00f, 0x363E}},
    {"happy",     {0.62f, 0.0f,  0.05f, 1.00f,   0.0f,  0.85f, 0x363E}},
    {"laughing",  {0.34f, 0.0f,  0.10f, 0.95f,   0.0f,  1.00f, 0x363E}},
    {"funny",     {0.45f, 0.0f,  0.08f, 1.00f,   0.0f,  0.90f, 0x363E}},
    {"silly",     {0.55f, 0.3f,  0.10f, 1.05f,  -6.0f,  0.70f, 0x363E}},
    {"sad",       {0.58f, 0.0f,  0.34f, 1.00f,  19.0f, -0.40f, 0x363E}},
    {"crying",    {0.30f, 0.0f,  0.50f, 1.10f,  24.0f, -0.70f, 0x363E}},
    {"angry",     {0.68f, 0.0f, -0.10f, 0.82f, -27.0f, -0.25f, 0x363E}},
    {"surprised", {1.00f, 0.0f,  0.00f, 1.45f,   0.0f,  0.00f, 0x363E}},
    {"shocked",   {1.00f, 0.0f, -0.05f, 1.55f,   0.0f,  0.00f, 0x363E}},
    {"thinking",  {0.78f,-0.62f,-0.40f, 1.00f,  -9.0f,  0.00f, 0x363E}},
    {"sleepy",    {0.18f, 0.0f,  0.25f, 1.00f,   6.0f, -0.15f, 0x363E}},
    {"relaxed",   {0.70f, 0.0f,  0.05f, 1.00f,   0.0f,  0.55f, 0x363E}},
    {"loving",    {0.66f, 0.0f,  0.05f, 1.25f,   0.0f,  0.80f, 0xF97A}},
    {"kissy",     {0.60f, 0.0f,  0.05f, 1.20f,   0.0f,  0.85f, 0xF97A}},
    {"confused",  {0.90f, 0.0f, -0.70f, 1.00f,  -5.0f,  0.00f, 0x363E}},
    {"embarrassed",{0.55f,0.25f, 0.30f, 1.10f,   8.0f,  0.30f, 0xF97A}},
    {"winking",   {0.85f, 0.0f,  0.00f, 1.00f,   0.0f,  0.40f, 0x363E}},
    {"cool",      {0.60f, 0.0f, -0.05f, 0.90f, -12.0f,  0.20f, 0x363E}},
    {"confident", {0.65f, 0.0f, -0.08f, 0.95f, -10.0f,  0.30f, 0x363E}},
    {"delicious", {0.50f, 0.0f,  0.15f, 1.10f,   0.0f,  0.75f, 0x363E}},
};

const EyeState& LookupEmotion(const char* name) {
    if (name != nullptr) {
        for (const auto& p : kPresets) {
            if (std::strcmp(p.name, name) == 0) return p.state;
        }
    }
    return kPresets[0].state;   // neutral 兜底
}

inline uint32_t RandRange(uint32_t lo, uint32_t hi) {
    return lo + (esp_random() % (hi - lo + 1));
}

}  // namespace

EyeDisplay::EyeDisplay(esp_lcd_panel_handle_t left, esp_lcd_panel_handle_t right)
    : left_(left), right_(right) {
    mutex_ = xSemaphoreCreateMutex();
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
    }
    base_ = state_ = LookupEmotion("neutral");
    Flush(EyeRenderer::FullRect());
    ESP_LOGI(TAG, "双眼初始化完成");
}

EyeDisplay::~EyeDisplay() {
    if (buf_left_) heap_caps_free(buf_left_);
    if (buf_right_) heap_caps_free(buf_right_);
    if (mutex_) vSemaphoreDelete(mutex_);
}

bool EyeDisplay::Lock(int timeout_ms) {
    if (mutex_ == nullptr) return false;
    TickType_t wait = (timeout_ms <= 0) ? portMAX_DELAY : pdMS_TO_TICKS(timeout_ms);
    return xSemaphoreTake(mutex_, wait) == pdTRUE;
}

void EyeDisplay::Unlock() {
    if (mutex_ != nullptr) xSemaphoreGive(mutex_);
}

void EyeDisplay::Flush(DirtyRect r) {
    if (buf_left_ == nullptr || buf_right_ == nullptr) return;
    if (r.w <= 0 || r.h <= 0) return;

    xSemaphoreTake(mutex_, portMAX_DELAY);

    // 双眼不对称偏移在此施加，不放进 EyeRenderer ——
    // 渲染器保持可精确镜像测试。完全对称的眼睛看起来像机器。
    // 先把两只眼都渲染好，再交错传输。
    // 双眼不对称偏移在此施加，不放进 EyeRenderer —— 渲染器保持可精确镜像测试。
    // 完全对称的眼睛看起来像机器。
    EyeState l = state_;
    l.pupil_x += 0.045f;
    EyeRenderer::Render(buf_left_, l, +1, r);

    EyeState rr = state_;
    rr.pupil_x -= 0.045f;
    EyeRenderer::Render(buf_right_, rr, -1, r);

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
void EyeDisplay::BlitInterleaved(DirtyRect r) {
    constexpr int kStripRows = 16;
    for (int y = 0; y < r.h; y += kStripRows) {
        const int h = (y + kStripRows <= r.h) ? kStripRows : (r.h - y);
        const size_t off = (size_t)y * r.w;
        esp_lcd_panel_draw_bitmap(left_,  r.x, r.y + y, r.x + r.w, r.y + y + h,
                                  buf_left_ + off);
        esp_lcd_panel_draw_bitmap(right_, r.x, r.y + y, r.x + r.w, r.y + y + h,
                                  buf_right_ + off);
    }
}

void EyeDisplay::SetEyeState(const EyeState& s) {
    DirtyRect r = EyeRenderer::ComputeDirty(state_, s);
    state_ = s;
    Flush(r);   // r 为空时 Flush 直接返回，不浪费 SPI 带宽
}

void EyeDisplay::SetEmotion(const char* emotion) {
    ESP_LOGI(TAG, "SetEmotion: %s", emotion ? emotion : "(null)");
    base_ = LookupEmotion(emotion);
    SetEyeState(base_);
    if (behavior_ != nullptr) {
        behavior_->OnEmotion(emotion);   // 同一次调用同时驱动眼睛与手势
    }
}

void EyeDisplay::SetSwapRB(bool on) {
    Settings s("plush_eye", true);
    s.SetInt("swap_rb", on ? 1 : 0);
    EyeRenderer::SetSwapRB(on);
    Flush(EyeRenderer::FullRect());   // 通道换了，整屏重绘
    ESP_LOGI(TAG, "红蓝通道互换 = %s（已存 NVS）", on ? "开" : "关");
}

bool EyeDisplay::swap_rb() const { return EyeRenderer::swap_rb(); }

void EyeDisplay::StartIdleAnimation() {
    if (!available() || buf_left_ == nullptr) {
        ESP_LOGW(TAG, "眼睛不可用，待机动画未启动");
        return;
    }
    xTaskCreate(IdleTaskEntry, "eye_idle", 4096, this, 2, nullptr);
    ESP_LOGI(TAG, "待机动画已启动（随机眨眼 + 瞳孔游走）");
}

void EyeDisplay::IdleTaskEntry(void* arg) {
    static_cast<EyeDisplay*>(arg)->IdleLoop();
}

// 眨眼与瞳孔游走。这是"有生命感"的主要来源，且完全本地、零延迟、断网可用。
void EyeDisplay::IdleLoop() {
    uint32_t next_blink = RandRange(2500, 6000);
    uint32_t next_roam = RandRange(1500, 4000);
    uint32_t elapsed = 0;
    const uint32_t kTick = 50;

    float roam_x = 0.0f, roam_y = 0.0f;
    float target_x = 0.0f, target_y = 0.0f;

    while (true) {
        vTaskDelay(pdMS_TO_TICKS(kTick));
        elapsed += kTick;

        if (elapsed >= next_blink) {
            // 三角波：睁 → 闭 → 睁，全程约 150ms
            for (int i = 0; i < 6; i++) {
                float k = (i < 3) ? (i / 2.0f) : ((5 - i) / 2.0f);
                EyeState s = base_;
                s.pupil_x += roam_x;
                s.pupil_y += roam_y;
                s.openness = base_.openness * (1.0f - k) + 0.04f * k;
                SetEyeState(s);
                vTaskDelay(pdMS_TO_TICKS(25));
            }
            elapsed = 0;
            next_blink = RandRange(2500, 6000);
            continue;
        }

        if (elapsed >= next_roam) {
            target_x = ((int)RandRange(0, 100) - 50) / 200.0f;   // ±0.25
            target_y = ((int)RandRange(0, 100) - 50) / 300.0f;   // ±0.17
            next_roam = elapsed + RandRange(1500, 4000);
        }
        roam_x += (target_x - roam_x) * 0.06f;
        roam_y += (target_y - roam_y) * 0.06f;

        EyeState s = base_;
        s.pupil_x += roam_x;
        s.pupil_y += roam_y;
        SetEyeState(s);
    }
}
