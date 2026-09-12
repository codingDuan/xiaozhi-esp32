#ifndef _BOARD_CONFIG_H_
#define _BOARD_CONFIG_H_

#include <driver/gpio.h>
#include <driver/i2c_types.h>

#define AUDIO_INPUT_SAMPLE_RATE  16000
#define AUDIO_OUTPUT_SAMPLE_RATE 24000

// 如果使用 Duplex I2S 模式，请注释下面一行
#define AUDIO_I2S_METHOD_SIMPLEX

#define AUDIO_I2S_MIC_GPIO_WS   GPIO_NUM_1
#define AUDIO_I2S_MIC_GPIO_SCK  GPIO_NUM_2
#define AUDIO_I2S_MIC_GPIO_DIN  GPIO_NUM_42
#define AUDIO_I2S_SPK_GPIO_DOUT GPIO_NUM_39
#define AUDIO_I2S_SPK_GPIO_BCLK GPIO_NUM_40
#define AUDIO_I2S_SPK_GPIO_LRCK GPIO_NUM_41

#define BUILTIN_LED_GPIO        GPIO_NUM_48
#define BOOT_BUTTON_GPIO        GPIO_NUM_0
#define TOUCH_BUTTON_GPIO       GPIO_NUM_NC
#define VOLUME_UP_BUTTON_GPIO   GPIO_NUM_NC
#define VOLUME_DOWN_BUTTON_GPIO GPIO_NUM_NC

// ── 摄像头：沿用 bread-compact-wifi-s3cam，引脚不变 ──
#define CAMERA_PIN_D0    GPIO_NUM_11
#define CAMERA_PIN_D1    GPIO_NUM_9
#define CAMERA_PIN_D2    GPIO_NUM_8
#define CAMERA_PIN_D3    GPIO_NUM_10
#define CAMERA_PIN_D4    GPIO_NUM_12
#define CAMERA_PIN_D5    GPIO_NUM_18
#define CAMERA_PIN_D6    GPIO_NUM_17
#define CAMERA_PIN_D7    GPIO_NUM_16
#define CAMERA_PIN_XCLK  GPIO_NUM_15
#define CAMERA_PIN_PCLK  GPIO_NUM_13
#define CAMERA_PIN_VSYNC GPIO_NUM_6
#define CAMERA_PIN_HREF  GPIO_NUM_7
#define CAMERA_PIN_SIOC  GPIO_NUM_5
#define CAMERA_PIN_SIOD  GPIO_NUM_4
#define CAMERA_PIN_PWDN  GPIO_NUM_NC
#define CAMERA_PIN_RESET GPIO_NUM_NC
#define XCLK_FREQ_HZ     20000000

// ── 双眼屏（GC9A01 1.28" 240x240 ×2）──
// MOSI/CLK 已从 GPIO20/19 迁走，把原生 USB 还给烧录与日志。
// 实物模块 7 针 RST/CS/DC/SDA/SCL/GND/VCC，无 BL 引脚（背光内部常亮）。
// 模块丝印的 SDA/SCL 即 SPI 的 MOSI/CLK，不是 I2C。
#define DISPLAY_BACKLIGHT_PIN GPIO_NUM_NC   // 模块无 BL 引脚
#define DISPLAY_MOSI_PIN      GPIO_NUM_14   // 屏丝印 SDA
#define DISPLAY_CLK_PIN       GPIO_NUM_38   // 屏丝印 SCL
#define DISPLAY_DC_PIN        GPIO_NUM_47
#define DISPLAY_RST_PIN       GPIO_NUM_21
#define DISPLAY_CS_LEFT_PIN   GPIO_NUM_45
#define DISPLAY_CS_RIGHT_PIN  GPIO_NUM_46   // 原为 GPIO43(丝印TX)，但那是控制台 TX：
                                            // esp_lcd 占用该脚后串口日志立刻变乱码，
                                            // 实测确认。改用最后一个备用脚 GPIO46。

#define DISPLAY_SPI_HOST      SPI3_HOST
// 面包板飞线 + 双屏并联，先跑通再提速；上限 20MHz
//
// 眨眼的脏矩形 204x204、双眼合计 166KB，帧时长就是传输时长，10MHz 下一帧 133ms，
// 肉眼是慢动作。20MHz 实测干净无花点，再提到 40MHz —— SPI3 在 S3 上没有 IOMUX，
// 走 GPIO matrix 的硬上限就是 40MHz，到顶了。一帧降到 33ms，五帧眨眼约 200ms。
// 若屏上出现花点、撕裂或颜色错位，退回 20MHz（已实测稳定）。
#define DISPLAY_PCLK_HZ       (40 * 1000 * 1000)

// GC9A01 240x240 圆屏，硬编码不走 Kconfig 的 DISPLAY_LCD_TYPE choice
// （那个 choice 绑死在特定板型上，改它的依赖列表会污染其他板）
#define DISPLAY_WIDTH        240
#define DISPLAY_HEIGHT       240
#define DISPLAY_MIRROR_X     true
#define DISPLAY_MIRROR_Y     false
#define DISPLAY_SWAP_XY      false
#define DISPLAY_INVERT_COLOR true
#define DISPLAY_RGB_ORDER    LCD_RGB_ELEMENT_ORDER_BGR
#define DISPLAY_OFFSET_X     0
#define DISPLAY_OFFSET_Y     0
#define DISPLAY_SPI_MODE     0

// ── 舵机：经 PCA9685 驱动，ESP32 不直接产生 PWM ──
// 引脚与地址为 2026-09-07 实机验证所得，非推算。
//
// 端口选择必须看 Kconfig，不能看 camera_config_t.sccb_i2c_port —— 后者是死字段：
// sccb-ng.c:123 无条件用 SCCB_I2C_PORT_DEFAULT 覆盖它，而该常量由
// CONFIG_SCCB_HARDWARE_I2C_PORT1 决定（sccb-ng.c:40-44）。
// 本工程该选项为 y，即摄像头占 I2C_NUM_1，故舵机走 I2C_NUM_0。
// plush_toy_board.cc 中有 static_assert 守住这个约束。
#define SERVO_I2C_SDA_PIN    GPIO_NUM_44   // 排针丝印 RX
#define SERVO_I2C_SCL_PIN    GPIO_NUM_3
#define SERVO_I2C_PORT       I2C_NUM_0
#define SERVO_I2C_HZ         100000
#define PCA9685_ADDR         0x40          // 实测；0x70 是同一芯片的 ALLCALL 广播地址

// 装配时哪只舵机接 CH0，哪只就是左手；发现装反了对调这两行即可
#define SERVO_LEFT_CHANNEL   0
#define SERVO_RIGHT_CHANNEL  1

// SG90：500us→-90°，2500us→+90°
#define SERVO_MIN_PULSE_US   500
#define SERVO_MAX_PULSE_US   2500
#define SERVO_PWM_FREQ_HZ    50
// 塑料齿保护 + 毛绒布料回弹力，工作行程限制在 ±30°（实测无卡滞）
#define SERVO_MAX_ANGLE      30

// ── 触摸：MPR121 并入舵机那条 I2C，不占新引脚 ──
// 引脚已用尽（26-32 是 flash，33-37 被八线 PSRAM 占用），IRQ 无处可接，
// 因此只能轮询。去抖交给芯片的 DEBOUNCE 寄存器(0x5B)，不在软件里做第二重。
//
// 模块 VCC 必须接 3V3。它的 I2C 上拉拉到自身 VCC，接 5V 会把 SDA(GPIO44) 与
// SCL(GPIO3) 拉到 5V，超出耐压；GPIO3 还是 JTAG_SEL 启动脚。
#define MPR121_ADDR              0x5A          // ADDR 接地时的默认地址
#define TOUCH_POLL_INTERVAL_MS   50
#define TOUCH_HEAD_ELECTRODE     0             // 本期只接头部一个电极
#define TOUCH_ELECTRODE_COUNT    12
// 出厂猜测值，必须实机标定后回填。标定方法见 README「触摸标定」。
#define TOUCH_PRESS_THRESHOLD    0x0C
#define TOUCH_RELEASE_THRESHOLD  0x06

// 触摸响应模式，可叠加。存 NVS 命名空间 plush 的 touch_modes 键，运行时可改。
#define TOUCH_MODE_REFLEX   0x01   // 本地反射：直接改眼睛、动手臂
#define TOUCH_MODE_WAKE     0x02   // 唤醒对话：进入聆听状态
#define TOUCH_MODE_REPORT   0x04   // 上报大模型：把触摸作为一句话送给服务端
#define TOUCH_MODE_DIAG     0x08   // 读值诊断：把原始计数放进 HTTP status 返回
#define TOUCH_MODES_DEFAULT (TOUCH_MODE_REFLEX | TOUCH_MODE_DIAG)

// ── 运动：MPU6050 并入同一条 I2C，不占新引脚 ──
// INT 引脚同样无处可接，改为 100ms 轮询。姿态与摇晃都不需要毫秒级响应。
//
// GY-521 板载 4.7k 上拉，比 PCA9685/MPR121 的 10k 低一倍。三块板并联后
// 总上拉约 2.4k。若接入后 I2C 读写失败，或触摸、舵机开始不稳，
// 第一件事是拆掉 GY-521 上那两颗上拉电阻。
#define MPU6050_ADDR             0x68   // AD0 接地或悬空
#define MOTION_POLL_INTERVAL_MS  100
// ±4g 量程。±2g 摇晃时削顶，±8g 以上牺牲静态姿态分辨率。
#define MOTION_ACCEL_FS_SEL      0x08
#define MOTION_LSB_PER_G         8192

// 姿态门限（重力分量，单位 LSB）。进入与离开用不同门限 —— 没有迟滞的话，
// 玩具斜靠在沙发上会在两态边界反复横跳，每跳一次就改一次表情。
#define MOTION_UPRIGHT_ENTER   ((MOTION_LSB_PER_G * 7) / 10)   // +0.7g
#define MOTION_UPRIGHT_EXIT    ((MOTION_LSB_PER_G * 5) / 10)   // +0.5g
#define MOTION_INVERTED_ENTER  (-(MOTION_LSB_PER_G * 7) / 10)  // -0.7g
#define MOTION_INVERTED_EXIT   (-(MOTION_LSB_PER_G * 5) / 10)  // -0.5g

// 摇晃：合矢量对 1g 的偏离超过阈值算一次命中，窗口内命中够数才算摇晃，
// 之后进入不应期。没有不应期的话，一次持续摇晃会刷出几十个事件。
#define MOTION_SHAKE_DELTA       ((MOTION_LSB_PER_G * 35) / 100)  // 0.35g
#define MOTION_SHAKE_WINDOW_MS   1000
#define MOTION_SHAKE_HITS        3
#define MOTION_SHAKE_COOLDOWN_MS 1500

// 玩具竖立时哪一轴对着天。装配后若姿态判反，改这里而不是改判定逻辑。
#define MOTION_UP_AXIS_Z         1

// ── 坏样本防御 ──
// 2026-09-10 实测：I2C 偶发吐出全 1 的坏字节，加速度读成 [2647,-1,-1] 或
// az=-258。这个毛病在接 MPU6050 之前就有，触摸侧同样出现过读到 0 的样本，
// 是总线的电气问题（飞线过长、三模块并联），不是某个设备的问题。
// 判定层必须自带防御：一个坏样本曾把姿态从竖直翻成躺倒、眼睛跟着变 sleepy。
//
// 合理性闸门：手持玩具的合矢量不可能低于 0.4g，也不会超过 5g。
// 区间外的样本整帧丢弃，姿态与摇晃都不参与。
#define MOTION_PLAUSIBLE_MIN ((MOTION_LSB_PER_G * 4) / 10)
#define MOTION_PLAUSIBLE_MAX (MOTION_LSB_PER_G * 5)
// 落在合理区间内的坏样本仍可能出现，因此姿态还要求连续若干次判定一致。
// 100ms 一帧，3 帧是 0.3 秒，慢于人翻动玩具的速度，不影响响应观感。
#define MOTION_ORIENT_CONFIRM 3

// 运动响应模式。形状与触摸一致，但用独立的 NVS 键 motion_modes，
// 以便调试时单独关掉其中一类传感器。
#define MOTION_MODE_REFLEX   0x01
#define MOTION_MODE_WAKE     0x02
#define MOTION_MODE_REPORT   0x04
#define MOTION_MODE_DIAG     0x08
#define MOTION_MODES_DEFAULT (MOTION_MODE_REFLEX | MOTION_MODE_DIAG)

// 动作结束后机械振动还会持续一小段，这段时间内继续抑制摇晃判定。
#define MOTION_SERVO_SETTLE_MS 400

// ── 自发手势掩码 ──
// 形状同触摸/运动，NVS 键 gesture_modes。管的是「没人碰玩具时它自己动不动」：
// 设备状态迁移和服务端下发的 emotion。
//
// 默认全关（2026-09-11）。原因是实测观感：一轮对话必然走
// Idle→Listening→Speaking→Idle 三次迁移，服务端回复又几乎每次带 emotion，
// 于是每条指令都伴随四次手臂动作。动作稀疏才显得有意图，每句都动等于没动，
// 还平白耗电、给 I2C 总线添噪。要表现力时按位打开，或直接用 MCP 手势工具。
#define GESTURE_MODE_LISTEN   0x01   // 进入聆听：微微前倾
#define GESTURE_MODE_SPEAK    0x02   // 开始说话：轻摆一次
#define GESTURE_MODE_IDLE     0x04   // 回到空闲：归中泄力
#define GESTURE_MODE_EMOTION  0x08   // 服务端 emotion 联动手势
#define GESTURE_MODES_ALL                                                \
    (GESTURE_MODE_LISTEN | GESTURE_MODE_SPEAK | GESTURE_MODE_IDLE |      \
     GESTURE_MODE_EMOTION)
#define GESTURE_MODES_DEFAULT 0

// GPIO43(丝印TX) 保留给控制台 TX，勿占用 —— 否则日志变乱码（实测）
// 现已无空闲脚：3=舵机SCL 14/38=屏SPI 44=舵机SDA 45/46=两屏CS
// GPIO19/20 保持原生 USB，勿占用

// A MCP Test: Control a lamp —— 本板不使用
// #define LAMP_GPIO GPIO_NUM_NC

#endif // _BOARD_CONFIG_H_
