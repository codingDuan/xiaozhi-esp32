# 毛绒玩具项目 · 进度汇总

**更新时间**：2026-09-07
**分支**：`feat/plush-toy-design`（已推送至 `codingDuan/xiaozhi-esp32`）
**板型**：`main/boards/plush-toy/`

相关文档：
- 设计方案 `docs/superpowers/specs/2026-09-05-plush-toy-design.md`
- 计划一（眼睛）`docs/superpowers/plans/2026-09-06-plush-toy-eyes.md`
- 计划二（肢体）`docs/superpowers/plans/2026-09-07-plush-toy-limbs.md`
- 眼睛造型原型：分支 `prototype/eye-renderer`

---

## 一、当前完成度

| 模块 | 状态 | 验证方式 |
|---|---|---|
| 板型骨架 `plush-toy` | ✅ | 实机启动，`SKU=plush-toy` |
| 摄像头 OV3660 | ✅ | 实机识别 |
| PCA9685 舵机驱动 | ✅ | `PRE_SCALE=121` 回读一致 |
| 手势编排 `LimbController` | ✅ | 实机动作，无 BROWNOUT |
| MCP 手势工具 ×3 | ✅ | **端到端**：说"抱一抱我"→ 手臂张开 |
| 状态反射 `PlushBehavior` | ✅ | 状态轮询生效 |
| emotion → 表情+手势 | ✅ | 链路通，emoji 白名单待验 |
| 眼睛渲染 `EyeRenderer` | ✅ | 11 项主机端测试全过 |
| 双圆屏 `EyeDisplay` | ✅ | 实机初始化成功，无报错 |
| 待机眨眼 + 瞳孔游走 | ✅ | 已启动 |
| 服务端 prompt | ✅ | 已写入 `data/.config.yaml` |

## 二、待办

### 优先级高

1. **确认屏幕颜色是否正确**（阻塞 `RGB_ORDER` 定稿）
   之前的接线验证程序里，需要确认「阶段 A 变红的是左眼还是右眼」。
   - 左红右蓝 → `DISPLAY_RGB_ORDER = BGR` 正确
   - 左蓝右红 → 需改为 `RGB`
   现在主固件已烧回，可直接看眼睛的虹膜是否为青蓝色（`#35C7F5`）。
   若显示成橙红色，就是 RGB_ORDER 反了。

2. **验证 emoji 白名单是否生效**
   `data/.config.yaml` 的 prompt 已加白名单规则，但需服务端重启后实测。
   重点看串口 `SetEmotion:` 的值是否出现 `happy` 以外的情绪。
   已知隐患：模型曾自发使用 😊（U+1F60A），它**不在** `EMOJI_MAP` 中，
   会静默回落成 `happy`，而 🙂（U+1F642）才在表内。两者肉眼几乎无差别。

3. **SPI 提速**：当前 `DISPLAY_PCLK_HZ = 10MHz`，spec 允许上探至 20MHz。
   眼睛动画流畅度不足时再调。

### 优先级中

4. **配网二维码**（计划一 Task 6/7）—— `overlay_qr` 模块尚未实现。
   当前配网时眼睛无提示，只能看串口。方案：vendored Nayuki qrcodegen（MIT）。
5. **舵机 trim 校准** —— 装进玩偶后「手臂自然下垂」未必对应 0°，
   建议存 NVS `Settings` 以便在线调整。
6. **独立 5V 电源** —— 实测双路无间歇连续动作会 BROWNOUT。
   装进玩偶带载后必需，需 1000µF 电容。

---

## 三、引脚占用（已无空闲）

| GPIO | 用途 | 备注 |
|---|---|---|
| 0 | BOOT 按键 | |
| 1 / 2 / 42 | 麦克风 WS / SCK / DIN | |
| 3 | 舵机 I2C SCL | 接 PCA9685 |
| 4–13, 15–18 | 摄像头 | |
| 14 | 眼屏 MOSI | 屏丝印 `SDA` |
| 19 / 20 | **原生 USB** | 勿占用，烧录+日志 |
| 21 | 眼屏 RST | 两屏并联 |
| 26–32 | SPI Flash | 不可用 |
| 33–37 | 八线 PSRAM | 不可用 |
| 38 | 眼屏 CLK | 屏丝印 `SCL` |
| 39 / 40 / 41 | 喇叭 DOUT / BCLK / LRCK | |
| 43 | **控制台 UART TX** | **勿占用**，占了日志变乱码 |
| 44 | 舵机 I2C SDA | 排针丝印 `RX` |
| 45 | 左眼 CS | |
| 46 | 右眼 CS | 原为 43，因日志冲突迁移 |
| 47 | 眼屏 DC | 两屏并联 |
| 48 | 板载 WS2812 | |

---

## 四、构建与烧录

EIM 环境下 `idf.py` 是 shell 函数而非 PATH 上的可执行文件，
`scripts/build.py` 用 subprocess 调它会失败；且新增 `.cc` 后需 reconfigure
（`main/CMakeLists.txt:869` 的 `file(GLOB)` 只在 configure 时求值）。

```bash
source ~/.espressif/tools/activate_idf_v6.1.sh
export PATH="$IDF_PATH/tools:$PATH"     # 缺这行 build.py 必失败
idf.py reconfigure                       # 仅在新增/删除源文件后需要
idf.py build
idf.py -p /dev/cu.usbmodem5C834268091 flash
```

主机端眼睛测试（不需要硬件）：

```bash
cd main/boards/plush-toy/test && make test
./preview && python3 to_png.py          # 渲染各情绪为图片肉眼检查
```

---

## 五、服务端

- 路径 `~/Workspace/xiaozhi-esp32-server`，OTA `:8003`，WebSocket `:8000`
- **配置改 `data/.config.yaml`，不要改 `config.yaml`** ——
  后者是上游 git 跟踪文件，且会被前者完全覆盖（`config_loader.py:46` 深合并）
- **服务端 IP 会随网络变化**。设备里存的 OTA 地址过期时，
  症状是「设备突然不说话」。排查第一步：核对 Mac 当前 IP 与设备中存的地址。
  长期建议：固定 IP 的机器，或挂域名。

---

## 六、踩过的坑（避免重复）

| 现象 | 根因 | 位置 |
|---|---|---|
| 舵机一动摄像头花屏 | 摄像头 XCLK 与舵机抢 LEDC 通道 | 改用 PCA9685 后消失 |
| 舵机 I2C 建不起来 | 摄像头 SCCB 实占 `I2C_NUM_1` 而非 0；`camera_config_t.sccb_i2c_port` 是死字段 | `sccb-ng.c:123` |
| `PRE_SCALE` 写 121 读回 217 | `I2cDevice` 硬编码 400kHz，面包板飞线失真 | `i2c_device.cc:12` |
| 串口日志变乱码 | GPIO43 是控制台 TX，被 esp_lcd 当 CS 占用 | 已迁至 GPIO46 |
| 屏刷不出 + WiFi 起不来 | PSRAM→SPI DMA 需等大内部弹跳缓冲，115KB 分配失败并耗尽内部 RAM | 改分条传输 |
| 双路舵机连续动作掉电 | USB 供电不足 | 动作间强制冷却 300ms |
| prompt 改了不生效 | `data/.config.yaml` 覆盖 `config.yaml` | `config_loader.py:46` |
