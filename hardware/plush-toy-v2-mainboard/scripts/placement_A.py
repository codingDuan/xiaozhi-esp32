"""版本 A 布局（不带摄像头 · 单面）。原点左上角，x 右 y 下，单位 mm，角度按 KiCad 约定。

分区（spec 第 6 节）：
- 左边：ESP32 模组，天线伸出左边板外
- 上边：触摸、按键、眼睛、麦克风四个出线座，开口朝上（往头部走）
- 右边：两只舵机、加热，开口朝右
- 下边：电池、USB-C、喇叭、测温，开口朝下；电池座在左下，远离加热与电源芯片
起步尺寸来自 spec 第 2 节估算（52×42），加引脚标注后放大到 52×46，Task 9 逐轮收缩。
"""

W, H = 52.0, 46.0
CORNER_R = 2.0
EDGE_MARGIN = 0.5          # 器件占位与板边的最小距离（U1 除外）
GAP = 0.2                  # 自动排布时器件占位之间额外留的间隙
# In2 内层：VSYS 平面只占右侧这块矩形（舵机、降压输入、加热侧），其余整层是 +3V3。
# 首轮 3V3 只铺左半边，右下角测温上拉等 3V3 小网络只能拉长线横穿全板
# 第 3 轮收小：左边让出降压电感的 3V3 输出端，上边让出上沿出线座（麦克风 3V3 脚）
VSYS_RECT = (37.5, 9.0, W, 34.0)

# 出线座：位号 → (贴哪条边, 沿边坐标)。离板边的距离由 gen_pcb 按封装实际占位算，
# 开口方向随边而定（这些封装 0° 时开口都朝 +y）：上 180°、右 90°、下 0°、左 270°。
EDGE_CONNECTORS = {
    "J_TOUCH": ("top", 9.1),
    "J_LCD": ("top", 25.0),
    "J_MIC": ("top", 36.5),
    "J_KEY": ("top", 15.2),
    "J_ARM_L": ("right", 11.5),
    "J_ARM_R": ("right", 20.0),
    "J_HEAT": ("right", 29.5),
    "J_BAT": ("bottom", 14.0),
    "J_USB": ("bottom", 28.8),
    "J_SPK": ("bottom", 39.2),
    "J_NTC": ("bottom", 47.05),
}
EDGE_ANGLE = {"top": 180, "right": 90, "bottom": 0, "left": 270}

# 定点器件：位号 → (x, y, 角度)
ANCHORS = {
    # 模组转 90°，天线朝左伸出板外（一期同法：中心 x=6.75，板上只剩本体 x 0..20.2）
    "U1": (6.75, 21.0, 90),
    "H1": (3.5, 3.5, 0),
    "H2": (3.5, H - 3.5, 0),
    "SW_RST": (23.5, 14.5, 0),
    "SW_BOOT": (23.5, 19.0, 0),
    # 电源链按电流走向排成一串，避免宽电源线绕板（首轮布线 12 处开路多为电源线绕不过来）：
    # USB 座 → F_USB → U_EFUSE（USB 正上方）→ U_CHG + L_CHG（再往上）→ 电池保护 → 电池座（左下）
    "F_USB": (28.6, 34.3, 0),
    "U_EFUSE": (32.8, 34.3, 0),
    "U_CHG": (31.0, 29.0, 0),
    # 电感在芯片正上方：IP5306 的 SW(7)、BAT(6) 都在芯片上沿，电感两端正对这两脚
    "L_CHG": (31.0, 22.0, 0),
    "Q_BATP": (23.5, 33.5, 0),
    # 降压在 VSYS 平面一侧（x ≥ 36）取电，输出一小段线回到 3V3 区；功放贴着喇叭座
    "U_BUCK": (38.5, 22.5, 0),
    "U_AMP": (36.6, 33.0, 0),
}

# 其余器件放在所连主器件附近（gen_pcb 从目标点螺旋向外找空位）
NEAR = {
    "C_U1_BULK": "U1", "C_U1": "U1", "R_EN": "SW_RST", "C_EN": "SW_RST", "R_BOOT": "SW_BOOT",
    "R_SCL": "U_IMU", "R_SDA": "U_IMU", "R_SERVO_R_PD": "J_ARM_R",
    "R_CC1": "J_USB", "R_CC2": "J_USB", "R_CC_SUM1": "J_USB", "R_CC_SUM2": "J_USB",
    "C_CC_SENSE": "J_USB", "D_USB_DP": "J_USB", "D_USB_DN": "J_USB",     "C_EFUSE_IN": "U_EFUSE", "C_EFUSE_DVDT": "U_EFUSE",
    "R_EFUSE_ILM": "U_EFUSE", "C_VUSB": "U_EFUSE",
    "C_CHG_VIN": "U_CHG", "C_CHG_BAT": "U_CHG",
    "C_VSYS1": "U_CHG", "C_VSYS2": "U_CHG",
    "R_BATP_PU": "Q_BATP", "Q_BATN": "Q_BATP", "R_BATN_G": "Q_BATN",
    "R_BATN_PD": "Q_BATN", "R_BATP_BYP": "Q_BATP",
    "R_VBAT_TOP": "J_BAT", "R_VBAT_BOT": "J_BAT", "C_VBAT_SENSE": "J_BAT",
    "RT_BAT": "J_BAT", "R_BAT_NTC": "RT_BAT", "C_BAT_NTC": "RT_BAT",
    "L_BUCK": "U_BUCK", "R_FB1": "U_BUCK",
    "R_FB2": "U_BUCK", "C_FF": "U_BUCK", "C_BUCK_IN": "U_BUCK", "C_BUCK_HF": "U_BUCK",
    "C_BUCK_OUT1": "U_BUCK", "C_BUCK_OUT2": "U_BUCK",
    "Q_HEAT": "J_HEAT", "R_GATE": "Q_HEAT", "R_GATE_PD": "Q_HEAT",
    "R_NTC": "J_NTC", "C_NTC": "J_NTC",
    "R_LCD_MOSI": "J_LCD", "R_LCD_CLK": "J_LCD", "Q_LCD_BL": "J_LCD", "R_LCD_BL_GATE": "Q_LCD_BL",
    "R_LCD_BL_OFF": "Q_LCD_BL", "C_LCD": "J_LCD",
    "C_MIC": "J_MIC",
    "R_AMP_SD": "U_AMP", "C_AMP_BULK": "U_AMP", "C_AMP": "U_AMP",
    "C_SERVO1": (41.5, 13.5),   # 放在 VSYS 平面内，就近打孔接平面
    "C_SERVO2": "J_ARM_R", "C_SERVO3": "J_ARM_R",
    "U_IMU": (28.0, 24.0), "C_IMU": "U_IMU",
    "D_ESD_PWR": "J_KEY", "D_ESD_MUTE": "J_KEY", "R_KEY_MUTE_PU": "J_KEY",
    "D_ESD_TOUCH": "J_TOUCH", "C_TOUCH_FILT": "J_TOUCH",
}

# 测试点放背面：位号 → 背面目标点（在正面所连器件附近，方便对照）
BACK_NEAR = {
    "TP_VUSB": "U_EFUSE", "TP_VSYS": "U_CHG", "TP_VBAT": "J_BAT", "TP_3V3": "U_BUCK",
    "TP_GND": "U_BUCK", "TP_CC": "J_USB", "TP_EN": "SW_RST", "TP_BOOT": "SW_BOOT",
}

# 引脚标注：位号 → 按焊盘号 1、2、3… 的顺序。gen_pcb 把每个字贴在对应焊盘朝板内一侧，
# 按焊盘实际坐标放，不会印反（委托方 2026-10-05 要求：引脚旁标 GND 等简要说明）
PIN_LEGEND = {
    # 1mm 间距的座子两排交错，标注限 2 个字符：RS=复位 DA=数据 CK=时钟 3V=3.3V PW=电源键 MU=收音键
    "J_TOUCH": ["E0", "G"],
    "J_LCD": ["RS", "CS", "DC", "DA", "CK", "G", "3V", "BL"],
    "J_MIC": ["3V", "G", "SD", "WS", "CK", "G"],
    "J_KEY": ["PW", "MU", "G"],
    "J_ARM_L": ["S", "5V", "G"],
    "J_ARM_R": ["S", "5V", "G"],
    "J_HEAT": ["+", "-"],      # 1 脚接 VUSB 5V，2 脚接加热开关管
    "J_BAT": ["+", "-"],
    "J_SPK": ["+", "-"],
    "J_NTC": ["NT", "G"],
}

# 出线座旁的功能名丝印：位号 → 文字。gen_pcb 放在引脚标注外侧
CONNECTOR_LABELS = {
    "J_TOUCH": "TOUCH", "J_LCD": "LCD", "J_MIC": "MIC", "J_KEY": "KEY",
    "J_ARM_L": "ARM L", "J_ARM_R": "ARM R", "J_HEAT": "HEAT 串KSD9700",
    "J_BAT": "BAT +/-", "J_USB": "USB", "J_SPK": "SPK", "J_NTC": "NTC",
}
