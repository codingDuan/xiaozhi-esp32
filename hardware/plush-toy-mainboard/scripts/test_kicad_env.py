import unittest
import kicad_env

# 本工程要用到的官方库符号与封装。任何一项不存在，都要在 board_spec 里改用工程自带库。
REQUIRED_SYMBOLS = [
    ("RF_Module", "ESP32-S3-WROOM-1"),
    ("Driver_LED", "PCA9685PW"),
    ("Analog_ADC", "ADS1115IDGS"),
    ("Sensor_Motion", "MPU-6050"),
]
REQUIRED_FOOTPRINTS = [
    ("RF_Module", "ESP32-S3-WROOM-1"),
    ("Connector_USB", "USB_C_Receptacle_HRO_TYPE-C-31-M-12"),
    ("Package_TO_SOT_SMD", "SOT-23-5"),
    ("Package_TO_SOT_SMD", "SOT-23"),
    ("Package_DFN_QFN", "QFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.7mm"),
    ("Resistor_SMD", "R_0402_1005Metric"),
    ("Capacitor_SMD", "C_0402_1005Metric"),
]
# 工程自带库（lib/），官方库没有的器件
REQUIRED_PROJECT = [
    ("symbol", "plush", "INMP441"),
    ("footprint", "plush", "InvenSense_INMP441_LGA-9_4.72x3.76mm"),
]


class KicadEnvTest(unittest.TestCase):
    def test_cli_and_python_exist(self):
        self.assertTrue(kicad_env.Path(kicad_env.KICAD_CLI).exists())
        self.assertTrue(kicad_env.Path(kicad_env.KICAD_PYTHON).exists())

    def test_required_symbols(self):
        for lib, name in REQUIRED_SYMBOLS:
            with self.subTest(lib=lib, name=name):
                self.assertTrue(kicad_env.symbol_exists(lib, name))

    def test_required_footprints(self):
        for lib, name in REQUIRED_FOOTPRINTS:
            with self.subTest(lib=lib, name=name):
                self.assertTrue(kicad_env.footprint_exists(lib, name))

    def test_project_library_resolves_like_official(self):
        for kind, lib, name in REQUIRED_PROJECT:
            with self.subTest(kind=kind, name=name):
                check = kicad_env.symbol_exists if kind == "symbol" else kicad_env.footprint_exists
                self.assertTrue(check(lib, name))

    def test_symbol_file_and_footprint_dir_for_project_lib(self):
        self.assertEqual(kicad_env.symbol_file("plush").name, "plush.kicad_sym")
        self.assertEqual(kicad_env.footprint_dir("plush").name, "plush.pretty")
        self.assertEqual(kicad_env.footprint_dir("RF_Module").parent, kicad_env.FOOTPRINT_DIR)

    def test_schematic_version_read_from_bundled_demo(self):
        self.assertGreaterEqual(kicad_env.SCH_FILE_VERSION, 20250000)


if __name__ == "__main__":
    unittest.main()
