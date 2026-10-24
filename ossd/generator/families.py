"""NAND family constants used by the ParamTable derivation.

They live in code because the vendor package does not ship them: the original
tool keeps them inside its DLL. Keyed by the first ID byte.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Traits:
    id0: int
    family: int
    set_flash_type: int
    dc: int
    ce: int
    f8_base: int
    f8_delta: int
    f4_low: int
    f4_high: int
    fa: int
    default_ec: int
    p58: tuple[int, int]
    p5e: int
    p5f: int
    p1b_bonus: int


_TAS = Traits(
    id0=0x9B,
    family=0x15,
    set_flash_type=4,
    dc=0x1C000,
    ce=0x1800,
    f8_base=0x18E,
    f8_delta=5,
    f4_low=0x1800,
    f4_high=0x3000,
    fa=0x00C7,
    default_ec=0x25,
    p58=(0xDA, 0xDF),
    p5e=0xFC,
    p5f=0xD0,
    p1b_bonus=1,
)

BUILTIN = {0x9B: _TAS}


def builtin_traits(id0: int) -> Traits | None:
    return BUILTIN.get(id0)
