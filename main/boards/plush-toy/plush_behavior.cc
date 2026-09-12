#include "plush_behavior.h"
#include "application.h"
#include "eye_display.h"
#include "settings.h"

#include <esp_log.h>
#include <wifi_manager.h>

#define TAG "PlushBehavior"

PlushBehavior::PlushBehavior(LimbController* limbs, EyeDisplay* display)
    : limbs_(limbs), display_(display) {
    Settings settings("plush", false);
    touch_modes_ = (uint32_t)settings.GetInt("touch_modes", TOUCH_MODES_DEFAULT);
    motion_modes_ = (uint32_t)settings.GetInt("motion_modes", MOTION_MODES_DEFAULT);
    gesture_modes_ = (uint32_t)settings.GetInt("gesture_modes", GESTURE_MODES_DEFAULT);
}

void PlushBehavior::SetGestureModes(uint32_t modes) {
    gesture_modes_ = modes;
    Settings settings("plush", true);
    settings.SetInt("gesture_modes", (int32_t)modes);
    ESP_LOGI(TAG, "自发手势掩码改为 0x%02X", (unsigned)modes);
}

void PlushBehavior::SetMotionModes(uint32_t modes) {
    motion_modes_ = modes;
    Settings settings("plush", true);
    settings.SetInt("motion_modes", (int32_t)modes);
    ESP_LOGI(TAG, "运动模式掩码改为 0x%02X", (unsigned)modes);
}

void PlushBehavior::SetTouchModes(uint32_t modes) {
    touch_modes_ = modes;
    Settings settings("plush", true);
    settings.SetInt("touch_modes", (int32_t)modes);
    ESP_LOGI(TAG, "触摸模式掩码改为 0x%02X", (unsigned)modes);
}

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
    Gesture g;
    if (StateGesture(to, gesture_modes_, g))
        limbs_->Enqueue(g, 1);
}

void PlushBehavior::OnEmotion(const char* emotion) {
    if (emotion == nullptr || limbs_ == nullptr)
        return;

    Gesture g;
    int times = 1;
    if (EmotionGesture(emotion, gesture_modes_, g, times))
        limbs_->Enqueue(g, times);
}

void PlushBehavior::OnTouch(int electrode, bool pressed) {
    ESP_LOGI(TAG, "触摸 电极%d %s，掩码 0x%02X", electrode, pressed ? "按下" : "松开",
             (unsigned)touch_modes_);

    if ((touch_modes_ & TOUCH_MODE_REFLEX) != 0) {
        if (display_ != nullptr)
            display_->SetEmotion(pressed ? "happy" : "neutral");
        if (pressed && limbs_ != nullptr && limbs_->available())
            limbs_->Enqueue(Gesture::kCheer, 1);
    }

    // 松开不触发任何网络行为：一次触摸只该引起一轮对话，
    // 否则手指离开时会再来一轮。
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
