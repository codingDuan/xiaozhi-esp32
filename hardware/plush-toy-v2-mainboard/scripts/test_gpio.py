import unittest

from v2 import gpio

USABLE = set(range(0, 19)) | {21} | set(range(38, 49))


class GpioTests(unittest.TestCase):
    def test_spec_table_common(self):
        expected = {0: "BOOT", 38: "LCD_CLK", 14: "LCD_MOSI", 47: "LCD_DC", 45: "LCD_CS",
                    21: "LCD_RST", 48: "LCD_BL_PWM", 1: "MIC_WS", 2: "MIC_SCK", 42: "MIC_SD",
                    39: "AMP_DIN", 40: "AMP_BCLK", 41: "AMP_LRCLK", 43: "I2C_SCL", 44: "I2C_SDA",
                    3: "SERVO_L_PWM", 46: "SERVO_R_PWM", 19: "USB_DN", 20: "USB_DP"}
        self.assertEqual(gpio.COMMON, expected)

    def test_spec_table_nocam(self):
        self.assertEqual(gpio.NOCAM, {17: "HEAT_GATE_DRV", 18: "KEY_MUTE", 8: "TOUCH_E0",
                                      4: "NTC_SENSE", 5: "VBAT_SENSE", 6: "CC_SENSE", 7: "BAT_NTC_SENSE"})

    def test_spec_table_cam(self):
        self.assertEqual(gpio.CAM, {4: "CAM_SIOD", 5: "CAM_SIOC", 6: "CAM_VSYNC", 7: "CAM_HREF",
                                    15: "CAM_XCLK", 13: "CAM_PCLK", 11: "CAM_Y2", 9: "CAM_Y3",
                                    8: "CAM_Y4", 10: "CAM_Y5", 12: "CAM_Y6", 18: "CAM_Y7",
                                    17: "CAM_Y8", 16: "CAM_Y9"})

    def test_no_conflicts_and_only_usable_pins(self):
        for camera in (False, True):
            with self.subTest(camera=camera):
                table = gpio.for_family(camera)
                extra = gpio.CAM if camera else gpio.NOCAM
                self.assertEqual(set(gpio.COMMON) & set(extra), set())
                self.assertLessEqual(set(table) - {19, 20}, USABLE)
                self.assertEqual(len(set(table.values())), len(table))

    def test_camera_family_uses_every_usable_gpio(self):
        self.assertEqual(set(gpio.for_family(True)) - {19, 20}, USABLE)

    def test_psram_pins_never_assigned(self):
        for camera in (False, True):
            self.assertEqual(set(gpio.for_family(camera)) & {35, 36, 37}, set())

    def test_wroom_pad_table_covers_all_used_gpio(self):
        for camera in (False, True):
            self.assertLessEqual(set(gpio.for_family(camera)), set(gpio.WROOM_PAD_GPIO.values()))


if __name__ == "__main__":
    unittest.main()
