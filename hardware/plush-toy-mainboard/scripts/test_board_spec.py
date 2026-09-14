import unittest
from pathlib import Path
import board_spec
import config_pins

CONFIG_H = Path(__file__).resolve().parents[3] / "main/boards/plush-toy/config.h"

# config.h 宏 → 本板网络名。这张表本身就是 GPIO 分配的核对清单。
MACRO_TO_NET = {
    "AUDIO_I2S_MIC_GPIO_WS": "MIC_WS", "AUDIO_I2S_MIC_GPIO_SCK": "MIC_SCK",
    "AUDIO_I2S_MIC_GPIO_DIN": "MIC_SD", "AUDIO_I2S_SPK_GPIO_DOUT": "AMP_DIN",
    "AUDIO_I2S_SPK_GPIO_BCLK": "AMP_BCLK", "AUDIO_I2S_SPK_GPIO_LRCK": "AMP_LRCLK",
    "BUILTIN_LED_GPIO": "LED_RGB", "BOOT_BUTTON_GPIO": "BOOT",
    "CAMERA_PIN_D0": "CAM_Y2", "CAMERA_PIN_D1": "CAM_Y3", "CAMERA_PIN_D2": "CAM_Y4",
    "CAMERA_PIN_D3": "CAM_Y5", "CAMERA_PIN_D4": "CAM_Y6", "CAMERA_PIN_D5": "CAM_Y7",
    "CAMERA_PIN_D6": "CAM_Y8", "CAMERA_PIN_D7": "CAM_Y9", "CAMERA_PIN_XCLK": "CAM_XCLK",
    "CAMERA_PIN_PCLK": "CAM_PCLK", "CAMERA_PIN_VSYNC": "CAM_VSYNC", "CAMERA_PIN_HREF": "CAM_HREF",
    "CAMERA_PIN_SIOC": "CAM_SIOC", "CAMERA_PIN_SIOD": "CAM_SIOD",
    "DISPLAY_MOSI_PIN": "LCD_MOSI", "DISPLAY_CLK_PIN": "LCD_CLK", "DISPLAY_DC_PIN": "LCD_DC",
    "DISPLAY_RST_PIN": "LCD_RST", "DISPLAY_CS_LEFT_PIN": "LCD_CS_L", "DISPLAY_CS_RIGHT_PIN": "LCD_CS_R",
    "SERVO_I2C_SDA_PIN": "I2C_SDA", "SERVO_I2C_SCL_PIN": "I2C_SCL",
}
SUPPLIES = {"+3V3", "VBUS", "VMOT", "+2V8", "+1V5"}


def two_terminal(part):
    return len(part.pins) == 2


class GpioMatchesConfigTest(unittest.TestCase):
    def test_every_config_gpio_lands_on_its_net(self):
        pins = config_pins.load(CONFIG_H)
        for macro, net in MACRO_TO_NET.items():
            with self.subTest(macro=macro):
                self.assertEqual(board_spec.GPIO_NET[pins[macro]], net)

    def test_module_pins_follow_gpio_net(self):
        module = next(p for p in board_spec.PARTS if p.ref == "U1")
        for gpio, net in board_spec.GPIO_NET.items():
            with self.subTest(gpio=gpio):
                self.assertIn(net, module.pins.values())

    def test_flash_and_psram_gpios_unused(self):
        # GPIO26-37 在 N16R8 模组内部，模组焊盘只引出 35/36/37，且必须悬空
        for gpio in (35, 36, 37):
            self.assertNotIn(gpio, board_spec.GPIO_NET)


class HardConstraintTest(unittest.TestCase):
    def setUp(self):
        self.nets = board_spec.nets()
        self.fitted = [p for p in board_spec.PARTS if p.fitted]

    def test_hc1_no_part_bridges_vbus_and_vmot(self):
        for part in self.fitted:
            with self.subTest(ref=part.ref):
                self.assertFalse({"VBUS", "VMOT"} <= set(part.pins.values()))

    def test_hc2_single_star_link_between_pgnd_and_gnd(self):
        bridges = [p.ref for p in self.fitted if set(p.pins.values()) == {"GND", "PGND"}]
        self.assertEqual(bridges, ["R_STAR"])

    def test_hc3_heater_gate_pulldown(self):
        q = next(p for p in board_spec.PARTS if p.ref == "Q_HEAT")
        gate = q.pins["1"]
        pulldowns = [p for p in self.fitted if two_terminal(p)
                     and set(p.pins.values()) == {gate, "PGND"} and p.value == "100k"]
        self.assertEqual(len(pulldowns), 1)

    def test_hc4_no_pullup_on_strapping_cs(self):
        for net in ("LCD_CS_L", "LCD_CS_R"):
            for part in self.fitted:
                if two_terminal(part) and net in part.pins.values():
                    with self.subTest(net=net, ref=part.ref):
                        self.assertFalse(set(part.pins.values()) & SUPPLIES)

    def test_hc5_single_pullup_per_i2c_line(self):
        for net in ("I2C_SDA", "I2C_SCL"):
            ups = [p for p in self.fitted if two_terminal(p)
                   and set(p.pins.values()) == {net, "+3V3"}]
            with self.subTest(net=net):
                self.assertEqual(len(ups), 1)
                self.assertEqual(ups[0].value, "4.7k")


class NetIntegrityTest(unittest.TestCase):
    def test_no_single_pin_nets(self):
        for net, members in board_spec.nets().items():
            if net.startswith("NC_"):
                continue
            with self.subTest(net=net):
                self.assertGreaterEqual(len(members), 2)

    def test_refs_unique(self):
        refs = [p.ref for p in board_spec.PARTS]
        self.assertEqual(len(refs), len(set(refs)))

    def test_every_fitted_part_has_lcsc_code(self):
        for part in board_spec.PARTS:
            if part.fitted and not part.ref.startswith(("J_", "TP", "H")):
                with self.subTest(ref=part.ref):
                    self.assertRegex(part.lcsc, r"^C\d+$")


if __name__ == "__main__":
    unittest.main()
