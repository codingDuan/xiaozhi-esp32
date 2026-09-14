"""board_spec 的引脚号必须真实存在于所引用的 KiCad 符号与封装里。

test_board_spec 只核对网络之间的关系，看不出「写了一个符号里根本没有的引脚号」。
这类错误到生成原理图时才会暴露成悬空网络或 ERC 报错，排查成本高，所以在数据层就拦下。
"""
import re
import unittest

import board_spec
import kicad_env

_PIN = re.compile(r'\(pin\s+\w+\s+\w+.*?\(number\s+"([^"]+)"', re.S)
# KiCad 官方封装的焊盘号带引号（(pad "1" ...)），easyeda2kicad 转出的不带（(pad 1 ...)）
_PAD = re.compile(r'\(pad\s+(?:"([^"]*)"|([^\s()"]+))\s')


def _symbol_block(lib: str, name: str) -> str:
    text = kicad_env.symbol_file(lib).read_text(encoding="utf-8")
    start = text.find(f'(symbol "{name}"')
    if start < 0:
        raise KeyError(f"{lib}:{name}")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ValueError(f"{lib}:{name} 括号不配平")


def symbol_pins(ref: str) -> set[str]:
    """符号的全部引脚号；派生符号（extends）的引脚定义在父符号里。"""
    lib, name = ref.split(":", 1)
    block = _symbol_block(lib, name)
    parent = re.search(r'\(extends\s+"([^"]+)"\)', block)
    if parent:
        block = _symbol_block(lib, parent.group(1))
    return set(_PIN.findall(block))


def footprint_pads(ref: str) -> set[str]:
    lib, name = ref.split(":", 1)
    text = (kicad_env.footprint_dir(lib) / f"{name}.kicad_mod").read_text(encoding="utf-8")
    pads = {quoted or bare for quoted, bare in _PAD.findall(text)}
    return {p for p in pads if p}   # 空编号是机械孔或钢网辅助焊盘


class PartPinsTest(unittest.TestCase):
    def test_pin_keys_exist_on_symbol(self):
        for part in board_spec.PARTS:
            with self.subTest(ref=part.ref, symbol=part.symbol):
                unknown = set(part.pins) - symbol_pins(part.symbol)
                self.assertEqual(unknown, set())

    def test_pin_keys_exist_on_footprint(self):
        for part in board_spec.PARTS:
            with self.subTest(ref=part.ref, footprint=part.footprint):
                unknown = set(part.pins) - footprint_pads(part.footprint)
                self.assertEqual(unknown, set())

    def test_every_symbol_pin_assigned(self):
        # 未连接的引脚也必须显式写成 NC_ 网络，不允许遗漏：漏写的引脚在原理图里是悬空的，
        # ERC 会报，但更糟的是可能本该接地却被忘掉。
        for part in board_spec.PARTS:
            with self.subTest(ref=part.ref):
                missing = symbol_pins(part.symbol) - set(part.pins)
                self.assertEqual(missing, set())


if __name__ == "__main__":
    unittest.main()
