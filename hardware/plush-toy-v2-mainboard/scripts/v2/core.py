"""四个版本共用的电路。只写连接，料号与焊盘号全部来自 parts_db。"""
from v2 import parts_db as db
from v2.part import cap, cap10u, cap22u, res, testpoint


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
        db.part("SY8089", "U_BUCK", {"IN": "VSYS", "EN": "BUCK_EN", "SW": "BUCK_SW",
                                     "FB": "BUCK_FB", "GND": "GND"}),
        res("R_BUCK_EN", "100k", "VSYS", "BUCK_EN"),
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
