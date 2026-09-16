import unittest
from pathlib import Path
import board_spec
import config_pins
import export_wiring
import project_rules

CONFIG_H = Path(__file__).resolve().parents[3] / "main/boards/plush-toy/config.h"

# config.h 宏 → 本板网络名。这张表本身就是 GPIO 分配的核对清单。
MACRO_TO_NET = {
    "AUDIO_I2S_MIC_GPIO_WS": "MIC_WS", "AUDIO_I2S_MIC_GPIO_SCK": "MIC_SCK",
    "AUDIO_I2S_MIC_GPIO_DIN": "MIC_SD", "AUDIO_I2S_SPK_GPIO_DOUT": "AMP_DIN",
    "AUDIO_I2S_SPK_GPIO_BCLK": "AMP_BCLK", "AUDIO_I2S_SPK_GPIO_LRCK": "AMP_LRCLK",
    "DISPLAY_BACKLIGHT_PIN": "LCD_BL_PWM", "BOOT_BUTTON_GPIO": "BOOT",
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


def part(ref):
    matches = [item for item in board_spec.PARTS if item.ref == ref]
    if len(matches) != 1:
        raise AssertionError(f"{ref} 应有且仅有一个定义，实际 {len(matches)}")
    return matches[0]


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

    def test_usb_efuse_is_between_fuse_and_every_vbus_load(self):
        self.assertEqual(part("F_USB").pins, {"1": "VBUS_IN", "2": "VBUS_FUSED"})
        self.assertEqual(part("U_EFUSE").pins, {
            "1": "EFUSE_DVDT", "2": "VBUS_FUSED", "3": "VBUS_FUSED",
            "4": "VBUS_FUSED", "5": "VBUS", "6": "NC_U_EFUSE_FLT",
            "7": "EFUSE_ILM", "8": "GND", "9": "GND",
        })
        self.assertEqual(part("C_EFUSE_IN").pins, {"1": "VBUS_FUSED", "2": "GND"})
        self.assertEqual(part("C_EFUSE_DVDT").pins, {"1": "EFUSE_DVDT", "2": "GND"})
        self.assertEqual(part("R_EFUSE_ILM").pins, {"1": "EFUSE_ILM", "2": "GND"})
        for load in ("U_BUCK", "R_BUCK_EN", "U_AMP", "R_AMP_SD", "C_AMP_BULK", "C_AMP"):
            with self.subTest(load=load):
                self.assertNotIn("VBUS_FUSED", part(load).pins.values())
                self.assertIn("VBUS", part(load).pins.values())

    def test_buck_has_local_high_frequency_input_capacitor(self):
        capacitor = part("C_BUCK_HF")
        self.assertEqual(capacitor.value, "100nF")
        self.assertEqual(capacitor.footprint, "Capacitor_SMD:C_0402_1005Metric")
        self.assertEqual(capacitor.pins, {"1": "VBUS", "2": "GND"})

    def test_revised_camera_touch_and_backlight_parts(self):
        self.assertTrue(part("R_SIOC").fitted)
        self.assertTrue(part("R_SIOD").fitted)
        self.assertNotIn("TP_E0", {item.ref for item in board_spec.PARTS})
        self.assertEqual(part("J_TOUCH").pins, {"1": "TOUCH_E0", "2": "GND"})
        refs = {item.ref for item in board_spec.PARTS}
        self.assertNotIn("D_LED", refs)
        self.assertNotIn("C_LED", refs)
        self.assertEqual(part("Q_LCD_BL").value, "AO3401A")
        self.assertEqual(part("Q_LCD_BL").lcsc, "C15127")

    def test_backlight_high_side_switch_defaults_off(self):
        self.assertEqual(part("Q_LCD_BL").pins,
                         {"1": "LCD_BL_GATE", "2": "+3V3", "3": "LCD_BL"})
        self.assertEqual(part("R_LCD_BL_GATE").pins,
                         {"1": "LCD_BL_PWM", "2": "LCD_BL_GATE"})
        self.assertEqual(part("R_LCD_BL_GATE").value, "100")
        self.assertEqual(part("R_LCD_BL_OFF").pins,
                         {"1": "+3V3", "2": "LCD_BL_GATE"})
        self.assertEqual(part("R_LCD_BL_OFF").value, "100k")

    def test_both_eye_connectors_expose_switched_backlight_power(self):
        common = {"1": "LCD_RST", "3": "LCD_DC", "4": "LCD_MOSI_S",
                  "5": "LCD_CLK_S", "6": "GND", "7": "+3V3", "8": "LCD_BL"}
        self.assertEqual(part("J_LCD_L").pins, {**common, "2": "LCD_CS_L"})
        self.assertEqual(part("J_LCD_R").pins, {**common, "2": "LCD_CS_R"})
        self.assertEqual(part("J_LCD_L").footprint,
                         "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical")
        self.assertEqual(part("J_LCD_R").footprint,
                         "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical")

    def test_hand_installed_parts_are_owned_by_board_spec(self):
        expected = {"J_HEAT", "J_LCD_L", "J_LCD_R",
                    "J_SERVO_L", "J_SERVO_R",
                    "J_NTC", "J_SPK", "J_VMOT", "J_TOUCH"}
        actual = {item.ref for item in board_spec.PARTS
                  if item.fitted and not getattr(item, "assembly", True) and item.ref.startswith("J_")}
        self.assertEqual(actual, expected)


class WiringTableTest(unittest.TestCase):
    """对照表是给人拿着核实物的，和板子脱节就比没有更危险。"""

    def test_table_covers_every_connector(self):
        connectors = {part.ref for part in board_spec.PARTS if part.ref.startswith("J_")}
        self.assertEqual(connectors, set(export_wiring.CONNECTORS))

    def test_every_connector_pin_resolves_to_something_readable(self):
        for ref in export_wiring.CONNECTORS:
            spec = next(item for item in board_spec.PARTS if item.ref == ref)
            for number, net in spec.pins.items():
                with self.subTest(ref=ref, pin=number):
                    self.assertNotEqual(export_wiring.describe(net), "—")

    def test_committed_table_is_up_to_date(self):
        self.assertEqual(
            export_wiring.OUTPUT.read_text(encoding="utf-8"), export_wiring.render(),
            "WIRING.md 已过期，请重跑 python3 scripts/export_wiring.py")


class NetIntegrityTest(unittest.TestCase):
    def test_switched_backlight_uses_supply_netclass(self):
        assignments = {(item["netclass"], item["pattern"])
                       for item in project_rules.PATTERNS}
        self.assertIn(("Supply", "LCD_BL"), assignments)

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
