from dataclasses import dataclass

from v2 import cam, core, nocam


@dataclass(frozen=True)
class Variant:
    name: str
    camera: bool
    double_sided: bool


VARIANTS = {
    "A": Variant("A", camera=False, double_sided=False),
    "B": Variant("B", camera=False, double_sided=True),
    "C": Variant("C", camera=True, double_sided=False),
    "D": Variant("D", camera=True, double_sided=True),
}


def parts(name: str) -> list:
    v = VARIANTS[name]
    extra = cam.camera_parts() if v.camera else nocam.nocam_parts()
    return core.core_parts(v.camera) + extra


def nets(name: str) -> dict[str, list[tuple[str, str]]]:
    result: dict[str, list[tuple[str, str]]] = {}
    for part in parts(name):
        if not part.fitted:
            continue
        for pin, net in part.pins.items():
            result.setdefault(net, []).append((part.ref, pin))
    return result
