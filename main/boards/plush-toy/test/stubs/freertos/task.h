#pragma once

inline void vTaskDelay(int) {}

using TaskFunction_t = void (*)(void*);
// 主机侧不真的起任务：Start() 只需能编译链接，轮询逻辑通过 ApplyTouchBits 测。
inline int xTaskCreate(TaskFunction_t, const char*, int, void*, int, void*) { return 1; }
