"""PCB 放置：关键器件定点，其余按「靠近谁」由 gen_pcb 自动排布。

坐标原点在板子左上角，x 向右，y 向下，单位 mm。角度按 KiCad 约定，正值为屏幕上逆时针。
板子 90×60mm 单面贴片（设计方案 11 节）。分区按设计方案第 7 节：天线在左端伸出板边，
功率区在右端，传感器与逻辑在中间。

几何依据（KiCad 10 官方封装实测）：
- U1 ESP32-S3-WROOM-1：天线在局部 -y。转 90° 后天线朝左；模组中心放 x=6.75，
  天线段与整个净空区（局部 y -27.75..-6.75）全部落在板外，板上只剩模组本体 x 0..20.2。
- USB-C（HRO TYPE-C-31-M-12）：信号焊盘在局部 -y，开口朝 +y；转 180° 开口朝上边。
- FPC（AFC01-S24FCA-00）：信号焊盘在局部 -y，排线从 -y 插入；转 180° 排线从下边插入。
- 排针：原点在 1 脚，转 90° 后引脚沿 +x 排开。
"""

W, H = 90.0, 60.0
EDGE_MARGIN = 0.5          # 除 U1 外，器件焊盘与板边的最小距离
GAP = 0.2                  # 自动排布时器件庭院层之间额外留的间隙

# 定点器件：位号 → (x, y, 角度)
ANCHORS = {
    # 左端：模组，天线伸出左边
    "U1": (6.75, 30.0, 90),
    "SW_RST": (12.0, 6.0, 0),
    "SW_BOOT": (12.0, 13.0, 0),
    "D_LED": (18.0, 16.0, 0),
    "U_MIC": (14.0, 50.0, 0),
    # 上边：USB-C、降压、两块圆屏的排针（屏线往上走向头部）
    "J_USB": (28.0, 4.7, 180),        # 开口距上边 0.5mm，满足 EDGE_MARGIN
    "U_BUCK": (37.0, 9.0, 0),
    "J_LCD_L": (47.0, 2.5, 90),
    "J_LCD_R": (47.0, 7.5, 90),
    # 中部：传感器
    "U_IMU": (46.0, 30.0, 0),
    "U_TOUCH": (30.0, 46.0, 0),
    "U_PWM": (62.0, 25.6, 0),         # 实测 C_VMOT_BULK 占位下沿 y=20.11，留出 GAP 0.2
    "R_STAR": (66.0, 32.0, 90),
    # 下边：摄像头 FPC 与两颗 LDO、功放
    "J_CAM": (40.0, 57.4, 180),
    "U_LDO28": (26.0, 53.0, 0),
    "U_LDO15": (52.0, 56.0, 0),
    "U_AMP": (54.0, 50.0, 0),
    "J_SPK": (62.0, 55.0, 0),
    # 右端功率区：VMOT 输入、大电容、舵机、加热、测温
    # 占位按「庭院层 ∪ 焊盘」计：电解电容焊盘到 ±6.75mm，比庭院层（±5.2mm）宽
    "C_VMOT_BULK": (70.5, 14.8, 0),   # 上沿让开圆屏排针（y≈9.3），右沿让开 J_VMOT
    "J_VMOT": (83.3, 16.5, 90),       # 让开 H3 庭院层（下沿 y=7.5），右沿距板边 ≥ 0.5mm
    "J_SERVO_L": (86.0, 23.0, 0),
    "J_SERVO_R": (86.0, 32.0, 0),
    "J_HEAT": (84.5, 43.0, 270),
    "Q_HEAT": (76.0, 44.0, 0),
    "U_ADC": (70.0, 48.0, 0),
    "J_NTC": (74.0, 55.0, 0),
    # 安装孔：M3 庭院层 7×7mm，中心距板边 4mm 才满足 EDGE_MARGIN
    "H1": (4.0, 4.0, 0),
    "H2": (4.0, 56.0, 0),
    "H3": (86.0, 4.0, 0),
    "H4": (86.0, 56.0, 0),
}

# 自动排布：位号 → 靠近的定点器件位号，或直接给一个坐标
NEAR = {
    "C_U1_BULK": (23.0, 22.0), "C_U1": (23.0, 25.0),
    "R_EN": "SW_RST", "C_EN": "SW_RST", "R_BOOT": "SW_BOOT", "C_LED": "D_LED",
    # I2C 上拉靠近 ESP32（设计方案 6.4 节）
    "R_SDA": (23.0, 32.0), "R_SCL": (23.0, 34.0), "TP_SDA": (23.0, 38.0), "TP_SCL": (26.0, 38.0),
    "R_CC1": "J_USB", "R_CC2": "J_USB", "F_USB": "J_USB", "D_USB_DP": "J_USB", "D_USB_DN": "J_USB",
    "TP_VBUS": "J_USB",
    "R_BUCK_EN": "U_BUCK", "L_BUCK": "U_BUCK", "C_BUCK_IN": "U_BUCK", "C_BUCK_OUT1": "U_BUCK",
    "C_BUCK_OUT2": "U_BUCK", "R_FB1": "U_BUCK", "R_FB2": "U_BUCK", "C_FF": "U_BUCK", "TP_3V3": "U_BUCK",
    "C_LDO28_IN": "U_LDO28", "C_LDO28_OUT": "U_LDO28", "C_LDO15_IN": "U_LDO15", "C_LDO15_OUT": "U_LDO15",
    "Q_REV": "J_VMOT", "R_REV": "J_VMOT", "D_VMOT_TVS": "C_VMOT_BULK", "C_VMOT_HF": "C_VMOT_BULK",
    "TP_VMOT": "J_VMOT", "TP_PGND": "R_STAR", "TP_GND": "R_STAR",
    "C_PWM": "U_PWM", "R_OE": "U_PWM", "TP_OE": "U_PWM",
    "R_GATE": "Q_HEAT", "R_GATE_PD": "Q_HEAT", "TP_GATE": "Q_HEAT",
    "C_ADC": "U_ADC", "R_NTC": "U_ADC", "C_NTC": "U_ADC",
    "C_TOUCH": "U_TOUCH", "C_TOUCH_VREG": "U_TOUCH", "R_TOUCH_REXT": "U_TOUCH",
    **{f"TP_E{i}": (30.0, 38.0) for i in range(12)},
    "C_IMU": "U_IMU", "C_IMU_VLOGIC": "U_IMU", "C_IMU_REG": "U_IMU", "C_IMU_CP": "U_IMU",
    "R_CAM_PWDN": "J_CAM", "R_CAM_RST": "J_CAM", "C_CAM_RST": "J_CAM", "C_CAM_AVDD": "J_CAM",
    "C_CAM_DVDD": "J_CAM",
    "R_LCD_CLK": "J_LCD_L", "R_LCD_MOSI": "J_LCD_L", "C_LCD": "J_LCD_L",
    "R_MIC_SD": "U_MIC", "C_MIC": "U_MIC",
    "R_AMP_SD": "U_AMP", "C_AMP_BULK": "U_AMP", "C_AMP": "U_AMP",
    "TP_TX": (23.0, 42.0),
}

# 硬约束 HC-6：加热插座旁的丝印（设计方案 5.3 节）。
# 不能写 ℃：KiCad 内置笔画字体没有这个字形，渲染与 Gerber 里都是方框（2026-09-14 实测）。
# 位置放在 J_SERVO_R 下沿（y≈38.9）与 J_HEAT 上沿（y≈40.5）之间的空隙左侧，不压插座丝印
HEATER_SILK = ("必须串 KSD9700 65度 常闭", 70.0, 39.6)
