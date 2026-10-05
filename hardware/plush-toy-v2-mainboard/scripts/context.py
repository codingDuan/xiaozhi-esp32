"""当前版本的上下文：器件、网络与文件路径。所有生成脚本用 --variant 选版本。"""
import argparse
import importlib
from dataclasses import dataclass
from pathlib import Path

from v2 import variants

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Ctx:
    variant: variants.Variant
    parts: list
    nets: dict
    dir: Path
    project: str

    @property
    def sch(self) -> Path:
        return self.dir / f"{self.project}.kicad_sch"

    @property
    def pcb(self) -> Path:
        return self.dir / f"{self.project}.kicad_pcb"

    @property
    def pro(self) -> Path:
        return self.dir / f"{self.project}.kicad_pro"

    @property
    def build(self) -> Path:
        return self.dir / "build"

    @property
    def placement(self):
        return importlib.import_module(f"placement_{self.variant.name}")


def load(name: str) -> Ctx:
    return Ctx(variants.VARIANTS[name], variants.parts(name), variants.nets(name),
               ROOT / "variants" / name, f"plush-toy-v2-{name}")


def from_argv() -> Ctx:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True, choices=sorted(variants.VARIANTS))
    return load(parser.parse_args().variant)
