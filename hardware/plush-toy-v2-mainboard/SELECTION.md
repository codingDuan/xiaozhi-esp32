# 二期选型记录

2026-10-05 定稿。库存与「基础库 / 扩展库」取自嘉立创元件接口（`selectSmtComponentList`），单价为 1–49 片档美元价。
引脚号写在 `scripts/v2/parts_db.py`，本文件记录出处与核对结论。封装焊盘与语义引脚的对应由 `test_parts_db.FootprintPadTests` 用 KiCad 实际加载封装校验。

## 主要器件

| 键 | 料号 | 型号 | 库 | 库存 | 单价 | 符号 / 封装来源 |
|---|---|---|---|---|---|---|
| WROOM | C2913202 | ESP32-S3-WROOM-1-N16R8 | 扩展 | 30540 | $5.14 | KiCad 官方 |
| IP5306_I2C | C488349 | IP5306-I2C | 扩展 | 3653 | $0.35 | easyeda2kicad |
| TPS259531 | C2155674 | TPS259531DSGR | 扩展 | 3160 | $0.87 | 符号复制自一期 `plush.kicad_sym`，封装 KiCad 官方 |
| SY8089 | C78988 | SY8089AAAC | 扩展 | 41214 | $0.15 | KiCad TLV62569DBV 符号（引脚相同，一期已用） |
| MAX98357A | C910544 | MAX98357AETE+T | 扩展 | 23509 | $1.32 | KiCad 官方 |
| LIS2DH12 | C110926 | LIS2DH12TR | 扩展 | 1261 | $0.93 | easyeda2kicad |
| AO3400A | C20917 | AO3400A | **基础** | 956431 | $0.09 | KiCad 官方 |
| AO3401A | C15127 | AO3401A | **基础** | 816774 | $0.10 | KiCad 官方 |
| INDUCTOR_BOOST | C135287 | SMNR5030-1R0MT（1µH，5×5mm） | 扩展 | 2195 | $0.09 | easyeda2kicad |
| INDUCTOR_BUCK | C2926400 | YHNR4020-2R2M（2.2µH） | 扩展 | 10280 | $0.10 | 封装复制自一期 |
| PTC_USB | C883132 | BSMD1206-150-6V | 扩展 | 31086 | $0.05 | KiCad 官方 |
| ESD_LINE | C172409 | LESD8D3.3CAT5G | 扩展 | 1721919 | $0.01 | KiCad 官方 |
| NTC_0603_10K | C13564 | NCP18XH103F03RB（B=3380） | 扩展 | 244491 | $0.05 | KiCad 官方 |
| LDO_2V8 | C53099 | ME6211C28M5G-N | 扩展 | 下单前重查 | — | KiCad 官方 |
| LDO_1V5 | C53100 | ME6211C15M5G-N | 扩展 | 下单前重查 | — | KiCad 官方 |
| MPR121 | C91322 | MPR121QR2 | 扩展 | 下单前重查 | — | KiCad 官方 |
| ADS1115 | C37593 | ADS1115IDGSR | 扩展 | 下单前重查 | — | KiCad 官方 |

## 连接器与按键

| 键 | 料号 | 型号 | 库 | 库存 | 封装来源 |
|---|---|---|---|---|---|
| USB_C16 | C165948 | HRO TYPE-C-31-M-12 | 扩展 | 423652 | KiCad 官方 |
| CONN_BAT | C22461285 | 涵霞 HX PH2.0-2PWT（PH2.0 兼容） | 扩展 | 36669 | easyeda2kicad |
| CONN_LCD8 | C160407 | JST SM08B-SRSS-TB | 扩展 | 122870 | KiCad 官方 |
| CONN_MIC6 | C2845365 | HCTL HC-1.0-6PWT（SH1.0 兼容） | 扩展 | 157664 | easyeda2kicad |
| CONN_HEAT2 | C7429671 | ZX-XH2.54-2PWT（3A） | 扩展 | 139414 | easyeda2kicad |
| CONN_SH2 | C160402 | JST SM02B-SRSS-TB | 扩展 | 36375 | KiCad 官方 |
| CONN_KEY3 | C7430445 | ZX-SH1.0-3PWT | 扩展 | 90756 | easyeda2kicad |
| HDR_SERVO3 | C46061676 | HX PZ2.54-1x3P WT（卧贴） | 扩展 | 21801 | easyeda2kicad |
| SW_TACT | C720477 | TS-1088-AR02016（4×3mm） | **基础** | 778201 | easyeda2kicad |
| CAM_FPC | C262669 | AFC01-S24FCA-00（24P、0.5mm、下接） | 扩展 | 下单前重查 | 一期同型号封装复制并加方向丝印 |

阻容沿用一期料号，全部在库；除 75k、2.2nF、3.3nF 外均为基础库。

## 核对结论

### IP5306-I2C（手册 V1.21，含寄存器文档）
- 引脚：1 VIN、**2 SCL、3 SDA、4 IRQ**（I2C 版本把 LED1/2/3 改作 I2C）、5 KEY、6 BAT、7 SW、8 VOUT、EP GND。
- **没有充电指示灯驱动脚**。按计划 Task 1 的规则删除两颗指示灯，充电状态由固件经 I2C 读取（`0x70` bit3 充电中、`0x71` bit3 已充满）后用眼睛屏显示。需在 spec 第 4 节记修订并告知委托方。
- 防轻载关机：`SYS_CTL0 (0x00)` bit1「BOOST 输出常开」置 1；`SYS_CTL2 (0x02)` bit3:2 为轻载关机时间。
- 关闭充电：`0x00` bit4 置 0。
- 充电电流（VIN 端）：`0x24` bit4:0，I = 0.05 + b0×0.1 + b1×0.2 + b2×0.4 + b3×0.8 + b4×1.6 A。加热时调低用。
- I2C 地址 0xEA（8 位写地址，即 7 位 0x75），最高 400kHz；寄存器必须「读 → 改 → 写」。
- 待机电流（VIN=0，VBAT=3.7V）典型 50µA，正好等于 spec 3.3 的上限：一个月约 36mAh，1500mAh 电池可放约 3 年，可接受。
- 手册推荐电感 1µH（DARFON SPM70701R0，Isat 15A）。本板负载远小于移动电源场景，选 SMNR5030-1R0MT（1µH，5×5mm，额定 4A）。首板需在双舵机 + 对话时测电感温升。
- 业界先例：M5Stack Core 系列在 3.3V I2C 总线上直接挂 IP5306-I2C，ESP32 由升压输出经稳压供电，与本设计相同。

### TPS259531（eFuse）
- 1 dVdt、2 EN/UVLO、**3/4 IN、5 OUT**、6 FLT、7 ILM、8 GND、EP GND。与一期 `U_EFUSE` 接法一致，一期首板实测限流有效（#1 事故中把故障电流限在约 2A）。
- 计划初稿的示例代码把 IN/OUT 写反（2/3/4 当输出、5 当输入），已按本表改正，并加测试 `test_efuse_input_and_output_pads_follow_datasheet`。

### 功放：NS4168 → MAX98357A
- NS4168（手册）输入高电平门限 **0.7×VDD**。接 5V 时为 3.5V，ESP32 的 3.3V 输出够不着；改接 3.3V 音量约减半，且 D 类大电流脉冲落在 ESP32 电源上。
- MAX98357A 输入门限固定 1.3V，5V 供电可直接接 3.3V 逻辑；一期首板实测声音清楚。每板多 $0.55（1.32 − 0.77）。
- 接法同一期：SD_MODE 经 1MΩ 上拉到 VDD（(L+R)/2 模式），GAIN 悬空（9dB）。

### LIS2DH12（手册 Table 2）
- 1 SCL、2 CS（接 VDD_IO 选 I2C）、3 SDO/SA0（接 3V3，7 位地址 0x19；布线原因见 core.py 注释）、4 SDA、**5 Res 必须接地**、6/7/8 GND、9 VDD、10 VDD_IO、11 INT2、12 INT1。

### 摄像头族（仅 C/D）
- FPC 沿用一期实物核对过的 AFC01-S24FCA-00 下接座与同一封装。排线触点朝下时，实测关系为“摄像头第 k 脚 → 板上焊盘第 25−k 脚”；`v2/cam.py` 用 `CAMERA_PIN_SIGNALS` 与 `CAMERA_PAD_TO_PIN` 两级表表达，禁止把参考针表直接当焊盘号。
- 摄像头脚 4 DOVDD、10 DVDD、11 AVDD、2 AGND、15 DGND 分别落在反序后的焊盘 21、15、14、23、10；自动测试同时禁止电源脚落入 ESP32 GPIO 网络。
- 两路 LDO 沿用一期 ME6211C28M5G-N / ME6211C15M5G-N；MPR121 与 ADS1115 沿用一期已核对引脚表。C/D 下单前仍须重新检查库存和贴片库类型。
- MPR121 的 ELE0 接头部触摸；只有 ELE4–ELE11 支持 GPIO，故 ELE4 接加热栅极驱动、ELE5 接收音键。芯片复位时输出为高阻，`R_GATE_PD=100k` 硬件保证加热默认关闭。
- ADS1115 AIN0–AIN3 固定依次为加热 NTC、电池电压、CC 汇总、电池 NTC；固件必须使用相同通道顺序。

### 连接器
- SH1.0 6P、3P 的 JST 原厂卧贴件嘉立创缺货（SM03B 库存 2），改用国产兼容件，封装取自该料号本身（easyeda2kicad），不套用 JST 官方封装。
- 舵机座选卧贴（WT）：插头从板边水平插入，与其它出线座「开口朝外」一致。
- USB-C 保留一期 TYPE-C-31-M-12：16P 座子受接口标准限制宽度都在 9mm 左右，换型号省不出面积，而这颗一期已验证、库存 42 万。
- 喇叭座原为 MX1.25（C177225），2026-10-05 委托方要求统一为 SH1.0 2P（与测温、触摸同料号 C160402），少一种线、少一种扩展库料号。SH1.0 与 MX1.25 触点额定都是 1A，MAX98357A 输出在此范围内。
- 电池座原为 JST 原厂 S2B-PH-SM4-TB（C295747，$0.24），2026-10-05 委托方同意换国产兼容件涵霞 HX PH2.0-2PWT（C22461285，$0.033，库存最多、与舵机座同厂）。封装用该料号自身（easyeda2kicad），属性改为 SMD。国产座 1 脚在右侧，丝印按焊盘实际位置印 +/−，功能名只写 BAT。
- 电池座 1 脚为「+」。PH2.0 电池线各家极性不一，由板上防反接（`BATTERY_PROTECTION.md`）兜底，丝印大字标注。
