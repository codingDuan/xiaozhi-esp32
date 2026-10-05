"""A/B：触摸、ADC、加热栅极、收音键都直接接 ESP32（spec 5.2）。
这些网络已由 core 的 U1 按 gpio.NOCAM 接到模组，这里只补滤波。"""
from v2.part import cap


def nocam_parts() -> list:
    # C_TOUCH_FILT 取值需在 A 首板上按片上触摸灵敏度复核（TESTING.md 验收项）
    return [
        cap("C_TOUCH_FILT", "10nF", "TOUCH_E0", "GND"),
    ]
