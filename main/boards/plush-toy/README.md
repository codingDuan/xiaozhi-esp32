# Plush Toy 毛绒玩具板型

`plush-toy` 是一个面向 ESP32-S3 的 XiaoZhi 固件板型：保留摄像头和语音能力，用两块 GC9A01 圆屏显示参数化双眼，并通过 PCA9685 驱动两个 SG90 舵机作为左右手臂。

这是独立板型，不是现有摄像头板的引脚变体。`config.json` 中的 `type` 和构建 `name` 都是 `plush-toy`，也是 OTA 兼容性边界；发布后不要改名，也不要把本板引脚写回其他板型。

## 开发环境与构建

优先使用 ESP-IDF 6.0.2。若本地项目环境已经固定在经验证的 6.1，也可沿用，但交付时应记录实际版本。

```sh
source /path/to/esp-idf/export.sh
idf.py --version
python3 scripts/build.py --list-boards
python3 scripts/build.py plush-toy --name plush-toy
```

新增或删除板目录中的 `.c` / `.cc` 后先执行 `idf.py reconfigure`，因为 `main/CMakeLists.txt` 通过 configure 阶段的 glob 收集板级源文件。

当前 EIM 环境的 `idf.py` 可能是 shell 函数。若 `scripts/build.py` 找不到它，需要把 IDF tools 显式加入 `PATH`：

```sh
source ~/.espressif/tools/activate_idf_v6.1.sh
export PATH="$IDF_PATH/tools:$PATH"
idf.py reconfigure
idf.py build
idf.py -p /dev/cu.usbmodem5C834268091 flash
```

构建脚本会改变本地 `sdkconfig` 和 `build/` 状态；切换其他芯片或板型后，不要假设旧构建目录仍对应 `plush-toy`。

## 固件结构

- `plush_toy_board.cc`：组装音频、摄像头、双屏、PCA9685、按键和 MCP 工具；只在此导出一个 `DECLARE_BOARD`。
- `eye_renderer.*`：纯 CPU 的 `EyeState -> RGB565` 渲染，可在主机测试。
- `eye_display.*`：双 GC9A01 驱动、脏矩形、交错 SPI 传输和 overlay 模式。
- `overlay_qr.*` / `qrcodegen.*`：将配网文本编码为二维码模块；qrcodegen 是 vendored MIT 许可实现。
- `overlay_renderer.*`：二维码、等待图标和 OTA 进度环的纯像素渲染。
- `pca9685.*`：100kHz I2C 寄存器驱动。
- `limb_controller.*`：动作队列、机械限位、缓动和动作后泄力。
- `plush_behavior.*`：轮询设备状态，将状态和 emotion 映射为眼睛 overlay 与肢体反射。

核心程序仍只依赖 `Board` / `Display` 接口。状态变更由 `Application::SetDeviceState()` 处理；板级行为任务只读取状态，不直接修改核心状态机。

## 关键硬件知识

### 双屏与 PSRAM

两块 GC9A01 共用 MOSI、CLK、DC 和 RST，仅 CS 独立。面包板飞线和双屏并联会降低信号裕量，因此 SPI 默认 10MHz，上限按设计约束为 20MHz。

单眼 240×240 RGB565 帧约 115KB。两眼缓冲位于 PSRAM，但 SPI DMA 需要内部 RAM 弹跳缓冲，所以固件按 16 行分条并左右眼交错传输：既避免一次 115KB DMA 分配耗尽内部 RAM，也把双眼眨眼的最大时差压到一条传输时间。

### 摄像头与 I2C

摄像头 SCCB 实际占用的 I2C 端口由 `CONFIG_SCCB_HARDWARE_I2C_PORT1` 决定，不能相信 `camera_config_t.sccb_i2c_port`；esp32-camera 会覆盖该字段。本板摄像头使用 `I2C_NUM_1`，PCA9685 必须使用 `I2C_NUM_0`，板级 `static_assert` 会在冲突时阻止编译。

PCA9685 地址为 `0x40`，舵机 PWM 为 50Hz，`PRE_SCALE=121`。面包板飞线在 400kHz 下曾出现寄存器回读失真，因此驱动自持 100kHz device handle，不复用硬编码 400kHz 的通用 `I2cDevice`。

### 引脚与 USB

GPIO19/20 保留给 ESP32-S3 原生 USB，GPIO43 保留给控制台 UART TX。两块屏的 CS 使用 GPIO45/46；占用 GPIO43 会导致串口日志乱码。完整引脚定义以 `config.h` 为唯一代码事实来源。

## 供电安全

开发板由 Mac USB 供电时，开发板的 `5V` / `VIN` 必须留空。两个 SG90 使用独立 5V/2A 电源，舵机电源与开发板只共地；不要把两个 5V 电源并联，否则可能向主机 USB 倒灌。

舵机侧应就近并联 1000µF 电解电容和 0.1µF 陶瓷电容。USB 单独带载双舵机已实测会触发 brownout。固件把行程限制在 ±30°，动作串行执行，并在动作后关闭 PWM 泄力；这些是供电和塑料齿保护约束，不是可选优化。

## 显示行为

- 正常状态：参数化眼睛、随机眨眼和瞳孔游走。
- 配网状态：左眼显示 `WIFI:S:<SSID>;T:nopass;;` 二维码，右眼显示等待图标。
- 固件或 assets 下载：两眼显示从 12 点方向顺时针增长的进度环。
- 离开配网或升级状态：恢复眼睛模式；overlay 期间收到的 emotion 只更新恢复后的表情，不提前遮住二维码或进度。

二维码必须是白底黑码并保留四模块静默区。圆屏内接方形约 169px；当前配网内容生成的 25×25 模块二维码使用 5px/module，若增长到 Version 3 的 29×29 模块则自动降为 4px/module。缩放必须把静默区计入，不能固定写死为 5px/module。

## 验证

纯渲染和二维码编码无需 ESP-IDF 或硬件：

```sh
cd main/boards/plush-toy/test
make clean && make test
```

代码交付至少还应执行：

```sh
python3 -m unittest discover -s scripts/tests -v
idf.py reconfigure
idf.py build
```

成功构建不能替代实机验收。烧录后仍需检查：

1. 虹膜为青蓝而不是橙红；必要时调用 `self.eyes.swap_colors` 并持久化校正。
2. 双眼眨眼同步、无花屏，Wi-Fi 和 USB 日志正常。
3. 进入配网状态后二维码可被手机识别并加入热点。
4. OTA/资源下载时进度环随回调推进，失败后恢复眼睛。
5. 舵机动作无卡滞、无 brownout；装进玩偶后再做 trim 校准。

详细设计、实测记录与剩余硬件项见：

- [设计方案](../../../docs/superpowers/specs/2026-09-05-plush-toy-design.md)
- [进度汇总](../../../docs/superpowers/plans/STATUS.md)
- [剩余 TODO](../../../docs/superpowers/plans/TODO.md)
