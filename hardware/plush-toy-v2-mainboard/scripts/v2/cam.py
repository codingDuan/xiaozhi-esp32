"""C/D 摄像头族电路（spec §5.3、§7）。

FPC 焊盘与摄像头脚号必须分两级表达：一期实测 AFC01-S24FCA-00 下接座、
排线触点朝下时，摄像头第 k 脚落到板上第 25-k 脚。
"""
from v2 import parts_db as db
from v2.part import cap, res


CAMERA_PIN_SIGNALS: dict[int, str] = {
    1: "NC1", 2: "AGND", 3: "SIOD", 4: "DOVDD", 5: "SIOC", 6: "RESET",
    7: "VSYNC", 8: "PWDN", 9: "HREF", 10: "DVDD", 11: "AVDD", 12: "Y9",
    13: "XCLK", 14: "Y8", 15: "DGND", 16: "Y7", 17: "PCLK", 18: "Y6",
    19: "Y2", 20: "Y5", 21: "Y3", 22: "Y4", 23: "NC23", 24: "NC24",
}

CAMERA_PAD_TO_PIN: dict[str, int] = {str(pad): 25 - pad for pad in range(1, 25)}

CAMERA_SIGNAL_NETS = {
    "AGND": "GND", "DGND": "GND", "DOVDD": "+2V8", "AVDD": "+2V8", "DVDD": "+1V5",
    "SIOD": "CAM_SIOD", "SIOC": "CAM_SIOC", "RESET": "CAM_RESET", "VSYNC": "CAM_VSYNC",
    "PWDN": "CAM_PWDN", "HREF": "CAM_HREF", "XCLK": "CAM_XCLK", "PCLK": "CAM_PCLK",
    "Y2": "CAM_Y2", "Y3": "CAM_Y3", "Y4": "CAM_Y4", "Y5": "CAM_Y5",
    "Y6": "CAM_Y6", "Y7": "CAM_Y7", "Y8": "CAM_Y8", "Y9": "CAM_Y9",
}


def camera_connector() -> object:
    nets = {
        pad: CAMERA_SIGNAL_NETS[CAMERA_PIN_SIGNALS[camera_pin]]
        for pad, camera_pin in CAMERA_PAD_TO_PIN.items()
        if CAMERA_PIN_SIGNALS[camera_pin] in CAMERA_SIGNAL_NETS
    }
    nets.update({"25": "GND", "26": "GND"})
    return db.part("CAM_FPC", "J_CAM", nets)


def camera_parts() -> list:
    return [
        camera_connector(),
        db.part("LDO_2V8", "U_LDO28", {"VIN": "+3V3", "GND": "GND", "CE": "+3V3", "VOUT": "+2V8"}),
        cap("C_LDO28_IN", "1uF", "+3V3", "GND"),
        cap("C_LDO28_OUT", "1uF", "+2V8", "GND"),
        db.part("LDO_1V5", "U_LDO15", {"VIN": "+3V3", "GND": "GND", "CE": "+3V3", "VOUT": "+1V5"}),
        cap("C_LDO15_IN", "1uF", "+3V3", "GND"),
        cap("C_LDO15_OUT", "1uF", "+1V5", "GND"),
        res("R_CAM_PWDN", "10k", "CAM_PWDN", "GND"),
        res("R_CAM_RST", "10k", "+2V8", "CAM_RESET"),
        cap("C_CAM_RST", "100nF", "CAM_RESET", "GND"),
        cap("C_CAM_AVDD", "100nF", "+2V8", "GND"),
        cap("C_CAM_DVDD", "100nF", "+1V5", "GND"),
        res("R_SIOC", "4.7k", "CAM_SIOC", "+2V8"),
        res("R_SIOD", "4.7k", "CAM_SIOD", "+2V8"),
        db.part("MPR121", "U_TOUCH", {"SCL": "I2C_SCL", "SDA": "I2C_SDA", "ADDR": "GND",
                                        "VREG": "TOUCH_VREG", "VSS": "GND", "REXT": "TOUCH_REXT",
                                        "ELE0": "TOUCH_E0", "ELE4": "HEAT_GATE_DRV",
                                        "ELE5": "KEY_MUTE", "VDD": "+3V3"}),
        cap("C_TOUCH", "100nF", "+3V3", "GND"),
        cap("C_TOUCH_VREG", "100nF", "TOUCH_VREG", "GND"),
        res("R_TOUCH_REXT", "75k", "TOUCH_REXT", "GND"),
        db.part("ADS1115", "U_ADC", {"ADDR": "GND", "GND": "GND", "AIN0": "NTC_SENSE",
                                      "AIN1": "VBAT_SENSE", "AIN2": "CC_SENSE",
                                      "AIN3": "BAT_NTC_SENSE", "VDD": "+3V3",
                                      "SDA": "I2C_SDA", "SCL": "I2C_SCL"}),
        cap("C_ADC", "100nF", "+3V3", "GND"),
    ]
