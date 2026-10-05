"""版本 C 布局（摄像头、单面）。原点左上角，单位 mm。

60×45 mm 是 spec 的起步尺寸；60×50 mm 首轮布线在相机并行总线上稳定留下 7 个开路。
制造布局因此扩到 65×55 mm，给 J_CAM 与 U1 之间留出连续布线通道。
J_CAM 与全部线束连接器均在正面板边、卧式贴装；
摄像头两路 LDO 与去耦集中在上沿连接器下方，所有其余装配器件也只放正面。
"""

W, H = 65.0, 55.0
CORNER_R = 2.0
EDGE_MARGIN = 0.5
GAP = 0.2
# 0.5 mm 间距相机座逃逸区需要细栅格；其他网络保持 0.10 mm，
# 避免扬声器等跨板搜索把全板节点数放大四倍。
ROUTING_GRID = {"CAM_SIOC": 0.05, "+1V5": 0.05, "CAM_RESET": 0.05, "BATN_GATE": 0.05}
ROUTING_MARGIN = {"+1V5": 4.0, "CAM_RESET": 4.0, "BATN_GATE": 4.0}
VSYS_POLY = [(54.0, 8.0), (W, 8.0), (W, 22.0), (47.5, 22.0),
             (47.5, H), (40.0, H), (40.0, 21.5), (54.0, 21.5)]

EDGE_CONNECTORS = {
    "J_CAM": ("top", 12.5),
    "J_TOUCH": ("top", 24.5),
    "J_LCD": ("top", 35.0),
    "J_MIC": ("top", 49.0),
    "J_KEY": ("top", 60.0),
    "J_ARM_L": ("right", 14.5),
    "J_ARM_R": ("right", 26.0),
    "J_HEAT": ("bottom", 58.0),
    "J_BAT": ("bottom", 13.0),
    "J_USB": ("bottom", 30.0),
    "J_SPK": ("bottom", 43.5),
    "J_NTC": ("bottom", 49.7),
}
EDGE_ANGLE = {"top": 180, "right": 90, "bottom": 0, "left": 270}

ANCHORS = {
    "U1": (6.75, 30.0, 90),
    "H1": (43.0, 10.0, 0),
    "H2": (3.5, H - 3.5, 0),
    "SW_RST": (27.0, 19.0, 0),
    "SW_BOOT": (33.0, 19.0, 0),
    "U_LDO28": (8.0, 14.0, 0),
    "U_LDO15": (16.0, 14.0, 0),
    # 竖放且左移，给 J_CAM.19 的 RESET 留出直向下方逃逸通道。
    "R_SIOC": (8.0, 8.5, 90),
    "R_SIOD": (6.0, 10.5, 90),
    "R_CAM_RST": (9.25, 11.0, 90),
    "R_SCL": (22.0, 26.5, 0),
    "R_SDA": (24.2, 26.5, 0),
    "U_TOUCH": (26.0, 31.0, 0),
    "U_ADC": (36.5, 31.0, 180),
    "F_USB": (29.0, 40.0, 0),
    "U_EFUSE": (35.0, 40.0, 0),
    "U_CHG": (44.0, 34.0, 0),
    "L_CHG": (38.0, 25.0, 0),
    "Q_BATP": (21.0, 43.0, 0),
    # 与 RT_BAT 并排：两者的 BAT_NTC_SENSE 脚向下相对，GND 脚向上相对。
    "C_BAT_NTC": (20.0, 48.5, 90),
    # SDA 脚朝 U_ADC/总线区，避免被 QFN 相邻脚封死。
    "U_IMU": (31.0, 37.5, 270),
    "U_BUCK": (47.0, 18.0, 90),
    "U_AMP": (40.0, 44.5, 0),
}

NEAR = {
    "C_U1_BULK": "U1", "C_U1": "U1", "R_EN": "SW_RST", "C_EN": "SW_RST",
    "R_BOOT": "SW_BOOT",
    "R_SERVO_R_PD": "J_ARM_R",
    "R_CC1": "J_USB", "R_CC2": "J_USB", "R_CC_SUM1": "J_USB", "R_CC_SUM2": "J_USB",
    "C_CC_SENSE": "J_USB", "D_USB_DP": "J_USB", "D_USB_DN": "J_USB",
    "C_EFUSE_IN": "U_EFUSE", "C_EFUSE_DVDT": "U_EFUSE", "R_EFUSE_ILM": "U_EFUSE",
    "C_VUSB": "U_EFUSE", "C_CHG_VIN": "U_CHG", "C_CHG_BAT": "U_CHG",
    "C_VSYS1": "U_CHG", "C_VSYS2": "U_CHG",
    "R_BATP_PU": "Q_BATP", "Q_BATN": "Q_BATP", "R_BATN_G": "Q_BATN",
    "R_BATN_PD": "Q_BATN", "R_BATP_BYP": "Q_BATP",
    "R_VBAT_TOP": "J_BAT", "R_VBAT_BOT": "J_BAT", "C_VBAT_SENSE": "J_BAT",
    "RT_BAT": "J_BAT", "R_BAT_NTC": "RT_BAT", "C_BAT_NTC": "RT_BAT",
    "L_BUCK": "U_BUCK", "R_FB1": "U_BUCK", "R_FB2": "U_BUCK", "C_FF": "U_BUCK",
    "C_BUCK_IN": "U_BUCK", "C_BUCK_HF": "U_BUCK", "C_BUCK_OUT1": "U_BUCK",
    "C_BUCK_OUT2": "U_BUCK",
    "Q_HEAT": "J_HEAT", "R_GATE": "Q_HEAT", "R_GATE_PD": "Q_HEAT",
    "R_NTC": "J_NTC", "C_NTC": "J_NTC",
    "R_LCD_MOSI": "J_LCD", "R_LCD_CLK": "J_LCD", "Q_LCD_BL": "J_LCD",
    "R_LCD_BL_GATE": "Q_LCD_BL", "R_LCD_BL_OFF": "Q_LCD_BL", "C_LCD": "J_LCD",
    "C_MIC": "J_MIC", "R_AMP_SD": "U_AMP", "C_AMP_BULK": "U_AMP", "C_AMP": "U_AMP",
    "C_SERVO1": "J_ARM_L", "C_SERVO2": "J_ARM_R", "C_SERVO3": "J_ARM_R",
    "U_IMU": (31.0, 38.0), "C_IMU": "U_IMU",
    "D_ESD_PWR": "J_KEY", "D_ESD_MUTE": "J_KEY", "R_KEY_MUTE_PU": "J_KEY",
    "D_ESD_TOUCH": "J_TOUCH",
    "C_LDO28_IN": "U_LDO28", "C_LDO28_OUT": "U_LDO28",
    "C_LDO15_IN": "U_LDO15", "C_LDO15_OUT": "U_LDO15",
    "R_CAM_PWDN": "J_CAM", "C_CAM_RST": "J_CAM",
    "C_CAM_AVDD": "J_CAM", "C_CAM_DVDD": "J_CAM",
    "C_TOUCH": "U_TOUCH", "C_TOUCH_VREG": "U_TOUCH", "R_TOUCH_REXT": "U_TOUCH",
    "C_ADC": "U_ADC",
}

DECOUPLING = {
    "C_VSYS1": ("U_CHG", "VSYS", 3.0), "C_VSYS2": ("U_CHG", "VSYS", 6.0),
    "C_CHG_VIN": ("U_CHG", "VUSB", 3.0), "C_CHG_BAT": ("U_CHG", "VBAT", 3.0),
    "C_EFUSE_IN": ("U_EFUSE", "VBUS_FUSED", 3.0), "C_VUSB": ("U_EFUSE", "VUSB", 3.0),
    "R_EFUSE_ILM": ("U_EFUSE", "EFUSE_ILM", 3.0),
    "C_EFUSE_DVDT": ("U_EFUSE", "EFUSE_DVDT", 6.0),
    "C_BUCK_HF": ("U_BUCK", "VSYS", 2.0, "GND"), "L_BUCK": ("U_BUCK", "BUCK_SW", 3.0),
    "C_BUCK_IN": ("U_BUCK", "VSYS", 3.0), "R_FB1": ("U_BUCK", "BUCK_FB", 3.0),
    "R_FB2": ("U_BUCK", "BUCK_FB", 3.0), "C_FF": ("U_BUCK", "BUCK_FB", 3.0),
    "C_BUCK_OUT1": ("L_BUCK", "+3V3", 3.0), "C_BUCK_OUT2": ("L_BUCK", "+3V3", 6.0),
    "C_AMP": ("U_AMP", "VSYS", 3.0), "C_AMP_BULK": ("U_AMP", "VSYS", 6.0),
    "C_U1": ("U1", "+3V3", 3.0), "C_U1_BULK": ("U1", "+3V3", 6.0),
    "C_IMU": ("U_IMU", "+3V3", 3.0),
    "C_LDO28_IN": ("U_LDO28", "+3V3", 3.0), "C_LDO28_OUT": ("U_LDO28", "+2V8", 3.0),
    "C_LDO15_IN": ("U_LDO15", "+3V3", 3.0), "C_LDO15_OUT": ("U_LDO15", "+1V5", 3.0),
    "C_CAM_AVDD": ("J_CAM", "+2V8", 3.0), "C_CAM_DVDD": ("J_CAM", "+1V5", 3.0),
    "C_TOUCH": ("U_TOUCH", "+3V3", 3.0), "C_TOUCH_VREG": ("U_TOUCH", "TOUCH_VREG", 3.0),
    "C_ADC": ("U_ADC", "+3V3", 3.0),
}

# 密集的两颗传感器去耦固定在各自电源脚朝外一侧，避免自动搜索彼此抢占唯一通道。
DECOUPLING_ANCHORS = {
    "C_CAM_AVDD": (11.75, 8.0, 270),
    "C_CAM_DVDD": (10.5, 8.0, 270),
    "C_TOUCH_VREG": (22.5, 33.5, 180),
    "C_ADC": (32.2, 31.0, 180),
    # 输出脚落在 x=53.5，避开 x≥54 的 VSYS 平面，直接进 +3V3 区。
    "L_BUCK": (52.0, 19.15, 0),
}

DECOUPLING_AFTER_LEGENDS = {"C_AMP_BULK", "C_BUCK_OUT1", "C_BUCK_OUT2"}
HOT_LOOPS = [("GND", ("U_BUCK", "2"), ("C_BUCK_HF", "2"), 4.0)]

# 0.5mm FPC 与 UQFN 密脚的平面逃逸点；位置经净距检查后才会写入。
FANOUT_ANCHORS = {
    ("J_CAM", "23"): (7.25, 7.50),
    ("U_TOUCH", "4"): (23.80, 31.40),
    ("R_CC1", "2"): (24.00, 49.50),
    ("C_EFUSE_DVDT", "2"): (34.90, 38.80),
}

BACK_NEAR = {
    "TP_VUSB": "U_EFUSE", "TP_VSYS": "U_CHG", "TP_VBAT": "J_BAT", "TP_3V3": "U_BUCK",
    "TP_GND": "U_BUCK", "TP_CC": "J_USB", "TP_EN": "SW_RST", "TP_BOOT": "SW_BOOT",
}

PIN_LEGEND = {
    "J_TOUCH": ["E0", "G"], "J_LCD": ["RS", "CS", "DC", "DA", "CK", "G", "3V", "BL"],
    "J_MIC": ["3V", "G", "SD", "WS", "CK", "G"], "J_KEY": ["PW", "MU", "G"],
    "J_ARM_L": ["S", "5V", "G"], "J_ARM_R": ["S", "5V", "G"], "J_HEAT": ["+", "-"],
    "J_BAT": ["+", "-"], "J_SPK": ["+", "-"], "J_NTC": ["NT", "G"],
}

CONNECTOR_LABELS = {
    "J_TOUCH": "TOUCH", "J_LCD": "LCD", "J_MIC": "MIC", "J_KEY": "KEY",
    "J_ARM_L": "ARM L", "J_ARM_R": "ARM R", "J_HEAT": "HEAT\n串KSD9700",
    "J_BAT": "BAT", "J_USB": "USB", "J_SPK": "SPK", "J_NTC": "NTC",
}

# J_CAM 封装本身已有“FPC触点朝下”和插入箭头，不再额外占用一块 CAM 丝印。
SELF_LABELLED_CONNECTORS = {"J_CAM"}
