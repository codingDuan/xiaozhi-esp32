#include "plush_behavior.h"
#include "application.h"
#include "eye_display.h"

#include <esp_log.h>
#include <wifi_manager.h>

#define TAG "PlushBehavior"

PlushBehavior::PlushBehavior(LimbController* limbs, EyeDisplay* display)
    : limbs_(limbs), display_(display) {}

void PlushBehavior::Start() {
    if ((limbs_ == nullptr || !limbs_->available()) && display_ == nullptr) {
        ESP_LOGW(TAG, "肢体不可用，反射行为已禁用");
        return;
    }
    if (limbs_ == nullptr || !limbs_->available()) {
        ESP_LOGW(TAG, "肢体不可用，仅启用显示状态反射");
    }
    xTaskCreate(TaskEntry, "plush_behavior", 3072, this, 2, nullptr);
    ESP_LOGI(TAG, "反射任务已启动");
}

void PlushBehavior::TaskEntry(void* arg) { static_cast<PlushBehavior*>(arg)->Run(); }

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

    if (display_ != nullptr) {
        if (to == kDeviceStateWifiConfiguring) {
            const std::string payload =
                "WIFI:S:" + WifiManager::GetInstance().GetApSsid() + ";T:nopass;;";
            display_->ShowQrCode(payload.c_str());
        } else if (to == kDeviceStateUpgrading) {
            display_->SetDownloadProgress(0, 0);
        } else if (from == kDeviceStateWifiConfiguring || from == kDeviceStateUpgrading) {
            display_->ShowEyes();
        }
    }

    if (limbs_ == nullptr || !limbs_->available())
        return;
    switch (to) {
        case kDeviceStateListening:
            limbs_->Enqueue(Gesture::kLean, 1);  // 微微前倾，像在专心听
            break;
        case kDeviceStateSpeaking:
            limbs_->Enqueue(Gesture::kCheer, 1);  // 说话时轻摆一次
            break;
        case kDeviceStateIdle:
            limbs_->Enqueue(Gesture::kHome, 1);  // 归中泄力
            break;
        default:
            break;
    }
}

void PlushBehavior::OnEmotion(const char* emotion) {
    if (emotion == nullptr || limbs_ == nullptr)
        return;
    std::string e(emotion);

    // 服务端 EMOJI_MAP（textUtils.py:8-30）共 21 种，此处只映射有明确
    // 肢体表达的几类。其余刻意不动作 —— 动作稀疏比动作滥用更自然：
    // angry 时静止不动比手舞足蹈更有张力，thinking 时动作会干扰"正在想"的表达。
    if (e == "happy" || e == "laughing" || e == "funny" || e == "silly") {
        limbs_->Enqueue(Gesture::kCheer, 2);
    } else if (e == "loving" || e == "kissy") {
        limbs_->Enqueue(Gesture::kHug, 1);
    } else if (e == "sad" || e == "crying") {
        limbs_->Enqueue(Gesture::kDroop, 1);
    } else if (e == "surprised" || e == "shocked") {
        limbs_->Enqueue(Gesture::kWaveBoth, 1);
    }
}
