#include "touch_controller.h"
#include "config.h"

#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#define TAG "TouchController"

TouchController::TouchController(Mpr121* mpr) : mpr_(mpr) {}

void TouchController::Start() {
    if (mpr_ == nullptr) {
        ESP_LOGW(TAG, "MPR121 不可用，触摸感知已禁用");
        return;
    }
    xTaskCreate(TaskEntry, "touch", 3072, this, 3, nullptr);
    ESP_LOGI(TAG, "触摸轮询已启动，周期 %d ms", TOUCH_POLL_INTERVAL_MS);
}

void TouchController::TaskEntry(void* arg) { static_cast<TouchController*>(arg)->Run(); }

void TouchController::Run() {
    while (true) {
        // 读失败不重试也不退出：保留上一次状态，下个周期再读。
        // 共享 I2C 总线上偶发失败是正常的，为此杀掉任务得不偿失。
        ApplyTouchBits(mpr_->ReadTouchBits());
        vTaskDelay(pdMS_TO_TICKS(TOUCH_POLL_INTERVAL_MS));
    }
}

void TouchController::ApplyTouchBits(uint16_t bits) {
    const uint16_t changed = (uint16_t)(bits ^ last_bits_);
    last_bits_ = bits;
    if (changed == 0 || !handler_)
        return;
    for (int ch = 0; ch < TOUCH_ELECTRODE_COUNT; ++ch) {
        const uint16_t mask = (uint16_t)(1u << ch);
        if ((changed & mask) != 0)
            handler_(ch, (bits & mask) != 0);
    }
}
