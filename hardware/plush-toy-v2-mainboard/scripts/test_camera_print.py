"""C/D 摄像头 1:1 实物核验稿。用 KiCad 自带 Python 运行。"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pcbnew

import context


SCRIPT = Path(__file__).with_name("export_camera_check.py")


class CameraPrintTests(unittest.TestCase):
    def test_each_camera_variant_exports_a_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            for variant in ("C", "D"):
                output = Path(directory) / f"camera-{variant}.pdf"
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), "--variant", variant, "--output", str(output)],
                    text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(output.read_bytes().startswith(b"%PDF-"))
                self.assertGreater(output.stat().st_size, 10_000)

    def test_C_and_D_print_the_same_camera_footprint_geometry(self):
        found = []
        for variant in ("C", "D"):
            ctx = context.load(variant)
            board = pcbnew.LoadBoard(str(ctx.pcb))
            footprint = next(fp for fp in board.GetFootprints() if fp.GetReference() == "J_CAM")
            found.append((
                footprint.GetFPIDAsString(),
                round(footprint.GetPosition().x / 1e6, 3),
                round(footprint.GetPosition().y / 1e6, 3),
                round(footprint.GetOrientationDegrees(), 1),
                footprint.GetLayerName(),
            ))
        expected = (
            "plushv2:FPC-SMD_24P-P0.50_AFC01-S24FCA-00",
            12.5, 4.885, 180.0, "F.Cu",
        )
        self.assertEqual(found, [expected, expected])


if __name__ == "__main__":
    unittest.main()
