"""从固件 config.h 读取 GPIO 分配。PCB 的引脚只允许来自这里。"""
import re
from pathlib import Path

_DEFINE = re.compile(r"^\s*#define\s+(\w+)\s+GPIO_NUM_(\d+|NC)\b")


def load(path: Path) -> dict[str, int]:
    pins: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _DEFINE.match(line)
        if m:
            pins[m.group(1)] = -1 if m.group(2) == "NC" else int(m.group(2))
    return pins
