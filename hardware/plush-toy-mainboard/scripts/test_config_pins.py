import unittest
from pathlib import Path
import config_pins

CONFIG_H = Path(__file__).resolve().parents[3] / "main/boards/plush-toy/config.h"


class ConfigPinsTest(unittest.TestCase):
    def setUp(self):
        self.pins = config_pins.load(CONFIG_H)

    def test_known_values(self):
        self.assertEqual(self.pins["SERVO_I2C_SDA_PIN"], 44)
        self.assertEqual(self.pins["SERVO_I2C_SCL_PIN"], 3)
        self.assertEqual(self.pins["DISPLAY_CS_LEFT_PIN"], 45)
        self.assertEqual(self.pins["DISPLAY_CS_RIGHT_PIN"], 46)
        self.assertEqual(self.pins["DISPLAY_BACKLIGHT_PIN"], 48)
        self.assertEqual(self.pins["CAMERA_PIN_XCLK"], 15)

    def test_nc_is_minus_one(self):
        self.assertEqual(self.pins["CAMERA_PIN_PWDN"], -1)
        self.assertEqual(self.pins["BUILTIN_LED_GPIO"], -1)

    def test_comment_lines_ignored(self):
        self.assertNotIn("LAMP_GPIO", self.pins)


if __name__ == "__main__":
    unittest.main()
