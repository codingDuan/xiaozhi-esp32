import unittest

from v2 import parts_db

REQUIRED = {
    # 键 → 必须存在的语义引脚
    "WROOM": {"GND", "3V3", "EN"},
    "IP5306_I2C": {"VIN", "VOUT", "BAT", "SW", "KEY", "SCL", "SDA", "GND"},
    "TPS259531": {"IN", "OUT", "EN", "ILM", "DVDT", "GND"},
    "SY8089": {"IN", "EN", "SW", "FB", "GND"},
    "MAX98357A": {"VDD", "GND", "BCLK", "LRCLK", "DIN", "SD_MODE", "OUTP", "OUTN"},
    "LIS2DH12": {"VDD", "VDD_IO", "GND", "SCL", "SDA", "SDO_SA0", "CS", "RES"},
    "AO3400A": {"G", "S", "D"},
    "AO3401A": {"G", "S", "D"},
    "USB_C16": {"VBUS", "GND", "CC1", "CC2", "DP", "DN", "SHIELD"},
    "PTC_USB": {"1", "2"},
    "ESD_LINE": {"IO", "GND"},
    "CONN_BAT": {"+", "-"},
    "CONN_LCD8": {str(i) for i in range(1, 9)},
    "CONN_MIC6": {str(i) for i in range(1, 7)},
    "CONN_SPK2": {"1", "2"},
    "CONN_HEAT2": {"1", "2"},
    "CONN_SH2": {"1", "2"},
    "CONN_KEY3": {"1", "2", "3"},
    "HDR_SERVO3": {"1", "2", "3"},
    "SW_TACT": {"A", "B"},
    "INDUCTOR_BOOST": {"1", "2"},
    "INDUCTOR_BUCK": {"1", "2"},
    "NTC_0603_10K": {"1", "2"},
}


class PartsDbTests(unittest.TestCase):
    def test_every_required_key_present(self):
        self.assertEqual(set(REQUIRED) - set(parts_db.DB), set())

    def test_every_entry_has_lcsc_symbol_footprint(self):
        for key, entry in parts_db.DB.items():
            with self.subTest(key=key):
                self.assertRegex(entry.lcsc, r"^C\d+$")
                self.assertIn(":", entry.symbol)
                self.assertIn(":", entry.footprint)

    def test_required_semantic_pins_mapped(self):
        for key, names in REQUIRED.items():
            with self.subTest(key=key):
                self.assertEqual(names - set(parts_db.DB[key].pads), set())

    def test_grouped_pads_all_get_the_net(self):
        u = parts_db.part("TPS259531", "U_X", {"IN": "VIN_NET", "GND": "GND"})
        self.assertEqual((u.pins["3"], u.pins["4"]), ("VIN_NET", "VIN_NET"))
        self.assertEqual((u.pins["8"], u.pins["9"]), ("GND", "GND"))

    def test_efuse_input_and_output_pads_follow_datasheet(self):
        # 计划初稿把 IN/OUT 写反过；以一期实测接法（3/4 IN、5 OUT）为准
        self.assertEqual(parts_db.DB["TPS259531"].pads["IN"], ("3", "4"))
        self.assertEqual(parts_db.DB["TPS259531"].pads["OUT"], "5")

    def test_part_helper_rejects_unknown_semantic_pin(self):
        with self.assertRaises(KeyError):
            parts_db.part("AO3400A", "Q_X", {"G": "A", "S": "B", "DRAIN": "C"})


class FootprintPadTests(unittest.TestCase):
    def test_semantic_pads_exist_in_footprint(self):
        try:
            import pcbnew
        except ImportError:
            self.skipTest("需用 KiCad 自带 Python 运行")
        import kicad_env
        for key, entry in parts_db.DB.items():
            lib, name = entry.footprint.split(":", 1)
            fp = pcbnew.FootprintLoad(str(kicad_env.footprint_dir(lib)), name)
            with self.subTest(key=key):
                self.assertIsNotNone(fp, entry.footprint)
                pads = {p.GetNumber() for p in fp.Pads()}
                self.assertEqual(parts_db.pad_numbers(entry) - pads, set())


if __name__ == "__main__":
    unittest.main()
