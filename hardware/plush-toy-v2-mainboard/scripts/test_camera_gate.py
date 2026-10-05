import hashlib
import tempfile
import unittest
from pathlib import Path

import camera_gate


def verification_text(image_sha: str, *, order="VERIFIED", power="PENDING") -> str:
    return f"""# Camera verification

ORDER_GATE_STATUS: {order}
CONNECTOR_LCSC: C262669
CAMERA_MODULE: AFC01-S24FCA-00
CONTACTS_DIRECTION: DOWN
CAMERA_PIN_1_PAD: 24
CAMERA_PIN_24_PAD: 1
LENS_DIRECTION: AWAY_FROM_PCB
ORDER_VERIFIED_DATE: 2026-10-05
ORDER_VERIFIED_BY: fixture
EVIDENCE_IMAGE: camera-orientation.jpg
EVIDENCE_SHA256: {image_sha}

POWER_GATE_STATUS: {power}
EMPTY_PIN_TO_1V5: OL
DIODE_1V5_TO_GND_WITHOUT_CAMERA: 0.620V
DIODE_1V5_TO_GND_WITH_CAMERA: 0.615V
DIODE_1V5_TO_GND_RESULT: PASS
POWER_VERIFIED_DATE: 2026-10-06
POWER_VERIFIED_BY: fixture
"""


class CameraGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "CAMERA_VERIFICATION.md"
        self.image = self.root / "camera-orientation.jpg"
        self.image.write_bytes(b"real fixture image bytes")
        self.sha = hashlib.sha256(self.image.read_bytes()).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text=None):
        self.path.write_text(text or verification_text(self.sha), encoding="utf-8")

    def test_missing_file_fails_closed(self):
        self.assertTrue(camera_gate.validate_for_order(self.path))
        self.assertTrue(camera_gate.validate_for_camera_power(self.path))

    def test_verified_order_evidence_passes(self):
        self.write()
        self.assertEqual(camera_gate.validate_for_order(self.path), [])

    def test_pending_or_wrong_orientation_fails_order_gate(self):
        self.write(verification_text(self.sha, order="PENDING").replace(
            "CAMERA_PIN_1_PAD: 24", "CAMERA_PIN_1_PAD: 1").replace(
            "CONTACTS_DIRECTION: DOWN", "CONTACTS_DIRECTION: UP"))
        errors = "\n".join(camera_gate.validate_for_order(self.path))
        self.assertIn("ORDER_GATE_STATUS", errors)
        self.assertIn("CAMERA_PIN_1_PAD", errors)
        self.assertIn("CONTACTS_DIRECTION", errors)

    def test_missing_or_tampered_image_fails_order_gate(self):
        self.write(verification_text("0" * 64))
        self.assertIn("EVIDENCE_SHA256", "\n".join(camera_gate.validate_for_order(self.path)))
        self.image.unlink()
        self.assertIn("EVIDENCE_IMAGE", "\n".join(camera_gate.validate_for_order(self.path)))

    def test_power_gate_requires_order_and_disconnected_measurements(self):
        self.write()
        errors = "\n".join(camera_gate.validate_for_camera_power(self.path))
        self.assertIn("POWER_GATE_STATUS", errors)
        self.write(verification_text(self.sha, power="VERIFIED"))
        self.assertEqual(camera_gate.validate_for_camera_power(self.path), [])

    def test_power_gate_rejects_non_ol_or_failed_diode_comparison(self):
        text = verification_text(self.sha, power="VERIFIED").replace(
            "EMPTY_PIN_TO_1V5: OL", "EMPTY_PIN_TO_1V5: 0R").replace(
            "DIODE_1V5_TO_GND_RESULT: PASS", "DIODE_1V5_TO_GND_RESULT: FAIL")
        self.write(text)
        errors = "\n".join(camera_gate.validate_for_camera_power(self.path))
        self.assertIn("EMPTY_PIN_TO_1V5", errors)
        self.assertIn("DIODE_1V5_TO_GND_RESULT", errors)


if __name__ == "__main__":
    unittest.main()
