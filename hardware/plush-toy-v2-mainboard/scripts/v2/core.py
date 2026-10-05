"""四个版本共用的电路。只写连接，料号与焊盘号全部来自 parts_db。"""
from v2 import gpio
from v2 import parts_db as db
from v2.part import Part, cap, cap10u, cap22u, res, testpoint


def power_parts() -> list:
    return [
        # ── USB 入口：保险丝 → eFuse → VUSB（spec 3.1）──
        db.part("USB_C16", "J_USB", {"VBUS": "VBUS_IN", "GND": "GND", "SHIELD": "GND",
                                     "CC1": "CC1", "CC2": "CC2", "DP": "USB_DP", "DN": "USB_DN"}),
        res("R_CC1", "5.1k", "CC1", "GND"),
        res("R_CC2", "5.1k", "CC2", "GND"),
        # CC 电压汇总到一个 ADC 节点：未连接的一路被 5.1k 拉到地，节点 ≈ 有效 CC 的一半（spec 3.2）
        res("R_CC_SUM1", "100k", "CC1", "CC_SENSE"),
        res("R_CC_SUM2", "100k", "CC2", "CC_SENSE"),
        cap("C_CC_SENSE", "10nF", "CC_SENSE", "GND"),
        db.part("ESD_LINE", "D_USB_DP", {"IO": "USB_DP", "GND": "GND"}),
        db.part("ESD_LINE", "D_USB_DN", {"IO": "USB_DN", "GND": "GND"}),
        db.part("PTC_USB", "F_USB", {"1": "VBUS_IN", "2": "VBUS_FUSED"}),
        # EN/UVLO 接输入，与一期 U_EFUSE 相同
        db.part("TPS259531", "U_EFUSE", {"IN": "VBUS_FUSED", "EN": "VBUS_FUSED", "OUT": "VUSB",
                                         "ILM": "EFUSE_ILM", "DVDT": "EFUSE_DVDT", "GND": "GND"}),
        cap("C_EFUSE_IN", "100nF", "VBUS_FUSED", "GND"),
        cap("C_EFUSE_DVDT", "3.3nF", "EFUSE_DVDT", "GND"),
        res("R_EFUSE_ILM", "1k", "EFUSE_ILM", "GND"),
        cap10u("C_VUSB", "VUSB", "GND"),

        # ── 充放电 + 升压 IP5306-I2C（spec 3.1，SELECTION.md）──
        # I2C 直接挂 3.3V 总线（同 M5Stack Core 做法）；IRQ 不用
        db.part("IP5306_I2C", "U_CHG", {"VIN": "VUSB", "VOUT": "VSYS", "BAT": "VBAT", "SW": "CHG_SW",
                                        "KEY": "KEY_PWR", "SCL": "I2C_SCL", "SDA": "I2C_SDA",
                                        "GND": "GND"}),
        db.part("INDUCTOR_BOOST", "L_CHG", {"1": "CHG_SW", "2": "VBAT"}),
        cap22u("C_CHG_VIN", "VUSB", "GND"),
        cap22u("C_CHG_BAT", "VBAT", "GND"),
        cap22u("C_VSYS1", "VSYS", "GND"),
        cap22u("C_VSYS2", "VSYS", "GND"),

        # ── 电池：座子 → 防反接（BATTERY_PROTECTION.md 方案 C）→ VBAT ──
        db.part("CONN_BAT", "J_BAT", {"+": "VBAT_PACK", "-": "GND"}),
        *battery_protection(),
        res("R_VBAT_TOP", "100k", "VBAT", "VBAT_SENSE"),
        res("R_VBAT_BOT", "100k", "VBAT_SENSE", "GND"),
        cap("C_VBAT_SENSE", "100nF", "VBAT_SENSE", "GND"),
        res("R_BAT_NTC", "10k", "+3V3", "BAT_NTC_SENSE"),
        cap("C_BAT_NTC", "100nF", "BAT_NTC_SENSE", "GND"),
        db.part("NTC_0603_10K", "RT_BAT", {"1": "BAT_NTC_SENSE", "2": "GND"}),

        # ── 3V3 降压（同一期 SY8089，取 VSYS）：Vout = 0.6 × (1 + 100k/22k) ≈ 3.33V ──
        # EN 直接接输入（SY8089 手册允许）；一期的 100k 上拉在二期密板上是个难布的连接
        db.part("SY8089", "U_BUCK", {"IN": "VSYS", "EN": "VSYS", "SW": "BUCK_SW",
                                     "FB": "BUCK_FB", "GND": "GND"}),
        db.part("INDUCTOR_BUCK", "L_BUCK", {"1": "BUCK_SW", "2": "+3V3"}),
        res("R_FB1", "100k", "+3V3", "BUCK_FB"),
        res("R_FB2", "22k", "BUCK_FB", "GND"),
        cap("C_FF", "22pF", "+3V3", "BUCK_FB"),
        cap10u("C_BUCK_IN", "VSYS", "GND"),
        cap("C_BUCK_HF", "100nF", "VSYS", "GND"),
        cap22u("C_BUCK_OUT1", "+3V3", "GND"),
        cap22u("C_BUCK_OUT2", "+3V3", "GND"),

        # ── 加热功率级：只接 VUSB（spec 3.2）──
        db.part("CONN_HEAT2", "J_HEAT", {"1": "VUSB", "2": "HEAT_LOW"}),
        db.part("AO3400A", "Q_HEAT", {"G": "HEAT_GATE", "S": "GND", "D": "HEAT_LOW"}),
        res("R_GATE", "100", "HEAT_GATE_DRV", "HEAT_GATE"),
        res("R_GATE_PD", "100k", "HEAT_GATE", "GND"),
        db.part("CONN_SH2", "J_NTC", {"1": "NTC_SENSE", "2": "GND"}),
        res("R_NTC", "10k", "+3V3", "NTC_SENSE"),
        cap("C_NTC", "100nF", "NTC_SENSE", "GND"),

        # ── 测试点（背面）──
        testpoint("TP_VUSB", "VUSB"), testpoint("TP_VSYS", "VSYS"), testpoint("TP_VBAT", "VBAT"),
        testpoint("TP_3V3", "+3V3"), testpoint("TP_GND", "GND"), testpoint("TP_CC", "CC_SENSE"),
    ]


def battery_protection() -> list:
    """BATTERY_PROTECTION.md 方案 C：Q_BATP 只在电池两端电压为正时打开，与充电器拉高的 VBAT 无关。"""
    return [
        db.part("AO3401A", "Q_BATP", {"S": "VBAT", "D": "VBAT_PACK", "G": "BATP_GATE"}),
        res("R_BATP_PU", "1M", "VBAT", "BATP_GATE"),
        db.part("AO3400A", "Q_BATN", {"G": "BATN_GATE", "S": "GND", "D": "BATP_GATE"}),
        res("R_BATN_G", "100k", "VBAT_PACK", "BATN_GATE"),
        res("R_BATN_PD", "1M", "BATN_GATE", "GND"),
        # 过放电池被保护板切断后，经此涓流把电池端抬起来，保护板恢复后再走 Q_BATP
        res("R_BATP_BYP", "10k", "VBAT", "VBAT_PACK"),
    ]


def mcu_parts(camera: bool) -> list:
    table = gpio.for_family(camera)
    u1 = db.part("WROOM", "U1", {"GND": "GND", "3V3": "+3V3", "EN": "EN"})
    for pad, g in gpio.WROOM_PAD_GPIO.items():
        u1.pins[pad] = table.get(g, f"NC_U1_IO{g}")
    return [
        u1,
        cap10u("C_U1_BULK", "+3V3", "GND"),
        cap("C_U1", "100nF", "+3V3", "GND"),
        res("R_EN", "10k", "+3V3", "EN"),
        cap("C_EN", "1uF", "EN", "GND"),
        res("R_BOOT", "10k", "+3V3", "BOOT"),
        db.part("SW_TACT", "SW_RST", {"A": "EN", "B": "GND"}),
        db.part("SW_TACT", "SW_BOOT", {"A": "BOOT", "B": "GND"}),
        res("R_SCL", "4.7k", "I2C_SCL", "+3V3"),
        res("R_SDA", "4.7k", "I2C_SDA", "+3V3"),
        # GPIO46 是启动配置脚，舵机信号默认拉低（spec 5.1）
        res("R_SERVO_R_PD", "10k", "SERVO_R_PWM", "GND"),
        testpoint("TP_EN", "EN"), testpoint("TP_BOOT", "BOOT"),
    ]


def peripheral_parts() -> list:
    return [
        # 眼睛：共片选；背光高边开关同一期，不串限流电阻（spec 4 节，屏模块自带限流）
        db.part("CONN_LCD8", "J_LCD", {"1": "LCD_RST", "2": "LCD_CS", "3": "LCD_DC", "4": "LCD_MOSI_S",
                                       "5": "LCD_CLK_S", "6": "GND", "7": "+3V3", "8": "LCD_BL"}),
        res("R_LCD_MOSI", "33", "LCD_MOSI", "LCD_MOSI_S"),
        res("R_LCD_CLK", "33", "LCD_CLK", "LCD_CLK_S"),
        db.part("AO3401A", "Q_LCD_BL", {"G": "LCD_BL_GATE", "S": "+3V3", "D": "LCD_BL"}),
        res("R_LCD_BL_GATE", "100", "LCD_BL_PWM", "LCD_BL_GATE"),
        res("R_LCD_BL_OFF", "100k", "+3V3", "LCD_BL_GATE"),
        cap("C_LCD", "100nF", "+3V3", "GND"),
        # 麦克风：针序同一期 J_MIC
        db.part("CONN_MIC6", "J_MIC", {"1": "+3V3", "2": "GND", "3": "MIC_SD", "4": "MIC_WS",
                                       "5": "MIC_SCK", "6": "GND"}),
        cap("C_MIC", "100nF", "+3V3", "GND"),
        # 功放 MAX98357A（SELECTION.md §功放），接法同一期：SD_MODE 1M 上拉选 (L+R)/2，GAIN 悬空 9dB
        db.part("MAX98357A", "U_AMP", {"VDD": "VSYS", "GND": "GND", "DIN": "AMP_DIN", "BCLK": "AMP_BCLK",
                                       "LRCLK": "AMP_LRCLK", "SD_MODE": "AMP_SD",
                                       "OUTP": "SPK_P", "OUTN": "SPK_N"}),
        res("R_AMP_SD", "1M", "VSYS", "AMP_SD"),
        cap10u("C_AMP_BULK", "VSYS", "GND"),
        cap("C_AMP", "100nF", "VSYS", "GND"),
        db.part("CONN_SPK2", "J_SPK", {"1": "SPK_P", "2": "SPK_N"}),
        # 舵机：VSYS 直供，贴片电容储能
        db.part("HDR_SERVO3", "J_ARM_L", {"1": "SERVO_L_PWM", "2": "VSYS", "3": "GND"}),
        db.part("HDR_SERVO3", "J_ARM_R", {"1": "SERVO_R_PWM", "2": "VSYS", "3": "GND"}),
        cap22u("C_SERVO1", "VSYS", "GND"),
        cap22u("C_SERVO2", "VSYS", "GND"),
        cap22u("C_SERVO3", "VSYS", "GND"),
        # 加速度计 LIS2DH12：I2C，CS 高电平选 I2C，Res 必须接地。
        # SA0 接 3V3（7 位地址 0x19）：它与 CS（2 脚）相邻，同网络一段短线即可；
        # 接地时 0.5mm 间距的 LGA 里打不出孔，布线不通
        db.part("LIS2DH12", "U_IMU", {"VDD": "+3V3", "VDD_IO": "+3V3", "GND": "GND", "RES": "GND",
                                      "SCL": "I2C_SCL", "SDA": "I2C_SDA", "SDO_SA0": "+3V3", "CS": "+3V3"}),
        cap("C_IMU", "100nF", "+3V3", "GND"),
        # 外接按键：电源键 → IP5306 KEY，收音键 → 版本相关的 KEY_MUTE 网络
        db.part("CONN_KEY3", "J_KEY", {"1": "KEY_PWR", "2": "KEY_MUTE", "3": "GND"}),
        db.part("ESD_LINE", "D_ESD_PWR", {"IO": "KEY_PWR", "GND": "GND"}),
        db.part("ESD_LINE", "D_ESD_MUTE", {"IO": "KEY_MUTE", "GND": "GND"}),
        res("R_KEY_MUTE_PU", "10k", "+3V3", "KEY_MUTE"),
        db.part("CONN_SH2", "J_TOUCH", {"1": "TOUCH_E0", "2": "GND"}),
        db.part("ESD_LINE", "D_ESD_TOUCH", {"IO": "TOUCH_E0", "GND": "GND"}),
        # 安装孔 M2 ×2
        *[Part(f"H{i}", "M2", "Mechanical:MountingHole", "MountingHole:MountingHole_2.2mm_M2",
               assembly=False) for i in (1, 2)],
    ]


def core_parts(camera: bool) -> list:
    return power_parts() + mcu_parts(camera) + peripheral_parts()
