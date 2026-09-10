#pragma once

#include <stdint.h>

// 主机侧不需要真实时钟：判定逻辑的时间一律由 ApplySample 的参数传入，
// 这个桩只服务于永远不会在主机上运行的轮询任务。
inline int64_t esp_timer_get_time() { return 0; }
