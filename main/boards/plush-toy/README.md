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

## 测试工具 `tools/plush_toy_test.py`

所有实机测试都走这一个脚本，本节是它的完整命令参考。

固件在 TCP `8181` 提供一个仅用于验收的独立 HTTP 通道；它不经过唤醒词、语音识别、大模型、WebSocket 或本地服务。因此板子只要已连上 Wi-Fi，即使没有语音会话也可以测试。

**三个前提，不满足时命令会超时、被拒，或通道根本没起来**：

1. **`websocket.url` 的 host 必须是数字 IPv4**。通道启动时用它判断是否启用（`TestHttpChannel::enabled()`），是域名就直接不监听 —— 指向 `api.tenclass.net` 这类公共服务端时，测试通道**全程不存在**，扫端口也扫不到。必须先让板子连自建服务端，且服务端地址写成裸 IP，不能用 `.local` 或域名。
2. **开发机必须和板子同网段**。通道只接受与 `websocket.url` 同网段的来源（`PlushToyTestServer` 启动时用 STA 网卡掩码算），Mac 换了网络就会被 403。
3. **`--device-url` 必须显式传板子当前 IP**，脚本默认值只是占位。下文示例省略该参数以保持简洁。

### 怎么拿到板子 IP

板子的应用层控制台完全静默（见 `plans/TODO.md` 技术债），**串口读不到 IP**，别在那儿等。按可靠性排序：

1. **自建服务端的连接日志**。板子连上后服务端能看到对端地址，这是最直接的一手来源，且天然满足前提 1 —— 你本来就得先把服务端跑起来。
2. **路由器的 DHCP 客户端列表**。认乐鑫 OUI，或者认设备名。
3. **ARP 表**。先广播探一遍再查，找乐鑫 OUI：

   ```sh
   for i in $(seq 1 254); do ping -c 1 -W 200 192.168.1.$i >/dev/null 2>&1 & done; wait
   arp -an | grep -v incomplete
   ```

   注意这条只在板子与 Mac 同二层网络时有效；手机热点常做客户端隔离，扫不到不等于板子没上线。

4. **扫 8181 端口**。命中即可用，但**扫不到有歧义** —— 可能是板子不在本网段，也可能是前提 1 没满足导致通道压根没监听，两种情况长得一模一样。所以这条只用来确认，不用来排查。

拿到后统一这么传：

```sh
python3 tools/plush_toy_test.py --device-url http://<板子IP>:8181 status
```

IP 会随 DHCP 变。与其每次重新追踪，不如在路由器上给板子做地址保留 —— 保留之后这一节只需要读一次。

**`{"accepted":true}` 只表示命令进了队列**，与硬件是否存在、动作是否真的发生完全无关。要确认结果，读 `status` 或目视。

### 读状态

```sh
python3 tools/plush_toy_test.py status
```

这是唯一能拿到硬件真实状态的命令 —— 板子的应用层控制台目前完全静默（见 `plans/TODO.md` 技术债），打日志的诊断拿不到任何结果。

| 字段 | 含义 |
|---|---|
| `servo_present` | PCA9685 是否探测到并初始化成功 |
| `servo_diagnostics` | 舵机 PWM 寄存器快照，不改变输出 |
| `touch_present` | MPR121 是否探测到并初始化成功 |
| `touch_modes` | 触摸响应掩码 |
| `touch_bits` | 12 位触摸状态，bit N 对应 ELE N |
| `touch_filtered` / `touch_baseline` | 头部电极的滤波计数与基线 |
| `touch_all_filtered` / `touch_all_baseline` | 全部 12 路，用于确认线接在哪个电极上 |
| `gesture_modes` | 自发手势掩码，默认 `0`（不动） |
| `motion_present` | MPU6050 是否探测到并初始化成功 |
| `motion_modes` | 运动响应掩码 |
| `accel` | 三轴原始加速度，1g = 8192 |
| `orientation` | 0 未知、1 竖着、2 躺倒、3 倒置 |
| `shake_hits` | 当前窗口内的摇晃命中次数 |
| `motion_rejected` | 累计被合理性闸门丢弃的坏样本数 |

触摸与运动的原始读数只在各自掩码的诊断位打开时才出现，默认是打开的。

### 手臂与眼睛

```sh
python3 tools/plush_toy_test.py wave --side left --times 3   # left / right / both
python3 tools/plush_toy_test.py hug
python3 tools/plush_toy_test.py cheer --times 3
python3 tools/plush_toy_test.py eyes dragon-amber
python3 tools/plush_toy_test.py emotion happy
python3 tools/plush_toy_test.py diagnostics
```

`emotion` 与 `eyes` 的区别：`eyes` 只换虹膜主题；`emotion` 走的是服务端 emotion 通道的同一入口 `EyeDisplay::SetEmotion`，一次调用同时改变表情并触发对应手势（happy 摆手、loving 张臂、sad 垂臂、surprised 双手上举）。angry 与 thinking 按设计只改眼睛、不产生动作。

**手势那一半默认是关的**（见下文「自发手势掩码」），所以直接跑 `emotion happy` 只会看到眼睛变化。要验手势映射，先 `gesture-modes 0x08`。

### 自发手势

```sh
python3 tools/plush_toy_test.py gesture-modes 0x0F      # 全开
python3 tools/plush_toy_test.py gesture-modes 0         # 恢复默认：不动
```

指的是「没人碰玩具时它自己动不动」—— 设备状态迁移与服务端下发的 emotion。NVS 键 `gesture_modes`，**默认 `0`**。

| 位 | 值 | 触发时机 | 手势 |
|---|---|---|---|
| 0 | 0x01 | 进入聆听 | 微微前倾 |
| 1 | 0x02 | 开始说话 | 轻摆一次 |
| 2 | 0x04 | 回到空闲 | 归中泄力 |
| 3 | 0x08 | 服务端 emotion | 按情绪映射 |

默认全关的理由（2026-09-11 实测观感）：一轮对话必然走 `Idle→Listening→Speaking→Idle` 三次迁移，服务端回复又几乎每次带 emotion，于是**每条指令都伴随四次手臂动作**。动作稀疏才显得有意图，每句都动等于没动，还平白耗电、给 I2C 总线添噪。

这一位掩码只管自发动作。触摸反射、摇晃反射和 MCP 手势工具都走各自的路径，不受它影响 —— 关掉之后玩具照样能被摸、被晃、被大模型指挥摆手。

### 触摸

```sh
python3 tools/plush_toy_test.py touch-modes 0x09        # 改响应掩码
python3 tools/plush_toy_test.py simulate-touch 0        # 伪造按下 ELE0
python3 tools/plush_toy_test.py simulate-touch 0 --release
```

`simulate-touch` 复用 `TouchController::ApplyTouchBits`，与真实触摸同一条路径，因此结果不依赖手指位置和力度。电极号取 0 到 11。

### 运动

```sh
python3 tools/plush_toy_test.py motion-modes 0x09       # 改响应掩码
python3 tools/plush_toy_test.py simulate-motion shake   # shake / upright / lying / inverted
```

`simulate-motion` 复用 `MotionController::ApplySample`，与真实轮询同一条路径。

**姿态类命令的结果活不过 300ms。** 伪造样本只是插队，真实 10Hz 轮询仍在并发喂当前重力方向，三帧确认（`MOTION_ORIENT_CONFIRM`）一满就把姿态翻回原样。因此**用 CLI 连发两条命令再读 `status`，永远只会看到初态** —— 一次 CLI 调用就要几百毫秒，窗口早关了。要观测必须在同一个进程里发完立刻高频轮询：

```python
post("simulate_motion", {"kind": "lying"})
seen = [orient() for _ in range(10)]   # 期望序列形如 [2,2,2,...,1,1]
```

看"峰值"而不是"终值"。终值回到竖立是对的，不是失败。

**竖立与倒置之间不能直接互跳。** 迟滞的前两个分支决定了中间必然经过侧躺，所以伪造 `inverted` 需要两段确认共六帧，命令内部已按 `MOTION_ORIENT_CONFIRM * 2` 连喂。真实翻动玩具也是这个过程，不是缺陷。

手动测真实传感器：把板子整个拿起来慢慢翻过来，盯着 `status` 的 `orientation` 从 1 变 2 再变 3，眼睛应跟着变 `sleepy` 再变 `surprised`；用力晃几下，眼睛应变 `confused` 并摆一次手。

**`orientation` 需要连续三帧一致才切换**，也就是翻过去后要停住约 0.3 秒才变。这是防坏样本加的迟滞，不是卡顿。

### 传感器响应掩码

触摸和运动各有一套掩码，位定义相同但**存在不同的 NVS 键**（`touch_modes` / `motion_modes`），因此可以单独关掉其中一类传感器。改完立即生效且重启保持。

| 位 | 值 | 模式 |
|---|---|---|
| 0 | 0x01 | 本地反射：直接改眼睛、动手臂 |
| 1 | 0x02 | 唤醒对话：进入聆听状态 |
| 2 | 0x04 | 上报大模型：作为一句话送给服务端 |
| 3 | 0x08 | 读值诊断：把原始计数放进 `status` |

两者默认都是 `0x09`。上报位与唤醒位是包含关系：上报走 `WakeWordInvoke`，本身带唤醒效果，两位同开不会触发两轮对话。

调试单条路径时，先只开要验的那一位，例如 `motion-modes 0x01` 只看本地反射。

### 完整回归

```sh
python3 tools/plush_toy_test.py run-regression
```

28 条，四组：

- **眼睛主题 6 条**，每条对应一种虹膜渲染路径：圆瞳浅巩膜、竖瞳暗巩膜、横瞳、无巩膜、照片纹理、日系画法。
- **手臂 5 条**：三个方向挥手、拥抱、欢呼。
- **情绪联动 6 条**，含 angry 这条「刻意不动作」的取舍：眼睛应变化而手臂必须不动。
- **触摸 4 条 + 运动 6 条**：各自先只开本地反射验证反应，再恢复诊断位。姿态按 竖→躺→倒→竖 走一圈。

**唤醒与上报两位不进回归** —— 它们会真的发起一轮对话，干扰后续用例。要验这两条得手动单独跑。

回归跑完仍需目视验收：舵机是否真的转动、眼睛是否切换。

## 触摸标定（MPR121）

**接线前先看这条：模块的 VCC 接 ESP32 的 3V3，不要接 5V。** 模块的 I2C 上拉电阻拉到自身 VCC，接 5V 会把 SDA(GPIO44) 与 SCL(GPIO3) 拉到 5V，超出 ESP32-S3 耐压；GPIO3 还是 JTAG_SEL 启动引脚。

MPR121 并入舵机那条 I2C（`I2C_NUM_0`），地址 0x5A，与 PCA9685 的 0x40 不冲突，不占用任何新引脚。引脚已用尽，IRQ 接不上，因此靠 50ms 轮询，去抖由芯片的 `DEBOUNCE` 寄存器完成。

阈值必须实机标定，`config.h` 里的出厂值只是猜测 —— 布料厚度和电极面积会显著改变触发点。用 `status` 读数标定（命令见「测试工具」一节）。

`status` 会带出 `touch_filtered` 与 `touch_baseline`。手指不碰时两者接近；手指贴上去时 `touch_filtered` 明显下降。记下这个差值，把约六成填进 `config.h` 的 `TOUCH_PRESS_THRESHOLD`，约三成填 `TOUCH_RELEASE_THRESHOLD`，然后重新烧录。

**释放阈值必须低于触摸阈值**，这是迟滞的来源。两者相等或反过来会让电极在临界点反复抖动，表现为一秒内几十次按下松开。

**接错脚和电极失效长得一模一样**，靠 `status` 的 `touch_all_filtered` 分辨：接了线的电极读数明显低于悬空的（2026-09-10 实测，接线的八路在 188 到 216，悬空的四路在 364 到 398）。

响应掩码与模拟触摸的用法见「测试工具」一节。

## 运动标定（MPU6050）

接线同样并入舵机那条 I2C，地址 0x68，不占新引脚：

```
MPU6050 (GY-521)      ESP32-S3
VCC  ──►  3V3      ← 模块虽标 3-5V，仍接 3V3，理由同 MPR121
GND  ──►  GND
SCL  ──►  GPIO3    ← 与 PCA9685、MPR121 同一节点
SDA  ──►  GPIO44   ← 与 PCA9685、MPR121 同一节点
AD0  ──►  GND 或悬空 ← 决定地址 0x68
INT / XDA / XCL ──► 不接
```

**总线上拉是接入它特有的风险。** GY-521 板载 4.7k 上拉，比 PCA9685 和 MPR121 的 10k 低一倍。三块板并联后总上拉约 2.4k。100kHz 下预期仍可工作，但若接入后出现 I2C 读写失败，或现有的触摸、舵机开始不稳，**第一件事是拆掉 GY-521 上那两颗上拉电阻**。

只读加速度计，不读陀螺仪：姿态由重力方向得出，摇晃由幅值判定，都不需要角速度。

标定同样靠 `status` 读数（命令见「测试工具」一节）。静置时三轴合矢量应接近 8192（1g，±4g 量程下）。玩具竖立时 `orientation` 应为 1；若读到 3（倒置），说明装配方向相反，**改 `config.h` 的 `MOTION_UP_AXIS_Z` 或轴符号，不要去改判定逻辑**。

竖直翻到倒置必然经过躺倒，会产生两个事件，这不是抖动。

**摇晃阈值要注意一个陷阱**：判定看的是合矢量对 1g 的偏离，因此**缓慢倾斜也会被记为命中** —— 例如静态停在 0.6g 时偏离已达 0.4g，超过默认阈值 0.35g，连续三次就会误判为摇晃。若发现搬动玩具时误报摇晃，调大 `MOTION_SHAKE_DELTA` 或调大 `MOTION_SHAKE_HITS`。

**总线坏读会污染标定。** 2026-09-10 实测坏帧率约 8.8%，典型坏样本是全 1 的字节。判定层已有防御：合矢量在 0.4g 到 5g 之外的整帧丢弃，姿态还要求连续三帧一致才切换，丢弃数记在 `status` 的 `motion_rejected`。**标定前先看这个数涨得快不快** —— 涨得快说明总线还没修好，此时标出来的阈值不可信。

**舵机自振会被加速度计读到**，因此动作执行期间及结束后 400ms 内摇晃判定被抑制（`LimbController::busy()`）。姿态判定不抑制，它看的是静态重力。验收时务必单独测这一条：触发一次手臂动作，确认**不**产生摇晃事件。

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
