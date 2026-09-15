"""由 board_spec 生成原理图 plush-toy-mainboard.kicad_sch。

生成策略：每个器件单独放在网格上，**每个引脚末端放一个同名网络标签**，不画导线。
连接关系完全由标签名决定，与 board_spec 一一对应；人看原理图时按标签名跟网络。
NC_ 前缀网络在引脚上放「不连接」标记。

KiCad 格式要点（照 KiCad 10 自带 template 的实际写法）：
- lib_symbols 里的符号是展平的，不含 extends；派生符号要从父符号展开
- 每个放置的符号必须带 instances 块，否则位号在网表里会退化成 U?、R?
- 电源输入引脚所在网络若没有电源输出引脚驱动，ERC 报错；这类网络补一个 PWR_FLAG
"""
import re
import uuid
from pathlib import Path

import board_spec
import kicad_env

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "plush-toy-mainboard"
SCH = ROOT / f"{PROJECT}.kicad_sch"
PRO = ROOT / f"{PROJECT}.kicad_pro"

GRID = 2.54
PAPER_W = 1150.0          # A0 横向可用宽度，mm
LABEL_ROOM = 25.4         # 引脚两侧给标签留的水平空间
ROW_GAP = 12.7
VLABEL_ROOM = 17.78       # 上下两端竖排标签占用的高度
TEXT_ROWS = 5.08          # 大器件位号与取值两行文字的高度
SMALL_PART_PINS = 4       # 不超过这个引脚数的器件，位号取值放在原点右侧

_PIN_RE = re.compile(
    r'\(pin\s+(\w+)\s+\w+\s*\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\).*?\(number\s+"([^"]+)"', re.S)


def _uid() -> str:
    return str(uuid.uuid4())


def _snap(v: float) -> float:
    return round(v / GRID) * GRID


def _block(text: str, name: str) -> str:
    start = text.find(f'(symbol "{name}"')
    if start < 0:
        raise KeyError(name)
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ValueError(f"符号 {name} 括号不配平")


def lib_symbol(lib_id: str) -> str:
    """返回可直接嵌入 lib_symbols 的展平符号块，顶层名带库前缀，子单元名不带。"""
    lib, name = lib_id.split(":", 1)
    text = kicad_env.symbol_file(lib).read_text(encoding="utf-8")
    block = _block(text, name)
    parent = re.search(r'\(extends\s+"([^"]+)"\)', block)
    if parent:
        base = _block(text, parent.group(1))
        pname = parent.group(1)
        # 用父符号的图形与引脚，子单元改名为派生名；Value 改成派生名
        base = base.replace(f'(symbol "{pname}_', f'(symbol "{name}_')
        base = base.replace(f'(symbol "{pname}"', f'(symbol "{name}"', 1)
        base = re.sub(r'(\(property\s+"Value"\s+)"[^"]*"', rf'\1"{name}"', base, count=1)
        block = base
    return block.replace(f'(symbol "{name}"', f'(symbol "{lib_id}"', 1)


def pins_of(block: str) -> dict[str, tuple[float, float, str, int]]:
    """引脚号 → (x, y, 电气类型, 角度)。坐标为连接点，相对符号原点，y 轴向上。

    角度是引脚从连接点伸向符号本体的方向：0 表示本体在右（引脚在符号左侧），
    180 表示本体在左，90 表示本体在上（引脚在底部），270 表示本体在下。
    """
    pins: dict[str, tuple[float, float, str, int]] = {}
    for m in _PIN_RE.finditer(block):
        pins.setdefault(m.group(5), (float(m.group(2)), float(m.group(3)), m.group(1),
                                     int(float(m.group(4))) % 360))
    return pins


def _property(key: str, value: str, x: float, y: float, hide: bool, justify: str = "") -> str:
    hidden = "\n\t\t\t\t(hide yes)" if hide else ""
    just = f"\n\t\t\t\t(justify {justify})" if justify else ""
    return (f'\t\t(property "{key}" "{value}"\n\t\t\t(at {x:.2f} {y:.2f} 0)\n'
            f'\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t){hidden}{just}\n\t\t\t)\n\t\t)\n')


def _placed(lib_id: str, ref: str, value: str, footprint: str, lcsc: str, fitted: bool,
            on_board: bool, in_bom: bool, x: float, y: float, pin_numbers, root_uuid: str,
            ref_xy: tuple[float, float], value_xy: tuple[float, float]) -> str:
    out = [f'\t(symbol\n\t\t(lib_id "{lib_id}")\n\t\t(at {x:.2f} {y:.2f} 0)\n\t\t(unit 1)\n'
           f'\t\t(exclude_from_sim no)\n\t\t(in_bom {"yes" if in_bom else "no"})\n'
           f'\t\t(on_board {"yes" if on_board else "no"})\n\t\t(dnp {"no" if fitted else "yes"})\n'
           f'\t\t(uuid "{_uid()}")\n']
    out.append(_property("Reference", ref, *ref_xy, False, "left"))
    out.append(_property("Value", value, *value_xy, False, "left"))
    out.append(_property("Footprint", footprint, x, y, True))
    out.append(_property("Datasheet", "", x, y, True))
    if lcsc:
        out.append(_property("LCSC", lcsc, x, y, True))
    for number in pin_numbers:
        out.append(f'\t\t(pin "{number}"\n\t\t\t(uuid "{_uid()}")\n\t\t)\n')
    out.append(f'\t\t(instances\n\t\t\t(project "{PROJECT}"\n\t\t\t\t(path "/{root_uuid}"\n'
               f'\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n')
    return "".join(out)


def _label(net: str, x: float, y: float, pin_angle: int) -> str:
    # 标签朝引脚的反方向伸出，文字落在符号本体之外，不压住引脚名。
    # 只改文字朝向，锚点仍在引脚末端，电气连接不受影响。
    angle = (pin_angle + 180) % 360
    justify = "left bottom" if angle in (0, 90) else "right bottom"
    shown = angle if angle in (0, 90) else angle - 180
    return (f'\t(global_label "{net}"\n\t\t(shape input)\n\t\t(at {x:.2f} {y:.2f} {shown})\n\t\t(effects\n\t\t\t(font\n'
            f'\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify {justify})\n\t\t)\n\t\t(uuid "{_uid()}")\n\t)\n')


def _no_connect(x: float, y: float) -> str:
    return f'\t(no_connect\n\t\t(at {x:.2f} {y:.2f})\n\t\t(uuid "{_uid()}")\n\t)\n'


def _flag_nets(blocks: dict[str, str]) -> list[str]:
    """有电源输入引脚、但没有电源输出引脚驱动的网络。"""
    kinds: dict[str, set[str]] = {}
    for part in board_spec.PARTS:
        if not part.fitted:
            continue
        pins = pins_of(blocks[part.symbol])
        for number, net in part.pins.items():
            if not net.startswith("NC_"):
                kinds.setdefault(net, set()).add(pins[number][2])
    return sorted(n for n, k in kinds.items() if "power_in" in k and "power_out" not in k)


def main() -> Path:
    root_uuid = _uid()
    blocks: dict[str, str] = {}
    for part in board_spec.PARTS:
        if part.symbol not in blocks:
            blocks[part.symbol] = lib_symbol(part.symbol)
    flag_id = "power:PWR_FLAG"
    blocks[flag_id] = lib_symbol(flag_id)

    body: list[str] = []
    cursor_x, cursor_y, row_h = 25.4, 25.4, 0.0

    def place(lib_id, ref, value, footprint, lcsc, fitted, on_board, in_bom, pin_nets):
        nonlocal cursor_x, cursor_y, row_h
        pins = pins_of(blocks[lib_id])
        xs = [p[0] for p in pins.values()] or [0.0]
        ys = [p[1] for p in pins.values()] or [0.0]
        width = max(xs) - min(xs) + 2 * LABEL_ROOM
        height = max(ys) - min(ys) + 2 * VLABEL_ROOM + TEXT_ROWS + ROW_GAP
        if cursor_x + width > PAPER_W:
            cursor_x, cursor_y, row_h = 25.4, cursor_y + row_h, 0.0
        # 符号原点放在包围盒左侧留出标签空间之后，并对齐 2.54 网格保证引脚落在网格上
        x = _snap(cursor_x + LABEL_ROOM - min(xs))
        y = _snap(cursor_y + max(ys) + VLABEL_ROOM)
        if len(pins) <= SMALL_PART_PINS:
            # 小器件：上下两端的竖排标签占住正上方和正下方，位号取值放原点右侧才不被压住
            ref_xy, value_xy = (x + 2.54, y - 1.27), (x + 2.54, y + 1.27)
        else:
            # 大器件：原点在本体中央，放右侧会压住引脚名，改放本体下方、底部竖排标签之外
            below = y - min(ys) + VLABEL_ROOM
            ref_xy, value_xy = (x + min(xs), below), (x + min(xs), below + 2.54)
        body.append(_placed(lib_id, ref, value, footprint, lcsc, fitted, on_board, in_bom,
                            x, y, pins.keys(), root_uuid,
                            ref_xy, value_xy))
        for number, net in pin_nets.items():
            px, py, _, pin_angle = pins[number]
            ax, ay = x + px, y - py      # 符号坐标 y 轴向上，原理图坐标 y 轴向下
            body.append(_no_connect(ax, ay) if net.startswith("NC_") else _label(net, ax, ay, pin_angle))
        cursor_x += width
        row_h = max(row_h, height)

    for part in board_spec.PARTS:
        place(part.symbol, part.ref, part.value, part.footprint, part.lcsc, part.fitted,
              part.fitted, part.fitted and part.assembly, part.pins)
    for index, net in enumerate(_flag_nets(blocks), start=1):
        place(flag_id, f"#FLG{index:02d}", "PWR_FLAG", "", "", True, False, False, {"1": net})

    head = [f'(kicad_sch\n\t(version {kicad_env.SCH_FILE_VERSION})\n\t(generator "plush_gen")\n'
            f'\t(generator_version "10.0")\n\t(uuid "{root_uuid}")\n\t(paper "A0")\n\t(lib_symbols\n']
    head += [f"\t\t{b}\n" for b in blocks.values()]
    head.append("\t)\n")
    tail = '\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)\n\t(embedded_fonts no)\n)\n'
    SCH.write_text("".join(head) + "".join(body) + tail, encoding="utf-8")
    if not PRO.exists():
        PRO.write_text("{}\n", encoding="utf-8")
    return SCH


if __name__ == "__main__":
    print(main())
