# 毛绒玩具项目 · 待交付 TODO

**更新**：2026-09-07 · 任务暂停于此
**当前进度**：见 `STATUS.md`
**分支**：`feat/plush-toy-design`（已推送至 `codingDuan/xiaozhi-esp32`）

---

## A. 只需你确认，一句话就能结（阻塞中）

### A1. 虹膜颜色 → 定稿 RGB_ORDER
**现状**：眼睛正在显示，虹膜颜色是 `#35C7F5`（青蓝）。若模块的 RGB/BGR 排列与配置不符，会显示成橙红。

**要做的**：看一眼虹膜颜色，告诉我是青蓝还是橙红。
- 青蓝 → 无需改动，此项关闭
- 橙红 → 把 `config.h` 的 `DISPLAY_RGB_ORDER` 默认值改为开启红蓝互换

**已铺好的退路**：即使不改代码，联网后对玩具说「眼睛颜色反了」，MCP 工具 `self.eyes.swap_colors` 会翻转并存进 NVS，重启不丢。

### A2. 眨眼是否已同步
**现状**：已从"顺序传输"改为"按条交错"，理论最大偏差从 66ms 降到 6ms。
**要做的**：再看一次眨眼，确认两只眼是否同时。若仍有可见时间差，把 `DISPLAY_PCLK_HZ` 从 10MHz 提到 20MHz（spec 允许上限），可再砍一半。

### A3. 眼睛造型是否满意
巩膜比例、瞳孔大小、高光位置这些现在改最便宜。参照 `main/boards/plush-toy/test/` 下 `make test && ./preview && python3 to_png.py` 生成的图。

---

## B. 需要网络恢复后才能验（当前设备在配网模式）

**前置**：手机热点开启 → Mac 连上该热点 → 确认 Mac 的 IP（热点重开会变）→ 设备配网填 `http://<MacIP>:8003/xiaozhi/ota/` → 服务端重启（`data/.config.yaml` 的 prompt 改动需重启才生效）

### B1. emoji 白名单是否生效
串口看 `SetEmotion:` 的值是否出现 `happy` 以外的情绪。

**已知隐患**：模型曾自发使用 😊（U+1F60A），它**不在** `EMOJI_MAP` 中，会静默回落成 `happy`；而 🙂（U+1F642）才在表内。两者肉眼几乎无差别。prompt 里已明写「形近的其他 emoji 一律无效（例如 😊 就不行，必须用 🙂）」，需实测是否管住了模型。

### B2. emotion → 表情 + 手势联动
说一句能引发不同情绪的话，确认眼型变化 + 对应手势。

### B3. 手势工具的其余两个
`self.limbs.hug` 已端到端验证通过。`wave_hand`、`cheer` 尚未实测。

---

## C. 未实现的功能（我可以直接做，不需要硬件）

### C1. 配网二维码 `overlay_qr`（计划一 Task 6/7）
**为什么值得做**：现在设备进配网模式时屏上毫无提示，只能看串口——这正是你刚遇到的情况。做完后左眼显示可扫二维码（内容 `WIFI:S:Xiaozhi-XXXX;T:nopass;;`），手机扫一下直接加入热点，不用手动翻 WiFi 列表。

**做法**（不要手写编码器，纠错码写错的表现是"扫不出来"，没硬件时发现不了）：
```bash
cd main/boards/plush-toy
curl -sL -o qrcodegen.c https://raw.githubusercontent.com/nayuki/QR-Code-generator/master/c/qrcodegen.c
curl -sL -o qrcodegen.h https://raw.githubusercontent.com/nayuki/QR-Code-generator/master/c/qrcodegen.h
```
（已验证可下载、MIT 许可、纯 C99 无依赖；本次未接线故已清除，需要时重下）

然后实现 `overlay_qr.h/.cc` + `EyeDisplay::ShowQrCode()`，并挂到 `kDeviceStateWifiConfiguring`。
**注意**：二维码必须深色模块画在**浅色底**上才扫得出，不能在黑底上画亮模块。

### C2. OTA 升级进度显示
Overlay 模式的第二个用途，进度环。优先级低于 C1。

---

## D. 需要等硬件条件（装进玩偶后）

### D1. 舵机 trim 校准
`0°` 是电气中位，装到手臂上后「自然下垂」未必对应 0°。建议存 NVS `Settings` 以便在线调整而不重烧。

### D2. 独立 5V 电源 + 1000µF 电容
**实测**：USB 供电下双路舵机无间歇连续动作会 BROWNOUT 掉电重启（可复现两次）。目前靠动作间强制冷却 300ms 规避。装进玩偶后手臂带载，电流更大，独立电源成为必需。

### D3. 服务端固定地址
服务端 IP 随网络变化，症状是「设备突然不说话」。本次已为此绕了三轮。建议：固定 IP 的机器，或挂域名。

---

## E. 已知技术债

| 项 | 说明 |
|---|---|
| 引脚已用尽 | 无空闲 GPIO，再加外设需先腾地方（详见 `STATUS.md` 引脚表） |
| LVGL 仍被编译 | `main/CMakeLists.txt:20-31` 无条件加入 `SOURCES`，本板不用但仍链接。emoji 图片资源已不打包（flash 占用的大头），代码部分依赖链接器裁剪 |
| SPI 仅 10MHz | spec 允许 20MHz，未上探。提速可改善眼睛动画流畅度 |
| 计划文档与实现有偏差 | 计划二写的是 GPIO 直驱 PWM，实际改用 PCA9685；计划一 Task 2/3 已合并实现。文档中已就地标注，但未整体重写 |
