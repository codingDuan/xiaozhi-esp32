#include "motion_controller.h"
#include "config.h"

#include <esp_log.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#define TAG "MotionController"

MotionController::MotionController(Mpu6050* mpu) : mpu_(mpu) {}

void MotionController::Start() {
    if (mpu_ == nullptr) {
        ESP_LOGW(TAG, "MPU6050 不可用，运动感知已禁用");
        return;
    }
    xTaskCreate(TaskEntry, "motion", 3072, this, 3, nullptr);
    ESP_LOGI(TAG, "运动轮询已启动，周期 %d ms", MOTION_POLL_INTERVAL_MS);
}

void MotionController::TaskEntry(void* arg) { static_cast<MotionController*>(arg)->Run(); }

void MotionController::Run() {
    while (true) {
        int16_t x = 0, y = 0, z = 0;
        // 读失败保留上一次判定，下个周期再读。共享总线上偶发失败是正常的。
        if (mpu_->ReadAccel(x, y, z))
            ApplySample(x, y, z, esp_timer_get_time() / 1000);
        vTaskDelay(pdMS_TO_TICKS(MOTION_POLL_INTERVAL_MS));
    }
}

Orientation MotionController::ClassifyOrientation(int16_t up) const {
    // 迟滞：已在某态时用较松的离开门限，未在该态时用较严的进入门限。
    if (orientation_ == Orientation::kUpright)
        return up > MOTION_UPRIGHT_EXIT ? Orientation::kUpright : Orientation::kLying;
    if (orientation_ == Orientation::kInverted)
        return up < MOTION_INVERTED_EXIT ? Orientation::kInverted : Orientation::kLying;
    if (up > MOTION_UPRIGHT_ENTER)
        return Orientation::kUpright;
    if (up < MOTION_INVERTED_ENTER)
        return Orientation::kInverted;
    return Orientation::kLying;
}

void MotionController::UpdateShake(int16_t ax, int16_t ay, int16_t az, int64_t now_ms) {
    if (now_ms < shake_cooldown_until_ms_)
        return;
    if (suppressor_ && suppressor_())
        return;

    // 用平方和比较，避免开方。阈值同样平方后比较。
    const int64_t magnitude_sq = (int64_t)ax * ax + (int64_t)ay * ay + (int64_t)az * az;
    const int64_t high = MOTION_LSB_PER_G + MOTION_SHAKE_DELTA;
    const int64_t low = MOTION_LSB_PER_G - MOTION_SHAKE_DELTA;
    const bool hit = magnitude_sq > high * high || magnitude_sq < low * low;

    if (now_ms - shake_window_start_ms_ > MOTION_SHAKE_WINDOW_MS) {
        shake_window_start_ms_ = now_ms;
        shake_hits_ = 0;
    }
    if (!hit)
        return;
    if (++shake_hits_ < MOTION_SHAKE_HITS)
        return;

    shake_hits_ = 0;
    shake_window_start_ms_ = now_ms;
    shake_cooldown_until_ms_ = now_ms + MOTION_SHAKE_COOLDOWN_MS;
    if (handler_)
        handler_(MotionEvent::kShake, orientation_);
}

void MotionController::ApplySample(int16_t ax, int16_t ay, int16_t az, int64_t now_ms) {
    // 合理性闸门。实测 I2C 会偶发吐出全 1 的坏字节，把加速度读成 [2647,-1,-1]
    // 或 az=-258。整帧丢弃，姿态与摇晃都不参与 —— 一个坏样本曾把姿态从竖直
    // 翻成躺倒，眼睛跟着变 sleepy。
    const int64_t magnitude_sq = (int64_t)ax * ax + (int64_t)ay * ay + (int64_t)az * az;
    const int64_t min_sq = (int64_t)MOTION_PLAUSIBLE_MIN * MOTION_PLAUSIBLE_MIN;
    const int64_t max_sq = (int64_t)MOTION_PLAUSIBLE_MAX * MOTION_PLAUSIBLE_MAX;
    if (magnitude_sq < min_sq || magnitude_sq > max_sq) {
        ++rejected_samples_;
        return;
    }

    const int16_t up = MOTION_UP_AXIS_Z ? az : ay;
    const Orientation next = ClassifyOrientation(up);
    if (next == orientation_) {
        pending_count_ = 0;  // 回到当前态，之前攒的确认作废
    } else {
        // 落在合理区间内的坏样本仍可能出现，因此还要求连续若干次判定一致。
        if (next != pending_orientation_) {
            pending_orientation_ = next;
            pending_count_ = 1;
        } else {
            ++pending_count_;
        }
        if (pending_count_ >= MOTION_ORIENT_CONFIRM) {
            orientation_ = next;
            pending_count_ = 0;
            if (handler_)
                handler_(MotionEvent::kOrientationChanged, orientation_);
        }
    }
    UpdateShake(ax, ay, az, now_ms);
}
