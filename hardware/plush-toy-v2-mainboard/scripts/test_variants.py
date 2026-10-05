import unittest

from v2 import variants

HAND_EXEMPT_PREFIXES = ("TP_", "H")


class VariantATests(unittest.TestCase):
    parts = variants.parts("A")

    def test_variant_table(self):
        self.assertEqual({k: (v.camera, v.double_sided) for k, v in variants.VARIANTS.items()},
                         {"A": (False, False), "B": (False, True), "C": (True, False), "D": (True, True)})

    def test_refs_unique(self):
        refs = [p.ref for p in self.parts]
        self.assertEqual(len(refs), len(set(refs)))

    def test_zero_hand_solder(self):
        for p in self.parts:
            if p.ref.startswith(HAND_EXEMPT_PREFIXES):
                continue
            with self.subTest(ref=p.ref):
                self.assertTrue(p.assembly)
                self.assertRegex(p.lcsc, r"^C\d+$")

    def test_no_single_pin_nets(self):
        singles = [n for n, ends in variants.nets("A").items()
                   if len(ends) == 1 and not n.startswith("NC_")]
        self.assertEqual(singles, [])

    def test_nocam_functions_reach_gpio(self):
        nets = variants.nets("A")
        for net in ("HEAT_GATE_DRV", "KEY_MUTE", "TOUCH_E0", "NTC_SENSE",
                    "VBAT_SENSE", "CC_SENSE", "BAT_NTC_SENSE"):
            self.assertIn("U1", {r for r, _ in nets[net]}, net)

    def test_no_camera_parts_in_a(self):
        self.assertFalse(any(p.ref.startswith(("J_CAM", "U_LDO", "U_TOUCH", "U_ADC")) for p in self.parts))

    def test_camera_variants_not_built_yet(self):
        for name in ("C", "D"):
            with self.assertRaises(NotImplementedError):
                variants.parts(name)


if __name__ == "__main__":
    unittest.main()
