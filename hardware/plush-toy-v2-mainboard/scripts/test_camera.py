"""C/D 摄像头族电路安全检查。期望值来自 spec §5.3、§7 和一期实测反序关系。"""
import unittest

from v2 import cam, gpio, variants


class CameraConnectorTests(unittest.TestCase):
    def test_fpc_pad_order_matches_measured_reverse_connection(self):
        # 若换座子或误恢复一期同序接法，本测试必须失败。
        self.assertEqual(cam.CAMERA_PAD_TO_PIN, {
            "1": 24, "2": 23, "3": 22, "4": 21, "5": 20, "6": 19,
            "7": 18, "8": 17, "9": 16, "10": 15, "11": 14, "12": 13,
            "13": 12, "14": 11, "15": 10, "16": 9, "17": 8, "18": 7,
            "19": 6, "20": 5, "21": 4, "22": 3, "23": 2, "24": 1,
        })

    def test_camera_power_and_ground_semantics_land_on_reversed_pads(self):
        # 电源/地语义或反序焊盘错一位，本测试必须失败。
        actual = {pad: cam.CAMERA_PIN_SIGNALS[pin] for pad, pin in cam.CAMERA_PAD_TO_PIN.items()
                  if cam.CAMERA_PIN_SIGNALS[pin] in {"DVDD", "AVDD", "DOVDD", "AGND", "DGND"}}
        self.assertEqual(actual,
                         {"10": "DGND", "14": "AVDD", "15": "DVDD", "21": "DOVDD", "23": "AGND"})

    def test_camera_power_pads_never_connect_to_esp32_gpio(self):
        # 任一摄像头电源脚直接接到 CAM GPIO，本测试必须失败。
        j_cam = next(p for p in variants.parts("C") if p.ref == "J_CAM")
        power_pads = {"14", "15", "21"}
        self.assertEqual({j_cam.pins[p] for p in power_pads}, {"+1V5", "+2V8"})
        self.assertEqual({j_cam.pins[p] for p in power_pads} & set(gpio.CAM.values()), set())
        self.assertEqual(j_cam.pins["10"], "GND")
        self.assertEqual(j_cam.pins["23"], "GND")


class CameraPeripheralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parts = variants.parts("C")
        cls.by_ref = {p.ref: p for p in cls.parts}

    def test_ads1115_channels_follow_spec_order(self):
        # 四路测量顺序交换会让固件把温度/电压解释错，本测试必须失败。
        adc = self.by_ref["U_ADC"]
        self.assertEqual({pad: adc.pins[pad] for pad in ("4", "5", "6", "7")},
                         {"4": "NTC_SENSE", "5": "VBAT_SENSE",
                          "6": "CC_SENSE", "7": "BAT_NTC_SENSE"})

    def test_mpr121_touch_and_gpio_functions_follow_spec(self):
        # 加热必须用可作 GPIO 的 ELE4+，且不能与静音键交换。
        touch = self.by_ref["U_TOUCH"]
        self.assertEqual({pad: touch.pins[pad] for pad in ("8", "12", "13")},
                         {"8": "TOUCH_E0", "12": "HEAT_GATE_DRV", "13": "KEY_MUTE"})

    def test_camera_family_has_no_pca9685(self):
        self.assertNotIn("U_SERVO", self.by_ref)

    def test_heater_has_hardware_pulldown_while_mpr121_resets(self):
        pulldown = self.by_ref["R_GATE_PD"]
        self.assertEqual(pulldown.value, "100k")
        self.assertEqual(set(pulldown.pins.values()), {"HEAT_GATE", "GND"})


if __name__ == "__main__":
    unittest.main()
