"""plush-toy 主板的全部器件与连接。原理图和 PCB 都从这里生成，改连接只改这里。

引脚号一律来自原厂数据手册或 KiCad 官方符号（已与数据手册核对），出处写在每个器件旁。
取值与料号见设计方案第 5.2、12 节。
"""
from dataclasses import dataclass, field


@dataclass
class Part:
    ref: str
    value: str
    symbol: str
    footprint: str
    lcsc: str = ""
    fitted: bool = True
    pins: dict[str, str] = field(default_factory=dict)
    assembly: bool = True


# GPIO → 网络。键集合必须与 test_board_spec.MACRO_TO_NET 覆盖的 GPIO 一致，
# 另加 USB（19/20）与控制台 TX（43，引到测试点）。
GPIO_NET = {
    1: "MIC_WS", 2: "MIC_SCK", 3: "I2C_SCL", 4: "CAM_SIOD", 5: "CAM_SIOC",
    6: "CAM_VSYNC", 7: "CAM_HREF", 8: "CAM_Y4", 9: "CAM_Y3", 10: "CAM_Y5",
    11: "CAM_Y2", 12: "CAM_Y6", 13: "CAM_PCLK", 14: "LCD_MOSI", 15: "CAM_XCLK",
    16: "CAM_Y9", 17: "CAM_Y8", 18: "CAM_Y7", 19: "USB_DN", 20: "USB_DP",
    21: "LCD_RST", 38: "LCD_CLK", 39: "AMP_DIN", 40: "AMP_BCLK", 41: "AMP_LRCLK",
    42: "MIC_SD", 43: "UART_TX", 44: "I2C_SDA", 45: "LCD_CS_L", 46: "LCD_CS_R",
    47: "LCD_DC", 48: "LCD_BL_PWM", 0: "BOOT",
}

# ESP32-S3-WROOM-1 模组焊盘号 → GPIO，出自 esp32-s3-wroom-1_wroom-1u_datasheet_en v1.8 表 3-1
_WROOM_PAD_GPIO = {
    "4": 4, "5": 5, "6": 6, "7": 7, "8": 15, "9": 16, "10": 17, "11": 18, "12": 8,
    "13": 19, "14": 20, "15": 3, "16": 46, "17": 9, "18": 10, "19": 11, "20": 12,
    "21": 13, "22": 14, "23": 21, "24": 47, "25": 48, "26": 45, "27": 0,
    "31": 38, "32": 39, "33": 40, "34": 41, "35": 42, "36": 44, "37": 43, "38": 2, "39": 1,
}

_u1_pins = {"1": "GND", "2": "+3V3", "3": "EN", "40": "GND", "41": "GND",
            "28": "NC_IO35", "29": "NC_IO36", "30": "NC_IO37"}
_u1_pins.update({pad: GPIO_NET[g] for pad, g in _WROOM_PAD_GPIO.items()})

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
SOT23_5 = "Package_TO_SOT_SMD:SOT-23-5"
TESTPAD = "TestPoint:TestPoint_Pad_D1.0mm"

# 阻容料号，均已在产品页核对（设计方案 12.5 节）
LCSC_R = {"0": "C17168", "33": "C25105", "100": "C25076", "1k": "C11702", "1.02k": "C226838",
          "4.7k": "C25900",
          "5.1k": "C25905", "10k": "C25744", "22k": "C25768", "75k": "C25798", "100k": "C25741",
          "1M": "C26083"}
LCSC_C = {"22pF": "C1555", "2.2nF": "C1531", "3.3nF": "C696855", "10nF": "C15195", "100nF": "C1525",
          "1uF": "C52923", "4.7uF": "C23733"}


def res(ref: str, value: str, a: str, b: str, fitted: bool = True) -> Part:
    return Part(ref, value, "Device:R", R0402, LCSC_R[value], fitted, {"1": a, "2": b})


def cap(ref: str, value: str, a: str, b: str) -> Part:
    return Part(ref, value, "Device:C", C0402, LCSC_C[value], True, {"1": a, "2": b})


def cap10u(ref: str, a: str, b: str) -> Part:
    return Part(ref, "10uF", "Device:C", C0603, "C19702", True, {"1": a, "2": b})


def cap22u(ref: str, a: str, b: str) -> Part:
    return Part(ref, "22uF", "Device:C", C0805, "C45783", True, {"1": a, "2": b})


def testpoint(ref: str, net: str) -> Part:
    return Part(ref, net, "Connector:TestPoint", TESTPAD, pins={"1": net}, assembly=False)


def nc(ref: str, pin: str) -> str:
    return f"NC_{ref}_{pin}"


PARTS: list[Part] = [
    # ── 主控 ──
    Part("U1", "ESP32-S3-WROOM-1-N16R8", "RF_Module:ESP32-S3-WROOM-1",
         "RF_Module:ESP32-S3-WROOM-1", "C2913202", pins=_u1_pins),
    cap10u("C_U1_BULK", "+3V3", "GND"),
    cap("C_U1", "100nF", "+3V3", "GND"),
    # EN 上电复位：10k 上拉 + 1µF 对地（设计方案第 9 节）
    res("R_EN", "10k", "+3V3", "EN"),
    cap("C_EN", "1uF", "EN", "GND"),
    # 按键 TS-1187A-B-A-B：1、2 内部相连接信号，3、4 内部相连接地（设计方案 12.5 节）
    Part("SW_RST", "TS-1187A-B-A-B", "lcsc:TS-1187A-B-A-B",
         "lcsc:SW-SMD_4P-L5.1-W5.1-P3.70-LS6.5-TL_H1.5", "C318884",
         pins={"1": "EN", "2": "EN", "3": "GND", "4": "GND"}),
    # GPIO0 是启动模式 strapping 脚，外加上拉保证默认从 Flash 启动
    res("R_BOOT", "10k", "+3V3", "BOOT"),
    Part("SW_BOOT", "TS-1187A-B-A-B", "lcsc:TS-1187A-B-A-B",
         "lcsc:SW-SMD_4P-L5.1-W5.1-P3.70-LS6.5-TL_H1.5", "C318884",
         pins={"1": "BOOT", "2": "BOOT", "3": "GND", "4": "GND"}),
    # 调试与外接按键口。装进玩偶后板载的 SW_RST/SW_BOOT 按不到，必须引出来；
    # 拆解的成品机芯也是这么做的（板边一排 3V3/TX/RX/RST/GND）。
    # 没有 RX：GPIO44（开发板丝印 RX）在本板是舵机 I2C 的 SDA。
    # BOOT 引出即等于把固件的主功能键引出（config.h 的 BOOT_BUTTON_GPIO = GPIO0）。
    #
    # 用 SH 1.0mm 而不是板上其余连接器的 PH 2.0mm：PH 是通孔件，焊盘穿透所有层，
    # 会撞上按键一带 B.Cu 的 LCD_CLK 和 USB_DP；贴片 PH 全板只剩一处放得下，
    # 且离 EN/BOOT/TX 有 33~48mm。SH 全贴片、只占 8.9x5.3mm，能贴着两个按键放。
    # 交给机器贴：1.0mm 脚距手焊容易连锡，而板上其余手工件都是通孔件。
    # 料号 BM05B-SRSS-TB(LF)(SN)。这颗在 LCSC 的库存显示不稳定，下单前要与
    # 供应商确认；实在缺货就退回手焊，或换等效的国产 SH 座（针序与封装相同）。
    Part("J_EXT", "Debug / Keys", "Connector_Generic:Conn_01x05",
         "Connector_JST:JST_SH_BM05B-SRSS-TB_1x05-1MP_P1.00mm_Vertical", "C160391",
         pins={"1": "+3V3", "2": "UART_TX", "3": "EN", "4": "BOOT", "5": "GND"}),
    # ── USB-C 与逻辑域 5V ──
    # 符号 Connector:USB_C_Receptacle_USB2.0_16P 引脚名与 HRO TYPE-C-31-M-12 封装焊盘名一一对应
    Part("J_USB", "TYPE-C-31-M-12", "Connector:USB_C_Receptacle_USB2.0_16P",
         "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", "C165948",
         pins={"A1": "GND", "B1": "GND", "A12": "GND", "B12": "GND",
               "A4": "VBUS_IN", "B4": "VBUS_IN", "A9": "VBUS_IN", "B9": "VBUS_IN",
               "A5": "USB_CC1", "B5": "USB_CC2", "A6": "USB_DP", "B6": "USB_DP",
               "A7": "USB_DN", "B7": "USB_DN", "A8": nc("J_USB", "SBU1"), "B8": nc("J_USB", "SBU2"),
               "SH": "GND"}),
    # CC 各 5.1k 下拉，主机才会输出 5V
    res("R_CC1", "5.1k", "USB_CC1", "GND"),
    res("R_CC2", "5.1k", "USB_CC2", "GND"),
    Part("F_USB", "BSMD1206-150-6V", "Device:Fuse", "Fuse:Fuse_1206_3216Metric", "C883132",
         pins={"1": "VBUS_IN", "2": "VBUS_FUSED"}),
    Part("U_EFUSE", "TPS259531DSGR", "plush:TPS259531",
         "Package_SON:Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm_ThermalVias", "C2155674",
         pins={"1": "EFUSE_DVDT", "2": "VBUS_FUSED", "3": "VBUS_FUSED", "4": "VBUS_FUSED",
               "5": "VBUS", "6": nc("U_EFUSE", "FLT"), "7": "EFUSE_ILM", "8": "GND", "9": "GND"}),
    cap("C_EFUSE_IN", "100nF", "VBUS_FUSED", "GND"),
    cap("C_EFUSE_DVDT", "3.3nF", "EFUSE_DVDT", "GND"),
    res("R_EFUSE_ILM", "1.02k", "EFUSE_ILM", "GND"),
    Part("D_USB_DP", "LESD8D3.3CAT5G", "Device:D_TVS", "Diode_SMD:D_SOD-882", "C172409",
         pins={"1": "USB_DP", "2": "GND"}),
    Part("D_USB_DN", "LESD8D3.3CAT5G", "Device:D_TVS", "Diode_SMD:D_SOD-882", "C172409",
         pins={"1": "USB_DN", "2": "GND"}),

    # ── 3V3 降压：SY8089AAAC，引脚与 TLV62569DBV 符号一致（EN GND SW VIN FB）──
    Part("U_BUCK", "SY8089AAAC", "Regulator_Switching:TLV62569DBV", SOT23_5, "C78988",
         pins={"1": "BUCK_EN", "2": "GND", "3": "BUCK_SW", "4": "VBUS", "5": "BUCK_FB"}),
    res("R_BUCK_EN", "100k", "VBUS", "BUCK_EN"),
    Part("L_BUCK", "2.2uH", "lcsc:YHNR4020-2R2M", "lcsc:IND-SMD_L4.0-W4.0_YHNR4020", "C2926400",
         pins={"1": "BUCK_SW", "2": "+3V3"}),
    cap("C_BUCK_HF", "100nF", "VBUS", "GND"),
    cap22u("C_BUCK_IN", "VBUS", "GND"),
    cap22u("C_BUCK_OUT1", "+3V3", "GND"),
    cap22u("C_BUCK_OUT2", "+3V3", "GND"),
    # Vout = 0.6 × (1 + 100k/22k) ≈ 3.327V
    res("R_FB1", "100k", "+3V3", "BUCK_FB"),
    res("R_FB2", "22k", "BUCK_FB", "GND"),
    cap("C_FF", "22pF", "+3V3", "BUCK_FB"),

    # ── 摄像头 LDO：ME6211，引脚 VIN GND CE NC VOUT（ESP32-S3-EYE-MB V2.2 第 2 页）──
    Part("U_LDO28", "ME6211C28M5G-N", "Regulator_Linear:ME6211C28M5", SOT23_5, "C53099",
         pins={"1": "+3V3", "2": "GND", "3": "+3V3", "4": nc("U_LDO28", "4"), "5": "+2V8"}),
    cap("C_LDO28_IN", "1uF", "+3V3", "GND"),
    cap("C_LDO28_OUT", "1uF", "+2V8", "GND"),
    Part("U_LDO15", "ME6211C15M5G-N", "Regulator_Linear:ME6211C15M5", SOT23_5, "C53100",
         pins={"1": "+3V3", "2": "GND", "3": "+3V3", "4": nc("U_LDO15", "4"), "5": "+1V5"}),
    cap("C_LDO15_IN", "1uF", "+3V3", "GND"),
    cap("C_LDO15_OUT", "1uF", "+1V5", "GND"),

    # ── 功率域 VMOT：舵机与加热，与 VBUS 无任何铜连接（HC-1）──
    Part("J_VMOT", "VMOT 5V", "Connector_Generic:Conn_01x02",
         "TerminalBlock_CUI:TerminalBlock_CUI_TB007-508-02_1x02_P5.08mm_Horizontal",
         pins={"1": "VMOT_IN", "2": "PGND"}, assembly=False),
    # 高边 P-MOS 防反接：漏极接输入、源极接负载，栅极经 10k 拉到 PGND。
    # 极性正确时体二极管先导通，随后 Vgs≈-5V 使沟道完全导通
    Part("Q_REV", "AO3401A", "Transistor_FET:AO3401A", SOT23, "C15127",
         pins={"1": "REV_GATE", "2": "VMOT", "3": "VMOT_IN"}),
    res("R_REV", "10k", "REV_GATE", "PGND"),
    Part("D_VMOT_TVS", "SMBJ5.0A", "Device:D_Zener", "Diode_SMD:D_SMB", "C129528",
         pins={"1": "VMOT", "2": "PGND"}),
    # 电解电容：1 号焊盘为正极（设计方案 12.5 节）
    Part("C_VMOT_BULK", "1000uF 10V", "lcsc:RVT1A102M1010_C970713",
         "lcsc:CAP-SMD_BD10.0-L10.3-W10.3-LS11.3-FD", "C970713", pins={"1": "VMOT", "2": "PGND"}),
    Part("C_VMOT_HF", "100nF", "Device:C", C0402, "C1525", pins={"1": "VMOT", "2": "PGND"}),
    # 功率地与逻辑地的唯一汇合点（HC-2），调试时可拆
    res("R_STAR", "0", "PGND", "GND"),

    # ── 主 I2C 全板唯一一组上拉（HC-5）──
    res("R_SDA", "4.7k", "I2C_SDA", "+3V3"),
    res("R_SCL", "4.7k", "I2C_SCL", "+3V3"),

    # ── PCA9685：舵机 CH0/CH1、加热 CH15；地址 0x40（A0-A5 全接地）──
    Part("U_PWM", "PCA9685PW", "Driver_LED:PCA9685PW", "Package_SO:TSSOP-28_4.4x9.7mm_P0.65mm", "C2678753",
         pins={"1": "GND", "2": "GND", "3": "GND", "4": "GND", "5": "GND", "24": "GND",
               "6": "SERVO_L_PWM", "7": "SERVO_R_PWM", "22": "HEAT_PWM",
               **{p: nc("U_PWM", p) for p in ("8", "9", "10", "11", "12", "13",
                                               "15", "16", "17", "18", "19", "20", "21")},
               "14": "GND", "23": "PWM_OE", "25": "GND", "26": "I2C_SCL", "27": "I2C_SDA", "28": "+3V3"}),
    cap("C_PWM", "100nF", "+3V3", "GND"),
    # OE 低有效，常接地。预留测试点，改版时可接外部看门狗强制关断（设计方案 5.4 节）
    res("R_OE", "10k", "PWM_OE", "GND"),
    testpoint("TP_OE", "PWM_OE"),
    # 舵机插针顺序与原 PCA9685 模块一致：PWM / V+ / GND
    Part("J_SERVO_L", "Servo L", "Connector_Generic:Conn_01x03",
         "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
         pins={"1": "SERVO_L_PWM", "2": "VMOT", "3": "PGND"}, assembly=False),
    Part("J_SERVO_R", "Servo R", "Connector_Generic:Conn_01x03",
         "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
         pins={"1": "SERVO_R_PWM", "2": "VMOT", "3": "PGND"}, assembly=False),

    # ── 加热：板载低边 MOSFET（设计方案 5.2 节）──
    res("R_GATE", "100", "HEAT_PWM", "HEAT_GATE"),
    res("R_GATE_PD", "100k", "HEAT_GATE", "PGND"),      # HC-3
    Part("Q_HEAT", "AO3400A", "Transistor_FET:AO3400A", SOT23, "C20917",
         pins={"1": "HEAT_GATE", "2": "PGND", "3": "HEAT_LOW"}),
    # 脚 1 接 VMOT，经板外 KSD9700 到加热膜，回到脚 2（HC-6 丝印在 gen_pcb 中加）
    Part("J_HEAT", "Heater", "Connector_Generic:Conn_01x02",
         "Connector_JST:JST_VH_B2P-VH_1x02_P3.96mm_Vertical", pins={"1": "VMOT", "2": "HEAT_LOW"},
         assembly=False),
    testpoint("TP_GATE", "HEAT_GATE"),

    # ── 测温：ADS1115，地址 0x48（ADDR 接地）──
    Part("U_ADC", "ADS1115IDGSR", "Analog_ADC:ADS1115IDGS", "Package_SO:TSSOP-10_3x3mm_P0.5mm", "C37593",
         pins={"1": "GND", "2": nc("U_ADC", "ALERT"), "3": "GND", "4": "NTC_SENSE",
               "5": nc("U_ADC", "AIN1"), "6": nc("U_ADC", "AIN2"), "7": nc("U_ADC", "AIN3"),
               "8": "+3V3", "9": "I2C_SDA", "10": "I2C_SCL"}),
    cap("C_ADC", "100nF", "+3V3", "GND"),
    res("R_NTC", "10k", "+3V3", "NTC_SENSE"),
    cap("C_NTC", "100nF", "NTC_SENSE", "GND"),
    Part("J_NTC", "NTC 10K", "Connector_Generic:Conn_01x02",
         "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical", pins={"1": "NTC_SENSE", "2": "GND"},
         assembly=False),

    # ── 触摸：MPR121，地址 0x5A（ADDR 接地）；IRQ 无 GPIO 可接，悬空轮询 ──
    Part("U_TOUCH", "MPR121QR2", "Sensor_Touch:MPR121QR2", "Package_DFN_QFN:UQFN-20_3x3mm_P0.4mm", "C91322",
         pins={"1": nc("U_TOUCH", "IRQ"), "2": "I2C_SCL", "3": "I2C_SDA", "4": "GND",
               "5": "TOUCH_VREG", "6": "GND", "7": "TOUCH_REXT",
               **{str(8 + i): f"TOUCH_E{i}" for i in range(12)}, "20": "+3V3"}),
    cap("C_TOUCH", "100nF", "+3V3", "GND"),
    cap("C_TOUCH_VREG", "100nF", "TOUCH_VREG", "GND"),
    res("R_TOUCH_REXT", "75k", "TOUCH_REXT", "GND"),
    Part("J_TOUCH", "Head Touch", "Connector_Generic:Conn_01x02",
         "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical",
         pins={"1": "TOUCH_E0", "2": "GND"}, assembly=False),
    *[testpoint(f"TP_E{i}", f"TOUCH_E{i}") for i in range(1, 12)],

    # ── 运动：MPU-6050，地址 0x68（AD0 接地）；INT 无 GPIO 可接 ──
    Part("U_IMU", "MPU-6050", "Sensor_Motion:MPU-6050", "Sensor_Motion:InvenSense_QFN-24_4x4mm_P0.5mm", "C24112",
         pins={"1": "GND", **{p: nc("U_IMU", p) for p in ("2", "3", "4", "5", "14", "15", "16", "17",
                                                           "19", "21", "22")},
               "6": nc("U_IMU", "AUX_DA"), "7": nc("U_IMU", "AUX_CL"), "8": "+3V3", "9": "GND",
               "10": "IMU_REGOUT", "11": "GND", "12": nc("U_IMU", "INT"), "13": "+3V3",
               "18": "GND", "20": "IMU_CPOUT", "23": "I2C_SCL", "24": "I2C_SDA"}),
    cap("C_IMU", "100nF", "+3V3", "GND"),
    cap("C_IMU_VLOGIC", "10nF", "+3V3", "GND"),
    cap("C_IMU_REG", "100nF", "IMU_REGOUT", "GND"),
    cap("C_IMU_CP", "2.2nF", "IMU_CPOUT", "GND"),

    # ── 摄像头 FPC：按设计方案 12.2 节 24 针表；25/26 为固定焊盘接地 ──
    Part("J_CAM", "AFC01-S24FCA-00", "lcsc:AFC01-S24FCA-00", "lcsc:FPC-SMD_24P-P0.50_AFC01-S24FCA-00", "C262669",
         pins={"1": nc("J_CAM", "1"), "2": "GND", "3": "CAM_SIOD", "4": "+2V8", "5": "CAM_SIOC",
               "6": "CAM_RESET", "7": "CAM_VSYNC", "8": "CAM_PWDN", "9": "CAM_HREF", "10": "+1V5",
               "11": "+2V8", "12": "CAM_Y9", "13": "CAM_XCLK", "14": "CAM_Y8", "15": "GND",
               "16": "CAM_Y7", "17": "CAM_PCLK", "18": "CAM_Y6", "19": "CAM_Y2", "20": "CAM_Y5",
               "21": "CAM_Y3", "22": "CAM_Y4", "23": nc("J_CAM", "23"), "24": nc("J_CAM", "24"),
               "25": "GND", "26": "GND"}),
    # config.h 中 PWDN、RESET 均为 NC：PWDN 下拉常开，RESET 上拉到 DOVDD 并加上电延时
    res("R_CAM_PWDN", "10k", "CAM_PWDN", "GND"),
    res("R_CAM_RST", "10k", "+2V8", "CAM_RESET"),
    cap("C_CAM_RST", "100nF", "CAM_RESET", "GND"),
    cap("C_CAM_AVDD", "100nF", "+2V8", "GND"),
    cap("C_CAM_DVDD", "100nF", "+1V5", "GND"),
    # FPC 走线比面包板原型长，SCCB 使用外部 4.7k 上拉保证边沿与抗干扰能力
    res("R_SIOC", "4.7k", "CAM_SIOC", "+2V8"),
    res("R_SIOD", "4.7k", "CAM_SIOD", "+2V8"),

    # ── 双屏：8 针排针，顺序 RST CS DC SDA SCL GND VCC BL ──
    # CLK 与 MOSI 在 ESP32 端串 33Ω，两屏共用这两根线（设计方案 6.5 节）
    res("R_LCD_CLK", "33", "LCD_CLK", "LCD_CLK_S"),
    res("R_LCD_MOSI", "33", "LCD_MOSI", "LCD_MOSI_S"),
    # GPIO48 低电平导通 AO3401A，为两块屏的 BL 脚提供受控 3.3V；100k 上拉保证上电默认关闭。
    res("R_LCD_BL_GATE", "100", "LCD_BL_PWM", "LCD_BL_GATE"),
    res("R_LCD_BL_OFF", "100k", "+3V3", "LCD_BL_GATE"),
    Part("Q_LCD_BL", "AO3401A", "Transistor_FET:AO3401A", SOT23, "C15127",
         pins={"1": "LCD_BL_GATE", "2": "+3V3", "3": "LCD_BL"}),
    Part("J_LCD_L", "LCD L", "Connector_Generic:Conn_01x08",
         "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical",
         pins={"1": "LCD_RST", "2": "LCD_CS_L", "3": "LCD_DC", "4": "LCD_MOSI_S", "5": "LCD_CLK_S",
               "6": "GND", "7": "+3V3", "8": "LCD_BL"}, assembly=False),
    Part("J_LCD_R", "LCD R", "Connector_Generic:Conn_01x08",
         "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical",
         pins={"1": "LCD_RST", "2": "LCD_CS_R", "3": "LCD_DC", "4": "LCD_MOSI_S", "5": "LCD_CLK_S",
               "6": "GND", "7": "+3V3", "8": "LCD_BL"}, assembly=False),
    cap("C_LCD", "100nF", "+3V3", "GND"),

    # ── 麦克风：外接模块 ──
    # 2026-09-15 改为外接：板载麦克风要求主板本身放在玩偶能「听见」的位置，
    # 塞进胸腔包一层棉花就废了。拆解的成品机芯也是外接的。
    # 6 脚顺序按常见 I2S 麦克风模块丝印：VDD GND SD WS SCK L/R。
    # 末脚给 GND，即 L/R 拉低 = 左声道，与原板载 INMP441 的第 4 脚接法一致。
    # 兼容 INMP441 / ICS43434 / ZTS6672 等 I2S 数字麦克风模块（委托方 2026-09-15 确认）。
    # 同 J_EXT，交给机器贴。料号 BM06B-SRSS-TB(LF)(SN)，库存充足。
    Part("J_MIC", "Mic", "Connector_Generic:Conn_01x06",
         "Connector_JST:JST_SH_BM06B-SRSS-TB_1x06-1MP_P1.00mm_Vertical", "C160392",
         pins={"1": "+3V3", "2": "GND", "3": "MIC_SD", "4": "MIC_WS", "5": "MIC_SCK", "6": "GND"}),

    # ── 功放：MAX98357A，供电取 VBUS（设计方案 12.3 节）──
    # GAIN_SLOT 悬空为 9dB；SD_MODE 经 1MΩ 上拉到 VDD，工作在 (左+右)/2 模式
    Part("U_AMP", "MAX98357AETE+T", "Audio:MAX98357A", "Package_DFN_QFN:TQFN-16-1EP_3x3mm_P0.5mm_EP1.23x1.23mm",
         "C910544",
         pins={"1": "AMP_DIN", "2": nc("U_AMP", "GAIN"), "3": "GND", "4": "AMP_SD",
               "5": nc("U_AMP", "5"), "6": nc("U_AMP", "6"), "7": "VBUS", "8": "VBUS",
               "9": "SPK_P", "10": "SPK_N", "11": "GND", "12": nc("U_AMP", "12"),
               "13": nc("U_AMP", "13"), "14": "AMP_LRCLK", "15": "GND", "16": "AMP_BCLK", "17": "GND"}),
    res("R_AMP_SD", "1M", "VBUS", "AMP_SD"),
    cap10u("C_AMP_BULK", "VBUS", "GND"),
    cap("C_AMP", "100nF", "VBUS", "GND"),
    # BTL 差分输出，喇叭两端都不能接地
    Part("J_SPK", "Speaker", "Connector_Generic:Conn_01x02",
         "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical", pins={"1": "SPK_P", "2": "SPK_N"},
         assembly=False),

    # ── 测试点（设计方案第 9 节）──
    testpoint("TP_3V3", "+3V3"),
    testpoint("TP_VBUS", "VBUS"),
    testpoint("TP_VMOT", "VMOT"),
    testpoint("TP_GND", "GND"),
    testpoint("TP_PGND", "PGND"),
    testpoint("TP_SDA", "I2C_SDA"),
    testpoint("TP_SCL", "I2C_SCL"),
    testpoint("TP_TX", "UART_TX"),

    # ── 安装孔 M3 ──
    *[Part(f"H{i}", "M3", "Mechanical:MountingHole", "MountingHole:MountingHole_3.2mm_M3",
           assembly=False) for i in range(1, 5)],
]


def nets() -> dict[str, list[tuple[str, str]]]:
    result: dict[str, list[tuple[str, str]]] = {}
    for part in PARTS:
        if not part.fitted:
            continue
        for pin, net in part.pins.items():
            result.setdefault(net, []).append((part.ref, pin))
    return result
