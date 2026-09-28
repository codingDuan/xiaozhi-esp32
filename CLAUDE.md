# CLAUDE.md

Project architecture, board rules, and validation policy live in `AGENTS.md` — read it first.

@AGENTS.md

## 固件

### vTaskDelay 受 100Hz tick 下限约束

本工程 `CONFIG_FREERTOS_HZ=100`（`sdkconfig:2836`），**一个 tick = 10ms**。`pdMS_TO_TICKS()` 向下取整，所以任何小于 10ms 的延时都会变成 **0 tick，即完全不等待**：

```c
vTaskDelay(pdMS_TO_TICKS(9));   // 0 tick — 不等待
vTaskDelay(pdMS_TO_TICKS(2));   // 0 tick — 不等待
vTaskDelay(pdMS_TO_TICKS(1));   // 0 tick — 不等待
```

实机后果：ADS1115 的转换等待被整体跳过，轮询在转换完成前就判超时，`thermal_code` 一次都读不出来。

需要亚 10ms 的等待时，用 `ads1115.cc` 里的写法把下限钳到 1 tick：

```c
int TicksAtLeast(int ms) {
    const int ticks = (int)pdMS_TO_TICKS(ms);
    return ticks > 0 ? ticks : 1;
}
vTaskDelay(TicksAtLeast(kPollWaitMs));
```

注意这样最短仍是 10ms，不是你写的毫秒数。真正需要微秒级精确延时的场合（外设时序）用 `esp_rom_delay_us()` 忙等，不要指望 `vTaskDelay`。

只有 `sdkconfig.defaults.esp32p4` 是 `CONFIG_FREERTOS_HZ=1000`；不要按 P4 的 1ms tick 推断本板行为。

### 烧录工作目录

`idf.py` 的所有命令（`reconfigure` / `build` / `flash` / `monitor`）都必须在**仓库根目录** `/Users/lianjia/Workspace/xiaozhi-esp32` 下执行——那里才有 ESP-IDF 工程的顶层 `CMakeLists.txt`。不要在 `main/`、`main/boards/plush-toy/` 或 `hardware/plush-toy-mainboard/` 下运行（做完 PCB 工作后当前目录常常停在 `hardware/` 里，先 `cd` 回根目录）。

```sh
cd /Users/lianjia/Workspace/xiaozhi-esp32
source ~/.espressif/tools/activate_idf_v6.1.sh
export PATH="$IDF_PATH/tools:$PATH"       # 本机 idf.py 是 shell 函数，脚本里找不到
idf.py -p /dev/cu.usbmodem5C834268091 flash monitor
```

板级源文件由 configure 阶段的 glob 收集，**新增或删除 `main/boards/plush-toy/` 下的 `.c` / `.cc` 后必须先 `idf.py reconfigure`**，否则新文件不会进构建。

`scripts/build.py` 会改写本地 `sdkconfig` 和 `build/`；切过其他芯片或板型后，不要假设 `build/` 还对应 `plush-toy`。详见 `main/boards/plush-toy/README.md`。

## PCB

`hardware/plush-toy-mainboard` 的检查流程见 `.claude/skills/pcb-check/SKILL.md`。核心规则：**没有重新灌铜的 DRC 结果一律不可信**。
