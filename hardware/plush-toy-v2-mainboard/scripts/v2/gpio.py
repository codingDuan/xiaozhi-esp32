"""spec 第 5 节 GPIO 表。固件 plush-toy-v2 的 config.h 以此为准。"""

COMMON = {
    0: "BOOT",
    38: "LCD_CLK", 14: "LCD_MOSI", 47: "LCD_DC", 45: "LCD_CS", 21: "LCD_RST", 48: "LCD_BL_PWM",
    1: "MIC_WS", 2: "MIC_SCK", 42: "MIC_SD",
    39: "AMP_DIN", 40: "AMP_BCLK", 41: "AMP_LRCLK",
    # 一期 SCL 在 GPIO3；二期挪到 43：ROM 启动日志只动 SCL，SDA 保持高，不构成起始条件
    43: "I2C_SCL", 44: "I2C_SDA",
    3: "SERVO_L_PWM", 46: "SERVO_R_PWM",
    19: "USB_DN", 20: "USB_DP",
}

NOCAM = {
    17: "HEAT_GATE_DRV", 18: "KEY_MUTE", 8: "TOUCH_E0",
    4: "NTC_SENSE", 5: "VBAT_SENSE", 6: "CC_SENSE", 7: "BAT_NTC_SENSE",
}

# 摄像头数据线沿用一期 config.h 的 Y2–Y9 命名（D0=Y2 … D7=Y9）
CAM = {
    4: "CAM_SIOD", 5: "CAM_SIOC", 6: "CAM_VSYNC", 7: "CAM_HREF", 15: "CAM_XCLK", 13: "CAM_PCLK",
    11: "CAM_Y2", 9: "CAM_Y3", 8: "CAM_Y4", 10: "CAM_Y5", 12: "CAM_Y6", 18: "CAM_Y7",
    17: "CAM_Y8", 16: "CAM_Y9",
}

# ESP32-S3-WROOM-1 模组焊盘号 → GPIO，出自 esp32-s3-wroom-1_wroom-1u_datasheet_en v1.8 表 3-1
WROOM_PAD_GPIO = {
    "4": 4, "5": 5, "6": 6, "7": 7, "8": 15, "9": 16, "10": 17, "11": 18, "12": 8,
    "13": 19, "14": 20, "15": 3, "16": 46, "17": 9, "18": 10, "19": 11, "20": 12,
    "21": 13, "22": 14, "23": 21, "24": 47, "25": 48, "26": 45, "27": 0,
    "31": 38, "32": 39, "33": 40, "34": 41, "35": 42, "36": 44, "37": 43, "38": 2, "39": 1,
}


def for_family(camera: bool) -> dict[int, str]:
    table = dict(COMMON)
    table.update(CAM if camera else NOCAM)
    return table
