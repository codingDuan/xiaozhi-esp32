"""用 KiCad 自带 Python 运行：shrink.py --variant A
按比例缩小板子，每轮宽或高减 1mm，直到放不下为止；打印每轮结果，不改 placement 文件。
定位坐标按比例缩放；模组 x 不动（天线必须伸出左边），角上的安装孔保持离两边 3.5mm。"""
import argparse
import importlib
import io
import contextlib

import context
import gen_pcb


def scaled(pl, base, w, h):
    sx, sy = w / base["W"], h / base["H"]
    pl.W, pl.H = w, h
    pl.EDGE_CONNECTORS = {r: (side, along * (sx if side in ("top", "bottom") else sy))
                          for r, (side, along) in base["EDGE"].items()}
    anchors = {}
    for r, (x, y, a) in base["ANCHORS"].items():
        if r == "U1":
            anchors[r] = (x, y * sy, a)
        elif r.startswith("H"):
            anchors[r] = (3.5 if x < base["W"] / 2 else w - 3.5, 3.5 if y < base["H"] / 2 else h - 3.5, a)
        else:
            anchors[r] = (x * sx, y * sy, a)
    pl.ANCHORS = anchors
    pl.NEAR = {r: (t if isinstance(t, str) else (t[0] * sx, t[1] * sy)) for r, t in base["NEAR"].items()}
    x1, y1, _, y2 = base["VSYS"]
    pl.VSYS_RECT = (x1 * sx, y1 * sy, w, y2 * sy)


def attempt(ctx) -> str:
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            gen_pcb.main(ctx)
        return "ok"
    except RuntimeError as e:
        return str(e).splitlines()[-1].strip()[:90]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True)
    args = parser.parse_args()
    ctx = context.load(args.variant)
    pl = ctx.placement
    base = {"W": pl.W, "H": pl.H, "EDGE": dict(pl.EDGE_CONNECTORS), "ANCHORS": dict(pl.ANCHORS),
            "NEAR": dict(pl.NEAR), "VSYS": pl.VSYS_RECT}
    w, h = pl.W, pl.H
    print(f"起点 {w}x{h}: {attempt(ctx)}")
    for axis in ("W", "H", "W", "H"):
        while True:
            nw, nh = (w - 1, h) if axis == "W" else (w, h - 1)
            scaled(pl, base, nw, nh)
            result = attempt(ctx)
            print(f"{nw}x{nh} ({nw * nh / 5400:.0%}): {result}")
            if result != "ok":
                break
            w, h = nw, nh
    print(f"最小可行 {w}x{h}")


if __name__ == "__main__":
    main()
