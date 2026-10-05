"""版本 B 布局（不带摄像头 · 双面）。原点左上角，x 右 y 下，单位 mm，角度按 KiCad 约定。

分区（spec 第 6 节）：
- 左边：ESP32 模组，天线伸出左边板外
- 上边：触摸、按键、眼睛、麦克风四个出线座，开口朝上（往头部走）
- 右边：两只舵机、加热，开口朝右
- 下边：电池、USB-C、喇叭、测温，开口朝下；电池座在左下，远离加热与电源芯片
正面只放模组、出线座和按键；电源、功放、IMU 及所属阻容全部放背面。
起步采用 spec 给 B 的 42×34 mm 目标；首轮因 U1 与上下沿连接器、右侧三座的实际庭院层
无法同时满足 0.2 mm 间隙；39.5 mm 第二轮又无法容纳连接器引脚丝印；42×43 mm
第三轮的右上角引脚丝印互撞，因此最终起布尺寸调整为 45×43 mm。该迭代只属于 B，不回写 A。
"""

W, H = 45.0, 43.0
CORNER_R = 2.0
EDGE_MARGIN = 0.5          # 器件占位与板边的最小距离（U1 除外）
GAP = 0.2                  # 自动排布时器件占位之间额外留的间隙
# In2 内层：VSYS 平面只占右侧这块矩形（舵机、降压输入、加热侧），其余整层是 +3V3。
# 首轮 3V3 只铺左半边，右下角测温上拉等 3V3 小网络只能拉长线横穿全板
# 第 3 轮收小：左边让出降压电感的 3V3 输出端，上边让出上沿出线座（麦克风 3V3 脚）
# 第 4 轮（2026-10-05 去耦复查）：降压组挪到充电电感右侧后，VSYS 改为 L 形——右列（舵机、加热侧）加中下部
# （IP5306 VOUT、功放）；3V3 留左列（模组）、上沿与中上部（降压输出、IMU、按键上拉、屏背光）和下沿（测温上拉）。
# 旧矩形 x ≥ 37.5 时 VSYS 源头在矩形外，补线器只能用 0.2mm 细线；整块矩形时降压输出又绕 16.8mm 才进 3V3 平面
# 54mm 宽后降压输出焊盘落在 x 38–43：上段 VSYS 只留舵机座一条（x ≥ 45，舵机 5V 脚在 x 47.4）
VSYS_POLY = [(31.0, 7.0), (W, 7.0), (W, 27.0), (15.0, 27.0), (15.0, 16.0), (31.0, 16.0)]

# 出线座：位号 → (贴哪条边, 沿边坐标)。离板边的距离由 gen_pcb 按封装实际占位算，
# 开口方向随边而定（这些封装 0° 时开口都朝 +y）：上 180°、右 90°、下 0°、左 270°。
EDGE_CONNECTORS = {
    "J_TOUCH": ("top", 4.9),
    "J_LCD": ("top", 13.94),
    "J_MIC": ("top", 24.30),
    "J_KEY": ("top", 31.46),
    "J_ARM_L": ("right", 10.1),
    "J_ARM_R": ("right", 18.4),
    "J_HEAT": ("right", 27.45),
    "J_SPK": ("bottom", 18.0),
    "J_NTC": ("bottom", 12.0),
    "J_BAT": ("bottom", 25.5),
    "J_USB": ("bottom", 35.6),
}
EDGE_ANGLE = {"top": 180, "right": 90, "bottom": 0, "left": 270}

# 定点器件：位号 → (x, y, 角度)
ANCHORS = {
    # 模组转 90°，天线朝左伸出板外（一期同法：中心 x=6.75，板上只剩本体 x 0..20.2）
    "U1": (6.75, 22.0, 90),
    "H1": (28.2, 27.0, 0),
    "H2": (23.0, 27.0, 0),
    "SW_RST": (23.3, 16.0, 0),
    "SW_BOOT": (29.2, 16.0, 0),
    # 电源链按电流走向排成一串，避免宽电源线绕板（首轮布线 12 处开路多为电源线绕不过来）：
    # USB 座 → F_USB → U_EFUSE（USB 正上方）→ U_CHG + L_CHG（再往上）→ 电池保护 → 电池座（左下）
    "F_USB": (33.0, 30.0, 0),
    "U_EFUSE": (38.0, 30.0, 0),
    "U_CHG": (25.0, 21.0, 0),
    # 电感在芯片正上方：IP5306 的 SW(7)、BAT(6) 都在芯片上沿，电感两端正对这两脚
    "L_CHG": (30.0, 13.0, 0),
    "Q_BATP": (23.0, 35.0, 0),
    # 降压在 VSYS 平面一侧（x ≥ 36）取电，输出一小段线回到 3V3 区；功放贴着喇叭座
    "U_BUCK": (40.0, 17.0, 90),
    "U_AMP": (40.0, 25.0, 0),
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
    "C_SERVO1": "J_ARM_L",      # 上段 VSYS 只剩舵机座一条，电容贴着左臂座 5V 脚
    "C_SERVO2": "J_ARM_R", "C_SERVO3": "J_ARM_R",
    "U_IMU": (20.0, 16.0), "C_IMU": "U_IMU",
    "D_ESD_PWR": "J_KEY", "D_ESD_MUTE": "J_KEY", "R_KEY_MUTE_PU": "J_KEY",
    "D_ESD_TOUCH": "J_TOUCH", "C_TOUCH_FILT": "J_TOUCH",
}

# 双面版本装配规则：正面保留模组、其两颗本地去耦、所有出线座和两个按键。C_U1/C_U1_BULK
# 若翻到背面就不再是高频同面去耦，因此是“阻容放背面”规则的唯一电气完整性例外。
# 测试点和安装孔不属于装配件，仍分别由 BACK_NEAR 与 ANCHORS 管理，不列入 BACK_PARTS。
BACK_PARTS = (set(NEAR) | {
    "F_USB", "U_EFUSE", "U_CHG", "L_CHG", "Q_BATP", "U_BUCK", "U_AMP",
}) - {"C_U1", "C_U1_BULK"}

# 去耦电容、反馈网络：位号 → (所服务的器件, 网络, 焊盘到该器件同网络引脚的最大距离 mm[, 回流网络])。
# 两档：每个电源引脚的第一颗电容 ≤ 3mm（高频电流回路）；同一引脚的第二颗储能电容 ≤ 6mm。
# gen_pcb 先放这些件、从引脚处起找位置，超距直接报错。首版只按「附近」放，C_BUCK_HF 离引脚 9.9mm、
# 降压反馈网络 10mm，DRC 全过却没发现（2026-10-05 复查）
DECOUPLING = {
    # 顺序即放置顺序：挤在定点芯片四周的充电、eFuse 先放，降压组随后
    # VSYS 引脚在 IP5306 左上角、VBAT 在右上：VSYS 电容先占左上空隙，VBAT 电容去右上
    "C_VSYS1": ("U_CHG", "VSYS", 3.0), "C_VSYS2": ("U_CHG", "VSYS", 6.0),
    "C_CHG_VIN": ("U_CHG", "VUSB", 3.0), "C_CHG_BAT": ("U_CHG", "VBAT", 3.0),
    "C_EFUSE_IN": ("U_EFUSE", "VBUS_FUSED", 3.0), "C_VUSB": ("U_EFUSE", "VUSB", 3.0),
    "R_EFUSE_ILM": ("U_EFUSE", "EFUSE_ILM", 3.0),
    "C_EFUSE_DVDT": ("U_EFUSE", "EFUSE_DVDT", 6.0),   # 只定上电斜率，µA 级慢节点
    # 第 4 个元素为回流网络：该电容的地焊盘也要贴着芯片地脚（热回路两端都短）。高频电容先于电感放，占住 1/2 脚左侧
    "C_BUCK_HF": ("U_BUCK", "VSYS", 2.0, "GND"),
    "L_BUCK": ("U_BUCK", "BUCK_SW", 3.0),        # 开关节点回路越短越好
    "C_BUCK_IN": ("U_BUCK", "VSYS", 3.0),
    "R_FB1": ("U_BUCK", "BUCK_FB", 3.0), "R_FB2": ("U_BUCK", "BUCK_FB", 3.0), "C_FF": ("U_BUCK", "BUCK_FB", 3.0),
    "C_BUCK_OUT1": ("L_BUCK", "+3V3", 3.0), "C_BUCK_OUT2": ("L_BUCK", "+3V3", 6.0),
    "C_AMP": ("U_AMP", "VSYS", 3.0), "C_AMP_BULK": ("U_AMP", "VSYS", 6.0),
    "C_U1": ("U1", "+3V3", 3.0), "C_U1_BULK": ("U1", "+3V3", 6.0),
    "C_IMU": ("U_IMU", "+3V3", 3.0),
}

# 这些储能电容在引脚标注之后再放：先放会占住喇叭座引脚标注的位置（余量大，晚放也能满足距离）
DECOUPLING_AFTER_LEGENDS = {"C_AMP_BULK", "C_BUCK_OUT1", "C_BUCK_OUT2"}

# 开关电源热回路：(网络, (位号, 焊盘), (位号, 焊盘), 表层最长 mm)。post_route 补一段直连，不靠绕平面过孔回流
# （2026-10-05 复查：降压地脚扇不出过孔，地回流先走 5mm 表层到过孔、再经平面回到输入电容）
HOT_LOOPS = [
    ("GND", ("U_BUCK", "2"), ("C_BUCK_HF", "2"), 4.0),
]

# 测试点放背面：位号 → 背面目标点（在正面所连器件附近，方便对照）
# 背面上沿预留测试带，装配件排布时把整条带当成禁区；测试点最后按网络链路顺序落入。
# 这样每个点的镜像丝印仍可贴在自身旁边，不会被密集的双面装配件挤走。
BACK_RESERVATIONS = [(0.5, 0.5, W - 0.5, 8.0)]
BACK_NEAR = {
    "TP_VUSB": (2.0, 3.0), "TP_VSYS": (7.8, 3.0), "TP_VBAT": (13.6, 3.0),
    "TP_3V3": (19.4, 3.0), "TP_GND": (25.2, 3.0), "TP_CC": (31.0, 3.0),
    "TP_EN": (36.8, 3.0), "TP_BOOT": (42.6, 3.0),
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
    "J_ARM_L": "ARM L", "J_ARM_R": "ARM R", "J_HEAT": "HEAT\n串KSD9700",
    # J_BAT 极性看引脚旁的 +/−（国产座 1 脚在右，写「+/-」会和引脚标注反着读）
    "J_BAT": "BAT", "J_USB": "USB", "J_SPK": "SPK", "J_NTC": "NTC",
}
