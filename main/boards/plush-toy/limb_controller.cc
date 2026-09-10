#include "limb_controller.h"
#include "config.h"

#include <esp_log.h>
#include <esp_timer.h>

#include <algorithm>
#include <cstdint>

#define TAG "LimbController"

namespace {
struct Item {
    Gesture g;
    int times;
};

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
    ESP_LOGI(TAG, "动作任务已启动，行程限制 ±%d°", SERVO_MAX_ANGLE);
}

bool LimbController::Enqueue(Gesture g, int times) {
    if (pca_ == nullptr || queue_ == nullptr) return false;
    Item it{g, times};
    // 不等待：队列满说明上一个动作还没做完，直接丢弃新动作。
    // 这是串行化的关键 —— 绝不允许两个手势叠加。
    if (xQueueSend(queue_, &it, 0) != pdTRUE) {
        ESP_LOGW(TAG, "队列已满，丢弃手势 %d", (int)g);
        return false;
    }
    return true;
}

void LimbController::TaskEntry(void* arg) {
    static_cast<LimbController*>(arg)->Run();
}

void LimbController::Run() {
    Item it;
    while (true) {
        if (xQueueReceive(queue_, &it, portMAX_DELAY) == pdTRUE) {
            busy_until_us_ = INT64_MAX;       // 动作期间无条件为忙
            Perform(it.g, it.times);
            vTaskDelay(pdMS_TO_TICKS(200));
            Relax();
            vTaskDelay(pdMS_TO_TICKS(300));   // 强制冷却，让电源轨恢复
            // 动作结束后机械振动还会持续一小段，沉降窗口内继续算忙
            busy_until_us_ = esp_timer_get_time() + MOTION_SERVO_SETTLE_MS * 1000;
        }
    }
}

bool LimbController::busy() const { return esp_timer_get_time() < busy_until_us_; }

void LimbController::MoveTo(int left_deg, int right_deg, int step_ms) {
    // 分步逼近，绝不瞬间大幅跳变 —— 急转是电流尖峰的主要来源
    constexpr int kStep = 2;
    while (left_deg_ != left_deg || right_deg_ != right_deg) {
        if (left_deg_ < left_deg) {
            left_deg_ = std::min(left_deg_ + kStep, left_deg);
        } else if (left_deg_ > left_deg) {
            left_deg_ = std::max(left_deg_ - kStep, left_deg);
        }
        if (right_deg_ < right_deg) {
            right_deg_ = std::min(right_deg_ + kStep, right_deg);
        } else if (right_deg_ > right_deg) {
            right_deg_ = std::max(right_deg_ - kStep, right_deg);
        }
        pca_->SetPulseUs(SERVO_LEFT_CHANNEL, DegToUs(left_deg_));
        pca_->SetPulseUs(SERVO_RIGHT_CHANNEL, DegToUs(right_deg_));
        vTaskDelay(pdMS_TO_TICKS(step_ms));
    }
}

void LimbController::Relax() {
    pca_->AllOff();
}

void LimbController::Perform(Gesture g, int times) {
    ESP_LOGI(TAG, "执行手势 %d ×%d", (int)g, times);
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
                vTaskDelay(pdMS_TO_TICKS(150));   // 实测缺此间歇会 BROWNOUT
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
