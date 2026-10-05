"""摄像头物理方向与断电测量门禁（spec §7.3 / §7.4）。

证据采用 CAMERA_VERIFICATION.md 中的机器可读 `KEY: value` 行。门禁默认失败：文件、字段、
照片或哈希任一缺失都返回错误，生产导出不得自行推断方向。
"""
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


ORDER_EXPECTED = {
    "ORDER_GATE_STATUS": "VERIFIED",
    "CONNECTOR_LCSC": "C262669",
    "CAMERA_MODULE": "AFC01-S24FCA-00",
    "CONTACTS_DIRECTION": "DOWN",
    "CAMERA_PIN_1_PAD": "24",
    "CAMERA_PIN_24_PAD": "1",
    "LENS_DIRECTION": "AWAY_FROM_PCB",
}
POWER_EXPECTED = {
    "POWER_GATE_STATUS": "VERIFIED",
    "EMPTY_PIN_TO_1V5": "OL",
    "DIODE_1V5_TO_GND_RESULT": "PASS",
}


def _fields(path: Path) -> tuple[dict[str, str], list[str]]:
    if not path.is_file():
        return {}, [f"缺少摄像头实物验证文件：{path}"]
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]+):\s*(.*?)\s*$", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values, []


def _expect(values: dict[str, str], expected: dict[str, str]) -> list[str]:
    return [f"{key} 必须为 {wanted!r}，实际 {values.get(key, '<missing>')!r}"
            for key, wanted in expected.items() if values.get(key) != wanted]


def _require_nonempty(values: dict[str, str], keys: tuple[str, ...]) -> list[str]:
    return [f"{key} 缺失或为空" for key in keys if not values.get(key)]


def validate_for_order(path: Path) -> list[str]:
    """§7.3：下单前实物方向、1 脚落点与照片证据。"""
    path = Path(path)
    values, errors = _fields(path)
    if errors:
        return errors
    errors += _expect(values, ORDER_EXPECTED)
    errors += _require_nonempty(values, ("ORDER_VERIFIED_DATE", "ORDER_VERIFIED_BY",
                                          "EVIDENCE_IMAGE", "EVIDENCE_SHA256"))
    image_name = values.get("EVIDENCE_IMAGE", "")
    if image_name:
        image = (path.parent / image_name).resolve()
        try:
            image.relative_to(path.parent.resolve())
        except ValueError:
            errors.append("EVIDENCE_IMAGE 必须位于验证文件同一目录内")
        else:
            if not image.is_file():
                errors.append(f"EVIDENCE_IMAGE 不存在：{image_name}")
            elif values.get("EVIDENCE_SHA256"):
                digest = hashlib.sha256(image.read_bytes()).hexdigest()
                if digest.lower() != values["EVIDENCE_SHA256"].lower():
                    errors.append("EVIDENCE_SHA256 与照片内容不匹配")
    return errors


def validate_for_camera_power(path: Path) -> list[str]:
    """§7.3 + §7.4：首板插摄像头上电前的断电测量。"""
    path = Path(path)
    errors = validate_for_order(path)
    values, field_errors = _fields(path)
    errors += field_errors
    if field_errors:
        return errors
    errors += _expect(values, POWER_EXPECTED)
    errors += _require_nonempty(values, ("DIODE_1V5_TO_GND_WITHOUT_CAMERA",
                                          "DIODE_1V5_TO_GND_WITH_CAMERA",
                                          "POWER_VERIFIED_DATE", "POWER_VERIFIED_BY"))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--power", action="store_true")
    args = parser.parse_args()
    errors = (validate_for_camera_power(args.path) if args.power
              else validate_for_order(args.path))
    if errors:
        print("摄像头物理门禁未通过：")
        for error in errors:
            print(f"- {error}")
        return 1
    print("摄像头物理门禁通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
