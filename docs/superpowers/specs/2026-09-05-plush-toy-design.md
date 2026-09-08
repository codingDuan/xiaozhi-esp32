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
    float lid_tilt;      // 上眼睑倾角（度）      —— 生气/难过；右眼取负值
    float curve;         // 下眼睑曲率 -1~+1     —— 弯月笑眼 / 下垂难过眼
    uint16_t iris_color; // 虹膜颜色 RGB565      —— 情绪染色
};
```

情绪之间用线性插值过渡，天然平滑。两眼的 `pupil_x` 保留约 0.045 的不对称偏移，避免机械感。

渲染实现：圆屏本身即眼球轮廓，画三层同心圆（巩膜/虹膜/瞳孔）+ 双高光点，上下眼睑用带倾角的直线（上睑）与二次曲线（下睑）构成的路径裁切。

### 2.2.1 视觉原型结论（2026-09-06）

造型经交互式原型验证后定稿，原型对比了三种结构上不同的风格：A 写实圆眼（分层圆）、B 极简发光（Vector/Cozmo 式形变光块）、C 点阵像素。

**采纳风格 A（写实圆眼）。** 确认的中性基线参数：

```c
// neutral / 待机基线
EyeState kNeutral = {
    .openness = 0.94f, .pupil_x = 0.00f, .pupil_y = 0.00f,
    .pupil_scale = 1.00f, .lid_tilt = 0.0f, .curve = 0.00f,
    .iris_color = 0x363E,   // #35C7F5 青蓝
};
```

原型暴露的三条约束，均已并入上文结构体定义：

1. **原设计的 5 个参数不足**。弯月笑眼需要下眼睑向上拱起，仅靠 `openness` 与 `lid_tilt` 无法表达——降低 `openness` 只会让眼睛变成一条横缝而非笑眼。故新增第 6 个字段 `curve`。
2. **`lid_tilt` 必须左右镜像**。「内低外高」是相对鼻梁的方向，左眼取 `+t` 时右眼须取 `-t`。同号会使「生气」表现为整张脸歪向一侧。
3. **`pupil_scale` 在 240px 圆屏上区分度有限**。「惊讶」的实际视觉传达主要来自 `openness` 拉满后露出的上下眼白，而非瞳孔放大。因此情绪映射表中 `surprised` 须以 `openness = 1.0` 为主导，`pupil_scale` 仅作辅助。

各情绪的完整参数取值见原型（归档位置见第 8 节）。

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

两块眼屏**接管**原主屏的 SPI 总线（MOSI/CLK/DC/RST 并联共用，仅 CS 独立），因此只需新增一根 CS。实物模块无 BL 引脚（背光内部直连 VCC，常亮不可调），故 `DISPLAY_BACKLIGHT_PIN` 恒为 `GPIO_NUM_NC`，GPIO38 得以释放给 SPI 时钟。

| 用途 | 引脚 | 说明 |
|---|---|---|
| 眼屏 MOSI | GPIO 14 | 从 GPIO20 迁移（原 `LAMP_GPIO`） |
| 眼屏 CLK | GPIO 38 | 从 GPIO19 迁移（原背光脚） |
| 眼屏 DC | GPIO 47 | 沿用 |
| 眼屏 RST | GPIO 21 | 沿用 |
| 左眼 CS | GPIO 45 | 沿用原主屏 CS |
| 右眼 CS | GPIO 43 | 原 U0TXD |
| 舵机 I2C SDA | GPIO 44 | 排针丝印 `RX`；接 PCA9685 SDA |
| 舵机 I2C SCL | GPIO 3 | 接 PCA9685 SCL；总线为 `I2C_NUM_0`（见 4.1） |
| 备用 | GPIO 46 | 预留电池检测 / 触摸唤醒 |
| USB | GPIO 19/20 | **恢复原生 USB**，烧录与日志共用一根线 |
| 背光 | — | 模块无 BL 引脚，内部直连 VCC 常亮 |
| 摄像头 | GPIO 4–13, 15–18 | 保留不动 |

**将 SPI 从 GPIO19/20 迁走的理由**：本板 README 明确记载摄像头占用了 USB 的 19/20。若维持现状，固件初始化 SPI 时 USB 枚举即断开，`/dev/cu.usbmodem*` 消失，此后每次烧录须手动按住 BOOT 并复位，且查看日志需外接 USB-TTL 模块。迁移仅需修改 `config.h` 中的宏定义，SPI 经 GPIO 矩阵可映射任意引脚，无逻辑代码改动。

**舵机改由 PCA9685 驱动后的变化**：舵机不再占用 ESP32 的 GPIO 做 PWM，因此原方案中「舵机落在 strapping 脚上、需外接 10kΩ 下拉」的顾虑全部消失，那两个电阻不再需要。GPIO46 因此空出作为备用脚。GPIO43 仍作右眼 CS —— 它是 ROM 启动阶段的串口发送脚，开机瞬间会输出日志脉冲，喂给 CS 无害（无时钟即无法锁存）。

### 3.2 供电

**两路电源完全独立，唯一的连接是共地。**

```
Mac ──USB──► 开发板（供电 + 烧录 + 日志）
                  │
                 GND ──────┬───── 共地点  ★两路电源唯一的连接★
                           │
5V/2A 充电头 ──► 舵机 ×2 ───┘
   （不接开发板任何引脚）
      └── 1000µF 电解 + 0.1µF 陶瓷并联于舵机侧 5V-GND，贴近舵机端
```

四条硬性要求：

1. **开发板的 `5V` / `VIN` 引脚必须空置**。开发过程中板子由 USB 供电，若同时把充电头的 5V 接到该引脚，等同两个 5V 源并联对顶，电流会倒灌进主机 USB 口。部分开发板有防倒灌二极管，不可依赖。
2. **舵机 5V 不得取自开发板排针**。板载走线与 USB 口内阻无法承受 SG90 启动瞬间约 700mA 冲击，压降会触发 ESP32 brownout 重启。
3. **1000µF 电解电容为必需件**，位置贴近舵机接线端，用于吸收启动浪涌。缺失时极大概率出现"一动就重启"。
4. **必须共地**。否则 PWM 信号无参考电平，舵机剧烈抖动。

**屏的 VCC 接开发板 `3V3` 引脚，不接 5V。** 实物模块（见 3.3）未见稳压芯片，逻辑电平为 3.3V。两块屏含常亮背光约 100mA，板载 LDO 可承受。

### 3.3 接线图

实物屏模块为 7 针：`RST / CS / DC / SDA / SCL / GND / VCC`。**没有 BL 引脚**——背光在模块内部直连 VCC，上电常亮且无法调光。丝印的 `SDA` / `SCL` 是厂商习惯叫法，实际是 SPI 的 MOSI 与 SCK，不是 I2C。

```
        ESP32-S3 CAM 开发板
      ┌────────────────────┐
      │ GPIO14 ────────────┼──┬─────────────┐        Mac ──USB──► 板子供电
      │ GPIO38 ────────────┼──┼──┬──────────┼──┐        （5V/VIN 引脚空置）
      │ GPIO47 ────────────┼──┼──┼──┬───────┼──┼──┐
      │ GPIO21 ────────────┼──┼──┼──┼──┬────┼──┼──┼──┐
      │ GPIO45 ────────────┼──┼──┼──┼──┼─┐  │  │  │  │
      │ GPIO43 ────────────┼──┼──┼──┼──┼─┼──┼──┼──┼──┼─┐
      │ 3V3 ───────────────┼──┼──┼──┼──┼─┼──┼──┼──┼──┼─┼──┐
      │ GND ───────────────┼──┼──┼──┼──┼─┼──┼──┼──┼──┼─┼──┼──┬── ★共地★
      │                    │  ▼  ▼  ▼  ▼ ▼  ▼  ▼  ▼  ▼ ▼  ▼  │
      │                    │ SDA SCL DC RST CS       ...      │
      │                    │ ┌──────────────┐ ┌──────────────┐│
      │                    │ │   左 眼       │ │   右 眼       ││
      │                    │ │  GC9A01 1.28"│ │  GC9A01 1.28"││
      │                    │ │  CS ← GPIO45 │ │  CS ← GPIO43 ││
      │                    │ └──────────────┘ └──────────────┘│
      │                    │  SDA/SCL/DC/RST/VCC/GND 两屏并联  │
      │ GPIO46 ────────────┼──► 左手舵机 信号(橙)  ┐            │
      │ GPIO44 ────────────┼──► 右手舵机 信号(橙)  │            │
      │  （各串 10kΩ 下拉）  │                     │            │
      │ GPIO19/20 = USB ✅ │                     │            │
      └────────────────────┘                     │            │
                                                 │            │
        5V/2A 充电头 ──┬── +5V ──► 舵机红线 ×2 ───┘            │
        （不接开发板）  │      ┌── 1000µF ─┐                   │
                       │      ├── 0.1µF ──┤ 贴近舵机端          │
                       └── GND ────────────┴──► 舵机棕线 ×2 ────┘
```

### 3.4 元件清单

除舵机与屏外：PCA9685 16 路舵机驱动板 ×1、1000µF/10V 电解电容 ×1、0.1µF 瓷片电容 ×1、5V/2A 充电头 ×1、杜邦线若干。

（原清单中的 10kΩ 电阻 ×2 已不需要——那是 GPIO 直驱 PWM 时给舵机信号线做下拉用的，改用 PCA9685 后信号由其驱动。）

**舵机须为 180° 版本**。360° 连续旋转舵机内部无位置反馈，PWM 输入对应转速而非角度，无法用于肢体定位，且无软件补救办法。

SG90 为塑料齿。毛绒布料的持续回弹力是打齿主因，故固件层面强制两项保护（见 4.4）。

---

## 4. 固件设计

### 4.1 资源冲突：I2C 端口（LEDC 冲突已因改用 PCA9685 而消失）

#### 已消失的冲突：LEDC 通道

早期设计由 ESP32 的 LEDC 直接产生舵机 PWM，会与摄像头 XCLK 争抢 `LEDC_CHANNEL_0`
（`managed_components/espressif__esp32-camera/target/xclk.c:24,33,49`）。
改用 PCA9685 后，PWM 由其自带振荡器产生，**ESP32 一个 LEDC 通道都不占**，该冲突不复存在。

#### 实际存在的冲突：I2C 端口（2026-09-07 实机发现）

**摄像头 SCCB 占用的是 `I2C_NUM_1`，不是 `I2C_NUM_0`。** 因此 PCA9685 必须走 `I2C_NUM_0`。

判定依据必须看 Kconfig，**不能看板级代码里的 `camera_config_t.sccb_i2c_port` 赋值**——那是个死字段：

- `managed_components/espressif__esp32-camera/driver/sccb-ng.c:123`：
  `sccb_i2c_port = SCCB_I2C_PORT_DEFAULT;` 无条件覆盖传入值
- `sccb-ng.c:40-44`：`SCCB_I2C_PORT_DEFAULT` 由 `CONFIG_SCCB_HARDWARE_I2C_PORT1` 决定
- 本工程 `sdkconfig` 中该选项为 `y`，启动日志印证：`sccb-ng: sccb_i2c_port=1`

`bread-compact-wifi-s3cam` 里那行 `config.sccb_i2c_port = 0;` 不起任何作用，照抄它会得出错误结论。

**防护**：`main/boards/plush-toy/plush_toy_board.cc` 中以 `static_assert` 钉死该约束，
两者撞车时编译期即报错。该断言已验证会正确触发。

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

| emotion | 眼睛（关键参数） | 手势 |
|---|---|---|
| `happy` | `openness .62`, `curve +.85` 弯月眼 | 雀跃 |
| `laughing` | `openness .34`, `curve +1.0` | 雀跃 |
| `sad` | `openness .58`, `lid_tilt +19`, `curve -.4` | 双手下垂 |
| `angry` | `openness .68`, `lid_tilt -27`, `curve -.25` | 静止（不动更具张力） |
| `surprised` | `openness 1.0`（主导）, `pupil_scale 1.45`（辅助） | 双手上举 |
| `thinking` | `pupil_x -.62`, `pupil_y -.4` 视线上移 | 静止 |
| `sleepy` | `openness .18`, `pupil_y +.25` | 静止泄力 |

`lid_tilt` 一栏为左眼取值，右眼取其负值。完整 21 种映射表存 NVS `Settings`（`main/settings.h`），支持在线调整。

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

1. ~~`espressif/qrcode` 组件在当前 ESP-IDF 版本下的可用性；不可用则自行实现最小二维码编码器。~~ —— **已解决**（2026-09-08）。最终 vendored Nayuki qrcodegen（MIT、纯 C99），由 `OverlayQr` 封装；固件实际编码与渲染输出已被 macOS Vision 精确回读原始 Wi-Fi 载荷，不再依赖 ESP-IDF 的二维码组件。
2. ~~SPI 在 20MHz 下双屏并联的实际稳定性，必要时降至 10MHz。~~ —— **不再上探**（2026-09-08）。10MHz 已在面包板双屏并联条件下实机稳定，按条交错后双眼理论最大时差约 6ms；用户接受当前表现并要求停止专项排查。除非以后重新观察到可见卡顿或错位，否则保持 10MHz。
3. ~~emoji 是否被 TTS 朗读~~ —— **已验证解决**（2026-09-07）。`get_string_no_punctuation_or_emoji()`（`textUtils.py:41`）能正确剥离首尾 emoji，实测 `'🙂 你好呀' → '你好呀'`、`'我很开心😍' → '我很开心'`，不会被念出来。
4. ~~GC9A01 的 `0x28`（DISPOFF）指令效果~~ —— **已作废**。实物模块背光不可控，DISPOFF 只让面板内容空白而背光仍亮，会得到两个发光的空白圆盘，比睁眼更糟。"闭眼睡觉"改为直接渲染 `openness = 0`（全黑画面），视觉等效且无需额外指令，该能力已在 `EyeRenderer` 中具备。

上述选择均已在实现中落地；二维码真屏扫码、OTA 进度和联网行为仍按计划文档中的硬件验收项继续跟踪。

---

## 8. 视觉原型归档

眼睛造型经交互式原型确定（见 2.2.1）。原型为一次性代码，按约定不进主干：

- **原型分支**：`prototype/eye-renderer`（仅含单个 HTML 文件）
- **在线版本**：https://claude.ai/code/artifact/2311c609-11f5-4db8-9f08-0b5bcfa5824b
- **回答的问题**：三种眼睛风格中哪种适合 1.28" 圆屏上的毛绒玩具，以及 `EyeState` 各字段的合理取值范围
- **结论**：采纳风格 A（写实圆眼）；新增 `curve` 字段；确认 `lid_tilt` 须左右镜像

原型页面内含全部 10 种情绪预设的参数、插值过渡演示与眨眼/游走动画，实现 C++ 版 `eye_renderer` 时以其为参照。
