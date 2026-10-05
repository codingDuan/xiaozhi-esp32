import unittest

from v2 import core


def nets_of(parts):
    result = {}
    for p in parts:
        for pin, net in p.pins.items():
            result.setdefault(net, []).append((p.ref, pin))
    return result


def refs_on(parts, net):
    return {ref for ref, _ in nets_of(parts).get(net, [])}


def by_ref(parts, ref):
    return next(p for p in parts if p.ref == ref)


def ohms(value):
    scale = {"k": 1e3, "M": 1e6}
    return float(value[:-1]) * scale[value[-1]] if value[-1] in scale else float(value)


class PowerTests(unittest.TestCase):
    parts = core.power_parts()

    def test_heater_fed_only_from_vusb(self):
        heat = by_ref(self.parts, "J_HEAT")
        self.assertIn("VUSB", heat.pins.values())
        self.assertNotIn("VSYS", heat.pins.values())
        self.assertNotIn("VBAT", heat.pins.values())

    def test_no_part_bridges_vusb_and_vsys_except_charger(self):
        bridges = {p.ref for p in self.parts if {"VUSB", "VSYS"} <= set(p.pins.values())}
        self.assertEqual(bridges, {"U_CHG"})

    def test_efuse_between_fuse_and_loads(self):
        self.assertEqual(refs_on(self.parts, "VBUS_FUSED"), {"F_USB", "U_EFUSE", "C_EFUSE_IN"})
        efuse = by_ref(self.parts, "U_EFUSE")
        self.assertEqual({efuse.pins[p] for p in ("2", "3", "4")}, {"VBUS_FUSED"})
        self.assertEqual(efuse.pins["5"], "VUSB")

    def test_heater_gate_pulldown(self):
        pd = by_ref(self.parts, "R_GATE_PD")
        self.assertEqual(set(pd.pins.values()), {"HEAT_GATE", "GND"})
        self.assertEqual(pd.value, "100k")

    def test_heater_and_ntc_on_separate_connectors(self):
        ntc = by_ref(self.parts, "J_NTC")
        self.assertNotIn("VUSB", ntc.pins.values())
        self.assertNotIn("VSYS", ntc.pins.values())
        self.assertNotIn("HEAT_LOW", ntc.pins.values())

    def test_cc_divider_halves_three_amp_level(self):
        rd = ohms(by_ref(self.parts, "R_CC1").value)

        def node(rp):
            return 5.0 * rd / (rp + rd) / 2

        default, a15, a30 = node(56e3), node(22e3), node(10e3)
        self.assertGreaterEqual(a30 - a15, 0.25)
        self.assertGreaterEqual(a15 - default, 0.2)
        for ref, cc in (("R_CC_SUM1", "CC1"), ("R_CC_SUM2", "CC2")):
            self.assertEqual(set(by_ref(self.parts, ref).pins.values()), {cc, "CC_SENSE"})
            self.assertEqual(by_ref(self.parts, ref).value, "100k")

    def test_battery_reverse_path_blocked(self):
        # BATTERY_PROTECTION.md 方案 C：电池座与 IP5306 之间只有 Q_BATP 与 10k 旁路
        self.assertEqual(refs_on(self.parts, "VBAT_PACK"), {"J_BAT", "Q_BATP", "R_BATP_BYP", "R_BATN_G"})
        self.assertNotIn("U_CHG", refs_on(self.parts, "VBAT_PACK"))
        q1 = by_ref(self.parts, "Q_BATP")
        self.assertEqual((q1.pins["2"], q1.pins["3"], q1.pins["1"]), ("VBAT", "VBAT_PACK", "BATP_GATE"))
        self.assertEqual(by_ref(self.parts, "R_BATP_BYP").value, "10k")

    def test_battery_sense_fet_not_driven_by_charger(self):
        # Q_BATN 栅极只经电阻接电池正端与地；接到 VBAT 会被充电器骗开
        self.assertEqual(refs_on(self.parts, "BATN_GATE"), {"Q_BATN", "R_BATN_G", "R_BATN_PD"})
        self.assertEqual(set(by_ref(self.parts, "R_BATN_G").pins.values()), {"VBAT_PACK", "BATN_GATE"})
        q2 = by_ref(self.parts, "Q_BATN")
        self.assertEqual((q2.pins["1"], q2.pins["2"], q2.pins["3"]), ("BATN_GATE", "GND", "BATP_GATE"))
        self.assertEqual(set(by_ref(self.parts, "R_BATP_PU").pins.values()), {"VBAT", "BATP_GATE"})

    def test_charger_power_key_on_connector(self):
        self.assertIn("U_CHG", refs_on(self.parts, "KEY_PWR"))

    def test_charger_on_i2c(self):
        chg = by_ref(self.parts, "U_CHG")
        self.assertEqual((chg.pins["2"], chg.pins["3"]), ("I2C_SCL", "I2C_SDA"))

    def test_vbat_sense_divider_stays_below_adc_range(self):
        top = ohms(by_ref(self.parts, "R_VBAT_TOP").value)
        bot = ohms(by_ref(self.parts, "R_VBAT_BOT").value)
        self.assertLess(4.2 * bot / (top + bot), 2.5)   # ESP32 ADC 11dB 线性区上限约 2.5V
        self.assertEqual(set(by_ref(self.parts, "R_VBAT_TOP").pins.values()), {"VBAT", "VBAT_SENSE"})


if __name__ == "__main__":
    unittest.main()
