#pragma once

#include "mpr121.h"

#include <functional>

// 触摸轮询与边沿检测。只回答「哪个电极刚被碰到 / 刚离开」，
// 不知道电极对应身体哪个部位，也不知道该做什么反应 —— 那是 PlushBehavior 的事。
//
// 没有 IRQ 引脚可用（引脚已用尽），因此靠固定周期轮询。去抖已由芯片的
// DEBOUNCE 寄存器完成，这里只比较状态位，不做第二重软件去抖。
class TouchController {
public:
    using TouchHandler = std::function<void(int electrode, bool pressed)>;

    explicit TouchController(Mpr121* mpr);

    bool available() const { return mpr_ != nullptr; }
    void SetHandler(TouchHandler handler) { handler_ = std::move(handler); }
    void Start();

    // 比较新状态位与上一次，逐位产出事件。
    // 公开是为了两个用途：主机侧单测，以及测试通道的模拟触摸。
    void ApplyTouchBits(uint16_t bits);

private:
    static void TaskEntry(void* arg);
    void Run();

    Mpr121* mpr_ = nullptr;
    TouchHandler handler_;
    uint16_t last_bits_ = 0;
};
