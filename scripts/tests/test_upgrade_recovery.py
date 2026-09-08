import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class UpgradeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "main/application.cc").read_text(encoding="utf-8")

    def test_failed_firmware_upgrade_returns_to_idle(self):
        method = self.source.split("bool Application::UpgradeFirmware(", 1)[1]
        method = method.split("void Application::WakeWordInvoke(", 1)[0]
        failure_branch = method.split("if (!upgrade_success) {", 1)[1]
        failure_branch = failure_branch.split("} else {", 1)[0]

        self.assertIn(
            "SetDeviceState(kDeviceStateIdle);",
            failure_branch,
            "failed OTA must leave upgrading so board overlays and LEDs can recover",
        )

    def test_download_progress_callbacks_ignore_stale_updates(self):
        assets_method = self.source.split("void Application::CheckAssetsVersion()", 1)[1]
        assets_method = assets_method.split("void Application::CheckNewVersion()", 1)[0]
        firmware_method = self.source.split("bool Application::UpgradeFirmware(", 1)[1]
        firmware_method = firmware_method.split("void Application::WakeWordInvoke(", 1)[0]

        guard = "GetDeviceState() == kDeviceStateUpgrading"
        self.assertIn(guard, assets_method)
        self.assertIn(guard, firmware_method)


if __name__ == "__main__":
    unittest.main()
