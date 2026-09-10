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
- `eye_theme.*`：20 个原创参数化眼睛主题，以及名称解析和顺序切换状态机。
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

### 切换眼睛主题

说“换眼睛”会按以下顺序切到下一种主题，最后一种后回到第一种：

`ocean`、`emerald`、`violet`、`amber`、`rose`、`ice`、`copper`、`jade`、`midnight`、`pearl`、`void-blue`、`void-purple`、`void-rose`、`dragon-amber`、`dragon-emerald`、`dragon-violet`、`cat-gold`、`cat-jade`、`cat-ice`、`cat-rose`、`uncanny-human`、`uncanny-dragon`、`anime-sky`、`anime-rose`、`anime-gold`、`anime-violet`。

也可指名选择，例如“换成 `dragon-amber` 眼睛”或“换成 `cat-gold` 眼睛”。前者是竖瞳龙眼，后者是横瞳猫眼。`anime-*` 四种走日系画法：虹膜放大到写实的一倍半、上缘压一条眼睑投影带、下缘补一道反射光月牙、加放射纤维和加粗的睫毛线，高光按虹膜比例放大。主题选择会持久化，断电重启后保持；它与 `self.eyes.swap_colors` 的面板 RGB/BGR 校准相互独立。

## 本地服务端地址

设备会把配网时填写的 OTA 地址持久化到 NVS；服务器 IP 变化后，即使服务仍监听端口，设备也无法自动找到新地址。当前构建已启用 lwIP 的 mDNS 查询，因此同一局域网内可优先使用稳定的 Bonjour 主机名：

```text
OTA:       http://MacBook-Pro-107.local:8003/xiaozhi/ota/
WebSocket: ws://MacBook-Pro-107.local:8010/xiaozhi/v1/
Vision:    http://MacBook-Pro-107.local:8003/mcp/vision/explain
```

其中 OTA 地址由设备配网写入；WebSocket 和 Vision 地址写在服务端 `data/.config.yaml`。`.local` 方案避免普通 DHCP 地址变化，但只适用于设备与 Mac 在同一二层网络且网络允许 mDNS；手机热点可能隔离组播，必须实测。若解析失败，应在固定路由器上做 DHCP 地址保留，或使用可达的域名，不要退回每次手工追踪随机 IP。

## 文本动作测试

固件在 TCP `8181` 提供一个仅用于验收的独立 HTTP 通道；它不经过唤醒词、语音识别、大模型、WebSocket 或本地服务。因此板子只要已连上 Wi-Fi，即使没有语音会话也可以测试。通道只接受其持久化 `websocket.url` 中的 IPv4 主机发起的请求；当前开发机地址变更后，应让设备重新获取该配置再测试。

先检查通道状态（将地址替换为板子的局域网 IP）：

```sh
python3 tools/plush_toy_test.py --device-url http://172.20.10.2:8181 status
```

单项测试示例：

```sh
python3 tools/plush_toy_test.py --device-url http://172.20.10.2:8181 wave --side left
python3 tools/plush_toy_test.py --device-url http://172.20.10.2:8181 hug
python3 tools/plush_toy_test.py --device-url http://172.20.10.2:8181 cheer --times 3
python3 tools/plush_toy_test.py --device-url http://172.20.10.2:8181 eyes dragon-amber
python3 tools/plush_toy_test.py --device-url http://172.20.10.2:8181 emotion happy
python3 tools/plush_toy_test.py --device-url http://172.20.10.2:8181 diagnostics
```

`emotion` 与 `eyes` 的区别：`eyes` 只换虹膜主题，`emotion` 走的是服务端 emotion 通道的同一入口 `EyeDisplay::SetEmotion`，一次调用同时改变眼睛表情并触发对应手势（happy 摆手、loving 张臂、sad 垂臂、surprised 双手上举）。angry 与 thinking 按设计只改眼睛、不产生动作。

执行完整的实机动作回归：

```sh
python3 tools/plush_toy_test.py --device-url http://172.20.10.2:8181 run-regression
```

回归覆盖三组：六个眼睛主题各对应一条虹膜渲染路径（圆瞳浅巩膜、竖瞳暗巩膜、横瞳、无巩膜、照片纹理、日系画法）、三个方向的挥手与拥抱欢呼、六个情绪联动。

`--device-url` 默认是当前开发板地址 `http://172.20.10.2:8181`，但建议每次明确传入。`{"accepted":true}` 表示请求已由板子的应用任务接收和排队；舵机是否真正转动、眼睛是否切换仍需目视验收。情绪联动尤其要看 angry 那条：眼睛应当变化而手臂必须保持不动。

## 触摸标定（MPR121）

**接线前先看这条：模块的 VCC 接 ESP32 的 3V3，不要接 5V。** 模块的 I2C 上拉电阻拉到自身 VCC，接 5V 会把 SDA(GPIO44) 与 SCL(GPIO3) 拉到 5V，超出 ESP32-S3 耐压；GPIO3 还是 JTAG_SEL 启动引脚。

MPR121 并入舵机那条 I2C（`I2C_NUM_0`），地址 0x5A，与 PCA9685 的 0x40 不冲突，不占用任何新引脚。引脚已用尽，IRQ 接不上，因此靠 50ms 轮询，去抖由芯片的 `DEBOUNCE` 寄存器完成。

阈值必须实机标定，`config.h` 里的出厂值只是猜测 —— 布料厚度和电极面积会显著改变触发点。步骤：

```sh
python3 tools/plush_toy_test.py --device-url http://172.20.10.2:8181 touch-modes 0x09
python3 tools/plush_toy_test.py --device-url http://172.20.10.2:8181 status
```

`status` 会带出 `touch_filtered` 与 `touch_baseline`。手指不碰时两者接近；手指贴上去时 `touch_filtered` 明显下降。记下这个差值，把约六成填进 `config.h` 的 `TOUCH_PRESS_THRESHOLD`，约三成填 `TOUCH_RELEASE_THRESHOLD`，然后重新烧录。

**释放阈值必须低于触摸阈值**，这是迟滞的来源。两者相等或反过来会让电极在临界点反复抖动，日志里表现为一秒内几十次按下松开。

四个响应模式可叠加，掩码存 NVS，改完立即生效且重启保持：

| 位 | 值 | 模式 |
|---|---|---|
| 0 | 0x01 | 本地反射：直接改眼睛、动手臂 |
| 1 | 0x02 | 唤醒对话：进入聆听状态 |
| 2 | 0x04 | 上报大模型：把触摸作为一句话送给服务端 |
| 3 | 0x08 | 读值诊断：把原始计数放进 status 返回 |

默认 `0x09`。上报位与唤醒位是包含关系：上报走 `WakeWordInvoke`，本身就带唤醒效果，两位同开不会触发两轮对话。

没接传感器也能验证四条响应路径：

```sh
python3 tools/plush_toy_test.py --device-url http://172.20.10.2:8181 simulate-touch 0
python3 tools/plush_toy_test.py --device-url http://172.20.10.2:8181 simulate-touch 0 --release
```

它复用 `TouchController::ApplyTouchBits`，与真实触摸走同一条路径，因此结果不依赖手指位置和力度。

## 验证

纯渲染和二维码编码无需 ESP-IDF 或硬件：

```sh
cd main/boards/plush-toy/test
make clean && make test
```

观感改动还要肉眼过一遍。下面这条把每个主题的七种情绪渲成 PNG，
默认渲 `ocean` 和 `anime-sky` 两种画法便于对照：

```sh
make preview-png                              # 默认对照
make preview-png THEMES="anime-rose midnight" # 指名渲某几种
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
- [触摸感知设计（MPR121）](../../../docs/superpowers/specs/2026-09-10-plush-toy-mpr121-touch-design.md)
- [运动感知设计（MPU6050）](../../../docs/superpowers/specs/2026-09-10-plush-toy-mpu6050-motion-design.md)
- [进度汇总](../../../docs/superpowers/plans/STATUS.md)
- [剩余 TODO](../../../docs/superpowers/plans/TODO.md)
