# 毛绒玩具改造设计方案

**日期**：2026-09-05
**目标硬件**：ESP32-S3 面包板开发板（带 OV2640 摄像头），当前板型 `bread-compact-wifi-s3cam`
**新增外设**：SG90 180° 舵机 ×2（左右手）、GC9A01 1.28" 圆形 TFT ×2（左右眼）
**服务端**：自建 `xiaozhi-esp32-server`（本地路径 `~/Workspace/xiaozhi-esp32-server`）

---

## 1. 目标与范围

把现有的小智 ESP32-S3 语音助手装进毛绒玩具，具备两项新的物理表达能力：

- **肢体动作**：两个舵机驱动左右手臂
- **眼部表情**：两块圆形 TFT 各显示一只眼睛

原有的 240×320 主显示屏**移除**，其调试文本输出改由串口日志承担。

### 明确不在本期范围内

- 音频波形驱动的口型/节奏同步
- 双眼独立注视目标的辐辏计算
- 舵机动作序列自编程（otto-robot 的 `ACTION_SERVO_SEQUENCE`）
- 电池供电（本期为 USB 5V 带线）

---

## 2. 架构决策

### 2.1 动作触发架构：本地反射 + LLM 点缀

评估过三种触发方式：

| 方案 | 描述 | 否决理由 |
|---|---|---|
| A. 纯 LLM 驱动 | 全部动作由云端 LLM 调 MCP 工具触发（otto-robot 的做法） | 每个动作等一轮 LLM 推理，延迟 1–3 秒；LLM 常忘记调用，动作稀疏 |
| B. 服务端插件驱动 | 服务端在 TTS 前根据情绪下发动作指令 | 仍有网络往返延迟；多维护一套 |
| **C. 本地反射 + LLM 点缀** | 见下 | **采纳** |

**采纳 C 的理由**：毛绒玩具的核心体验是即时的物理回应，A 和 B 都被网络往返判死。C 把动作分三类：

1. **反射类**（设备本地，零延迟，断网可用）：由设备状态机驱动。待机呼吸眨眼、聆听时定睛前倾、说话时手臂轻摆。
2. **情绪类**（复用现有 `emotion` 通道，服务端零改动）：`SetEmotion()` 同时驱动眼睛参数和对应手势。
3. **意图类**（LLM 显式调用）：仅暴露 3 个 MCP 工具，用于"跟我招手""抱抱我"这类明确指令。

代价是动作策略烧在固件里。缓解措施：情绪→动作映射表存 NVS `Settings`，可在线调整而不重烧。

### 2.2 眼睛渲染：参数化直绘，不用 LVGL

otto-robot 走 LVGL + 预制 GIF（`main/boards/otto-robot/otto_emoji_display.cc:59`）。本项目不采用，三个理由：

1. LVGL 的 display 对象与单块 panel 一对一绑定，双屏需双份缓冲与刷新任务，而摄像头还要占 VGA 帧缓冲。
2. GIF 是固定帧序列。眨眼需随机触发、瞳孔需微动、情绪间需平滑过渡——这些是**参数**而非帧，用 GIF 会组合爆炸。
3. 眼睛不需要控件、布局、事件，LVGL 的能力一项都用不上。

改为参数化直绘，全部表情由一个结构体描述：

```c
struct EyeState {
    float openness;      // 0.0 全闭 ~ 1.0 全睁   —— 眨眼、困倦
    float pupil_x, pupil_y;  // 瞳孔偏移 -1.0~1.0  —— 注视方向、走神
    float pupil_scale;   // 瞳孔缩放             —— 惊讶放大、厌恶缩小
    float lid_tilt;      // 上眼睑倾角           —— 生气/难过
    uint16_t iris_color; // 虹膜颜色             —— 情绪染色
};
```

情绪之间用线性插值过渡，天然平滑。两眼的 `pupil_x` 保留轻微不对称，避免机械感。

渲染实现：圆屏本身即眼球轮廓，画三层同心圆（巩膜/虹膜/瞳孔）+ 高光点，上下眼睑用填充弧形覆盖。整数运算，单帧耗时毫秒级。

### 2.3 显示双模态

```
EyeDisplay
 ├── kModeEyes    : 按 EyeState 绘制眼球（默认）
 └── kModeOverlay : 铺满 1-bit 位图（配网二维码 / OTA 进度 / 错误码）
```

Overlay 模式补上了移除主屏后的信息缺口。`SetChatMessage` / `SetStatus` **不重写**，落到 `main/display/display.cc:31-37` 的基类默认实现，自动输出到串口日志——这就是调试通道。

### 2.4 配网提示：二维码而非文字

移除主屏后，配网提示（`main/boards/common/wifi_board.cc:181-187`）失去显示载体。

排除的方案：复用 `main/display/text_glyph.h` 的字形数据。该结构虽含 `bitmap` 光栅数据，但字形由服务端经 `text_glyph_payload` 下发，**配网时设备尚未联网，服务端不可达**。设备本地无字体光栅化器。

采纳方案：**左眼**渲染内容为 `WIFI:S:<ssid>;T:nopass;;` 的二维码，**右眼**同时显示一个静态"待配网"图标（避免一只眼漆黑造成"是不是坏了"的误判）。用户手机相机扫描后系统直接弹出"加入网络"，无需辨认字符、无需手动翻 WiFi 列表。这比原主屏显示一行小字**体验更好**。

可行性核算：240px 直径圆屏的内接正方形边长约 170px；Version 3 二维码 29×29 模块按 5px/模块渲染为 145px，含静默区可容纳，手机可扫。不需要字体，只需二维码编码器。

语音提示（`Lang::Sounds::OGG_WIFICONFIG`）本就存在，作为二维码的补充始终保留。

---

## 3. 硬件设计

### 3.1 引脚分配

ESP32-S3 在本板上的约束：`CONFIG_SPIRAM_MODE_OCT=y`，GPIO33–37 被八线 PSRAM 占用；GPIO26–32 为 SPI Flash；摄像头占用 GPIO4–13、15–18。

已核实 `~/.espressif/v6.1/esp-idf/components/soc/esp32s3/include/soc/soc_caps.h:195`：`SOC_GPIO_VALID_OUTPUT_GPIO_MASK == SOC_GPIO_VALID_GPIO_MASK`，ESP32-S3 无只读引脚，GPIO46 可作输出。

两块眼屏**接管**原主屏的 SPI 总线（MOSI/CLK/DC/RST 并联共用，仅 CS 独立），因此只需新增一根 CS。背光走常亮方案，释放 GPIO38。

| 用途 | 引脚 | 说明 |
|---|---|---|
| 眼屏 MOSI | GPIO 14 | 从 GPIO20 迁移（原 `LAMP_GPIO`） |
| 眼屏 CLK | GPIO 38 | 从 GPIO19 迁移（原背光脚） |
| 眼屏 DC | GPIO 47 | 沿用 |
| 眼屏 RST | GPIO 21 | 沿用 |
| 左眼 CS | GPIO 45 | 沿用原主屏 CS |
| 右眼 CS | GPIO 43 | 原 U0TXD |
| 左手舵机 | GPIO 46 | strapping，内部默认下拉 → 开机即安全低电平；仍建议外接 10kΩ 下拉作冗余 |
| 右手舵机 | GPIO 44 | 原 U0RXD，非 strapping；**必须**外接 10kΩ 下拉压掉内部上拉 |
| 备用 | GPIO 3 | 预留电池检测 / 触摸唤醒 |
| USB | GPIO 19/20 | **恢复原生 USB**，烧录与日志共用一根线 |
| 背光 | — | 两屏 BL 直接接 3V3 常亮 |
| 摄像头 | GPIO 4–13, 15–18 | 保留不动 |

**将 SPI 从 GPIO19/20 迁走的理由**：本板 README 明确记载摄像头占用了 USB 的 19/20。若维持现状，固件初始化 SPI 时 USB 枚举即断开，`/dev/cu.usbmodem*` 消失，此后每次烧录须手动按住 BOOT 并复位，且查看日志需外接 USB-TTL 模块。迁移仅需修改 `config.h` 中的宏定义，SPI 经 GPIO 矩阵可映射任意引脚，无逻辑代码改动。

**舵机避开 GPIO43 的理由**：GPIO43 是 ROM 启动阶段的串口发送脚，开机瞬间会输出日志脉冲。喂给舵机会导致上电抽搐；喂给 CS 则无害（无时钟即无法锁存）。

### 3.2 供电

```
5V/2A 充电头
   ├──► 开发板 5V 引脚（ESP32-S3 + 两屏 3V3）
   └──► 舵机红线 ×2（电源处直接分叉，不经开发板排针）
          └── 并联 1000µF 电解 + 0.1µF 陶瓷，贴近舵机端
GND ──► 舵机棕线 ×2 + 开发板 GND + 电容负极（必须共地）
```

三条硬性要求：

1. **舵机 5V 不得取自开发板排针**。板载走线与 USB 口内阻无法承受 SG90 启动瞬间约 700mA 冲击，压降会触发 ESP32 brownout 重启。
2. **1000µF 电解电容为必需件**，位置贴近舵机接线端，用于吸收启动浪涌。缺失时极大概率出现"一动就重启"。
3. **必须共地**。否则 PWM 信号无参考电平，舵机剧烈抖动。

### 3.3 接线图

```
        ESP32-S3 CAM 开发板                    5V/2A 充电头
      ┌────────────────────┐                    │
      │ GPIO14  MOSI ──────┼──┬──────────────┐  ├──► 开发板 5V
      │ GPIO38  CLK  ──────┼──┼──┬───────────┼──┤
      │ GPIO47  DC   ──────┼──┼──┼──┬────────┼──┤   └──► 舵机红线 ×2
      │ GPIO21  RST  ──────┼──┼──┼──┼──┬─────┼──┘
      │ GPIO45  CS ────────┼──┼──┼──┼──┼─┐   │
      │ GPIO43  CS ────────┼──┼──┼──┼──┼─┼─┐ │  ┌── 1000µF ─┐
      │                    │  │  │  │  │ │ │ │  ├── 0.1µF ──┤
      │ GPIO46 ────────────┼──┼──┼──┼──┼─┼─┼─┼──┼──► 左手舵机 信号(橙)
      │ GPIO44 ────────────┼──┼──┼──┼──┼─┼─┼─┼──┼──► 右手舵机 信号(橙)
      │   （各串 10kΩ 下拉）│  │  │  │  │ │ │ │  │
      │ GND ───────────────┼──┼──┼──┼──┼─┼─┼─┴──┴──► 舵机棕线 ×2  ★共地★
      │ 3V3 ───────────────┼──┼──┼──┼──┼─┼─┼────► 两屏 VCC + BL(常亮)
      │ GPIO19/20 = USB ✅ │  │  │  │  │ │ │
      └────────────────────┘  ▼  ▼  ▼  ▼ ▼ ▼
                          ┌──────────┐ ┌──────────┐
                          │  左眼     │ │  右眼     │
                          │ GC9A01   │ │ GC9A01   │
                          │ 1.28" 圆 │ │ 1.28" 圆 │
                          │ CS←GPIO45│ │ CS←GPIO43│
                          └──────────┘ └──────────┘
```

### 3.4 元件清单

除舵机与屏外：1000µF/10V 电解电容 ×1、0.1µF 瓷片电容 ×1、10kΩ 电阻 ×2、5V/2A 充电头 ×1、杜邦线若干。

**舵机须为 180° 版本**。360° 连续旋转舵机内部无位置反馈，PWM 输入对应转速而非角度，无法用于肢体定位，且无软件补救办法。

SG90 为塑料齿。毛绒布料的持续回弹力是打齿主因，故固件层面强制两项保护（见 4.4）。

---

## 4. 固件设计

### 4.1 必须先修复的资源冲突：LEDC 通道

- `managed_components/espressif__esp32-camera/target/xclk.c:24,33,49`：摄像头 XCLK 由 LEDC 生成，走 `LEDC_LOW_SPEED_MODE`，定时器与通道取自 `config->ledc_timer` / `config->ledc_channel`。
- `main/boards/bread-compact-wifi-s3cam/compact_wifi_board_s3cam.cc:128`：`camera_config_t config = {};` 零初始化后未赋值这两个字段，实际使用 `LEDC_TIMER_0` + `LEDC_CHANNEL_0`。
- `main/boards/otto-robot/oscillator.cc:21`：`static ledc_channel_t next_free_channel = LEDC_CHANNEL_0;`

直接移植舵机代码会导致**第一个舵机覆盖摄像头的 XCLK 通道**。表现为摄像头花屏或超时，而错误信息完全指向不到舵机。

修复（两处均改）：

1. 板级代码显式声明摄像头占用：`config.ledc_timer = LEDC_TIMER_0; config.ledc_channel = LEDC_CHANNEL_0;`（不改变行为，将隐式默认转为显式声明）
2. 舵机通道分配起点改为 `LEDC_CHANNEL_2`；定时器沿用 `LEDC_TIMER_1`（50Hz，与摄像头的 20MHz 定时器互不干扰）

背光走常亮方案后 `PwmBacklight` 不会实例化，少一个 LEDC 竞争者。

### 4.2 模块划分

新建 `main/boards/plush-toy/`（仓库为一板一目录结构，新增目录不影响现有板型）：

| 文件 | 职责 | 依赖 |
|---|---|---|
| `config.h` / `config.json` | 引脚与编译选项 | — |
| `plush_toy_board.cc` | 板型装配：音频、摄像头、双屏 SPI、按键 | 全部 |
| `eye_renderer.h/.cc` | **纯计算**：`EyeState` → 像素缓冲 | 无硬件依赖 |
| `eye_display.h/.cc` | `Display` 子类，双模态，驱动两块 panel | eye_renderer, esp_lcd |
| `overlay_qr.h/.cc` | 字符串 → 二维码位图 | 无硬件依赖 |
| `limb_controller.h/.cc` | 舵机动作层 | oscillator |
| `oscillator.h/.cc` | 自 otto-robot 复制（改通道起点） | LEDC |
| `plush_behavior.h/.cc` | 反射协调器 + MCP 工具注册 | 以上全部 |

**边界设计要点**：`eye_renderer` 与 `overlay_qr` 均为不接触硬件的纯函数模块，输入参数输出像素。二者可在开发机上编译为单元测试，将渲染结果导出为图片肉眼检查，无需烧录固件即可迭代眼球造型参数——该部分是全项目最需反复调参的环节。

### 4.3 资源核算

**内存**：单块 240×240 RGB565 全帧 = 115KB。两眼**共用一个 PSRAM 缓冲区**（渲染左眼 → blit 左屏 → 渲染右眼 → blit 右屏），峰值占用 115KB PSRAM。摄像头 VGA 帧缓冲同在 PSRAM，8MB 容量下二者无压力。

**SPI 带宽（关键约束）**：现有板型使用 `pclk_hz = 40MHz`。本项目为面包板 + 杜邦线 + 两屏并联负载，40MHz 在此走线条件下极易出现花屏或总线死锁。**必须降至 20MHz，建议自 10MHz 调通后再上调。**

20MHz ≈ 2.5MB/s。单眼全屏重绘 115KB → 46ms，双眼 → 92ms，仅 11fps。

**因此脏矩形刷新是必需项而非优化项**：巩膜静止，逐帧变化的仅瞳孔与眼睑。只重绘变化区域（约 100×100 = 20KB），双眼合计约 16ms，可稳定 30fps。眨眼时眼睑扫过区域较大，但持续仅 150ms，瞬时掉帧可接受。

此约束须在第一版架构中即体现；若按全屏重绘实现，运行结果会是幻灯片，且容易被误判为方案本身不可行。

### 4.4 舵机动作层

复制 `main/boards/otto-robot/oscillator.cc`（`electron-bot` 亦采用复制方式，符合仓库惯例），改动两处：通道起点改 `LEDC_CHANNEL_2`；行程限制 ±30°。

手势由「振幅 + 周期 + 相位差」三参数描述，直接对应 `oscillator.h:37-40` 的 `SetA/SetO/SetPh/SetT` 原生接口，无需自行实现插值：

| 手势 | 参数 |
|---|---|
| 挥手 | 单侧，振幅 25°，周期 400ms，重复 3 次 |
| 拥抱 | 双侧同相位张开至 +30° 并保持 |
| 雀跃 | 双侧反相位，振幅 15°，周期 250ms |

**塑料齿保护（硬性约束）**：

1. 动作结束后 200ms 调用 `Oscillator::Detach()`（`oscillator.h:35`，底层为 `ledc_stop`）主动断开 PWM 使舵机泄力。长期顶住毛绒布料堵转是打齿首因。
2. 动作队列**串行化**，同一时刻仅一个手势执行。手势叠加会产生超出机械限位的合成角度。

### 4.5 反射协调器

**挂钩点选择**：`main/application.cc:247` 与 `:916` 存在 `led->OnStateChanged()` 回调，但将玩具行为伪装为 `Led` 语义别扭。改用 `main/application.h:68` 的 public `GetDeviceState()`。

`PlushBehavior` 自建 50Hz FreeRTOS 任务——该任务本就必需（`Oscillator::Refresh()` 需周期调用）。在同一 tick 内读取设备状态即可发现状态变化。**零核心代码改动。**

**链路 ① 设备状态 → 待机神态**（本地，零延迟，断网可用）

| 状态 | 眼睛 | 肢体 |
|---|---|---|
| `kDeviceStateIdle` | 呼吸式微眨 + 随机 3~7s 眨眼 + 瞳孔缓慢游走 | 静止泄力 |
| `kDeviceStateListening` | `openness=1.0`，瞳孔居中定睛 | 双手前倾 15° |
| `kDeviceStateSpeaking` | 瞳孔随节奏微动 | 双手反相位轻摆 |
| `kDeviceStateConnecting` | 瞳孔转圈 | 静止 |
| `kDeviceStateWifiConfiguring` | Overlay 模式，显示二维码 | 静止 |
| `kDeviceStateUpgrading` | Overlay 模式，进度环 | 静止 |

**链路 ② emotion → 表情 + 手势**（复用现成通道）

`main/application.cc:602-606` 已将服务端下发的 `{"type":"llm","emotion":...}` 直通至 `display->SetEmotion()`。重写 `SetEmotion` 使其同时切换眼睛参数与触发对应手势：

| emotion | 眼睛 | 手势 |
|---|---|---|
| `happy` | 弯月眼 | 雀跃 |
| `sad` | `lid_tilt` 内高外低 | 双手下垂 |
| `surprised` | 瞳孔放大 1.4× | 双手上举 |
| `angry` | `lid_tilt` 内低外高 | 静止（不动更具张力） |

完整映射表存 NVS `Settings`（`main/settings.h`），支持在线调整。

**链路 ③ MCP 工具**（LLM 显式调用）

仅暴露 3 个（otto-robot 暴露 28 个，工具过多会降低 LLM 选择准确率），经 `main/mcp_server.cc:311` 的 `AddTool()` 注册：

```
self.limbs.wave_hand   { side: "left"|"right"|"both", times: 1-5 }
self.limbs.hug         {}
self.eyes.look_at      { direction: "left"|"right"|"up"|"down"|"center" }
```

---

## 5. 服务端设计

`xiaozhi-esp32-server` **无需修改任何代码**：

- **MCP 工具**：`core/providers/tools/device_mcp/` 自动发现设备端注册的工具并提供给 LLM，无需服务端注册。
- **emotion 下发**：`core/utils/textUtils.py:84` 的 `get_emotion()` 已在每轮回复时推送 `{"type":"llm","emotion":...}`。

### 唯一必需的配置项：角色 prompt

`get_emotion()` 的实现（`core/utils/textUtils.py:84-95`）通过**扫描 LLM 回复文本中的 emoji 字符**来判定情绪，默认值为 `"happy"`：

```python
emotion = "happy"          # 默认值
for char in text:
    if char in EMOJI_MAP:
        emotion = EMOJI_MAP[char]
        break
```

**若 LLM 回复不含 emoji，`emotion` 恒为 `"happy"`**，玩具将始终保持同一表情。该失败模式极难排查——设备端代码与链路均正常，仅表情不变。

因此角色 prompt 必须要求 LLM 每次回复携带一个 emoji，且限定在 `EMOJI_MAP`（`textUtils.py:8-30`）支持的 21 种之内：

`😂funny 😭crying 😠angry 😔sad 😍loving 😲surprised 😱shocked 🤔thinking 😌relaxed 😴sleepy 😜silly 🙄confused 😶neutral 🙂happy 😆laughing 😳embarrassed 😉winking 😎cool 🤤delicious 😘kissy 😏confident`

Prompt 须明确三点：① 每次回复开头放一个 emoji；② 只从上述 21 个中选择；③ 何时调用 `wave_hand` / `hug` 等工具。

**待实现阶段验证**：emoji 是否会被送入 TTS 而被朗读。`get_string_no_punctuation_or_emoji()`（`textUtils.py:41`）负责剥离，需实测确认该链路生效。

---

## 6. 移除主屏的已知影响

| 影响 | 处理 |
|---|---|
| 配网引导文字 | 改为二维码（见 2.4）+ 现有语音播报 |
| OTA 升级进度 | Overlay 模式进度环 + 串口日志 |
| 聊天文本 / 状态栏 | 串口日志（基类默认实现，零改动） |
| 摄像头拍照预览 | **不予恢复**。摄像头用途为服务端视觉问答，本地预览无价值 |

附带收益：不再需要 LVGL 与 emoji 图片资源，节省的 flash 与 PSRAM 供摄像头帧缓冲使用，缓解了同时保留摄像头与双屏的内存压力。

---

## 7. 待验证事项

以下项需在实现阶段确认，不阻塞设计定稿：

1. `espressif/qrcode` 组件在当前 ESP-IDF 版本下的可用性；不可用则自行实现最小二维码编码器。
2. SPI 在 20MHz 下双屏并联的实际稳定性，必要时降至 10MHz。
3. emoji 是否被 TTS 朗读（见第 5 节）。
4. GC9A01 的 `0x28`（DISPOFF）指令在本模块上的实际效果——用于实现"闭眼睡觉"，替代已取消的背光 PWM 调光。
