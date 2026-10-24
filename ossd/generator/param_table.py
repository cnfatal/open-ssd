"""ParamTable (P) derivation, ported from src/sm2263_param_table.c."""

from __future__ import annotations

from ..config.flash_set import SetRow
from .families import Traits
from .pretest_config import set_chce_map


class ParamError(RuntimeError):
    pass


def _rd16(buf, off: int) -> int:
    return buf[off] | buf[off + 1] << 8


def _rd32(buf, off: int) -> int:
    return buf[off] | buf[off + 1] << 8 | buf[off + 2] << 16 | buf[off + 3] << 24


def _wr16(buf, off: int, value: int) -> None:
    buf[off : off + 2] = (value & 0xFFFF).to_bytes(2, "little")


def _wr32(buf, off: int, value: int) -> None:
    buf[off : off + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")


def _bit_length(value: int) -> int:
    return value.bit_length()


def _l8(value: int) -> int:
    return 0 if value <= 1 else _bit_length(value) - 1


def _id_is(value: int, a: int, b: int) -> bool:
    return value == a or value == b


FIXED_50 = bytes((0x31, 0x3F, 0x15, 0x85, 0x05, 0xE0, 0x70, 0x78))
FIXED_5A = bytes((0x00, 0x32, 0x11, 0x81))
FIXED_60 = bytes((0xB0, 0x44, 0xF2, 0x1B))
ECC_LOOKUP = (0, 152, 228, 248)
ECC_OVERHEAD = (26, 22, 26)


def build_param_table(
    drive: bytearray,
    row: SetRow,
    matrix: bytes,
    internal: int,
    ch_mask: int,
    ce_mask: int,
    traits: Traits,
) -> bytearray:
    if row.count < 19:
        raise ParamError("SET row too short")
    id0 = row.columns[0] & 0xFF
    if row.columns[6] != traits.set_flash_type or drive[0x74] != traits.family or id0 != traits.id0:
        raise ParamError("family mismatch")

    param = bytearray(1024)
    param[0:10] = b"SM2263PARA"
    chce = set_chce_map(matrix, internal, ch_mask, ce_mask, param)
    if chce:
        raise ParamError(f"SetChCeMap failed: 0x{chce:02x}")

    id0b = drive[0x200]
    if id0b != id0:
        raise ParamError("drive/SET id mismatch")
    d218 = drive[0x218]
    d248 = drive[0x248]
    d2d0 = drive[0x2D0]

    p0b = p0c = p0d = 0
    if drive[0x0F] & 0x80:
        p0b |= 0x01
    if drive[0x13] & 0x80:
        p0b |= 0x02
    if _rd32(drive, 0x23C) > 1:
        p0b |= 0x04
    if (d2d0 & 0x40) and _id_is(id0b, 0x98, 0x45):
        p0b |= 0x10

    if d218 in (1, 3):
        p0c |= 0x01
    if d218 in (2, 4):
        p0c |= 0x02
    if drive[0xD4]:
        p0c |= 0x04
    if d248 and not (d248 & 0x10):
        p0c |= 0x08
    if d2d0 & 0x40:
        p0c |= 0x10
    if drive[0x238] > 1:
        p0c |= 0x20
    if id0b in (0x89, 0x2C, 0x9B):
        p0c |= 0x40
    if d2d0 & 0x20:
        p0c |= 0x80

    if d2d0 & 0x08:
        p0d |= 0x01
    if d2d0 & 0x04:
        p0d |= 0x02
    p0d |= 0x04
    if d2d0 & 0x02:
        p0d |= 0x08
    if d2d0 & 0x01:
        p0d |= 0x10
    if d248 & 0x01:
        p0d |= 0x20
    if d218 == 3:
        p0d |= 0x40
    elif d218 == 4:
        p0d &= 0xFF & ~0x40
    if _rd32(drive, 0x50) != 0 and _id_is(id0b, 0x89, 0x2C):
        p0d |= 0x80
    param[0x0B] = p0b
    param[0x0C] = p0c
    param[0x0D] = p0d

    param[0x0A] = drive[0x200]
    param[0xAF] = drive[0x74]
    param[0x1A] = d248 >> 5

    f1 = (drive[0x10] or param[0x15]) if drive[0x13] & 0x80 else 1
    f2 = (drive[0x0C] or drive[0x23C]) if drive[0x0F] & 0x80 else 1
    p12 = (f1 * f2) & 0xFF
    if _id_is(id0b, 0x89, 0x2C) and p12 >= 4:
        param[0x0D] &= 0xFF & ~0x10
    p13 = drive[0x238]
    p17 = drive[0x23C]
    p14 = param[0x14]
    p15 = param[0x15]
    p16 = (p12 * p14) & 0xFF
    p1e = (p16 * p13) & 0xFF
    param[0x12] = p12
    param[0x13] = p13
    param[0x17] = p17
    param[0xD0] = drive[0x6C]
    param[0xD1] = drive[0x78]
    param[0xD2] = drive[0x7C]
    param[0x16] = p16
    param[0x1E] = p1e
    param[0x1F] = (p14 * p13) & 0xFF
    param[0x1C] = _l8(p13)
    if not p12 or not p13:
        raise ParamError("geometry zero")
    param[0x1D] = ((p15 * p17) // p12) & 0xFF
    ceil16 = (p1e + 15) // 16
    param[0x6A] = (p12 * p13) & 0xFF
    param[0x6B] = (ceil16 or 1) & 0xFF

    d22c16 = _rd16(drive, 0x22C)
    d22c32 = _rd32(drive, 0x22C)
    p36 = d22c16 // p13 if p13 > 1 else d22c16
    p38 = (d22c32 // p13) & 0xFFFF
    _wr16(param, 0x36, p36)
    _wr16(param, 0x38, p38)
    _wr16(param, 0x32, p38)
    p1b = _bit_length((p38 - 1) & 0xFFFF) - _bit_length(511) + traits.p1b_bonus
    param[0x1B] = p1b & 0xFF

    page_kb = drive[0x21C]
    s = page_kb * 2 if page_kb in (4, 8, 16, 32) else 4
    plane_mul = p13 if p13 > 1 else 1
    param[0x40] = ((s // 2) * plane_mul) & 0xFF
    param[0x41] = (s * plane_mul) & 0xFF
    param[0x42] = (s // 2) & 0xFF
    param[0x43] = s & 0xFF

    p46 = _rd16(drive, 0x228)
    if param[0x0C] & 0x01:
        divisor = 2
    elif param[0x0C] & 0x02:
        divisor = 3
    elif drive[0x74] == 9:
        divisor = 4
    else:
        divisor = 1
    p48 = (p46 // divisor) & 0xFFFF
    p4a = (p48 * p1e) & 0xFFFF
    _wr16(param, 0x46, p46)
    _wr16(param, 0x48, p48)
    _wr16(param, 0x4A, p4a)
    c0 = (p46 * p1e) & 0xFFFFFFFF
    _wr32(param, 0xC0, c0)
    _wr32(param, 0xC4, (s // 8) * _rd32(param, 0xC0))
    _wr32(param, 0xC8, (s // 8) * _rd16(param, 0x4A))
    param[0x69] = drive[0x04]
    param[0x7A] = drive[0x08]
    if drive[0xC0] & 0x04:
        param[0xD3] |= 0x01
    for i in range(6):
        param[0xF0 + i] = drive[0x200 + 4 * i]

    total = ((page_kb << 10) + _rd16(drive, 0x220)) & 0xFFFF
    units = ((page_kb << 10) // 2048) & 0xFF
    if param[0x0D] & 0x80:
        shift = 2 if (_id_is(id0b, 0x89, 0x2C) and (param[0xD0] & 0x08)) else 1
        total = (total >> shift) & 0xFFFF
        units = (units >> shift) & 0xFF
    found = False
    eu = ev = 0
    payload = 0
    for eu in (3, 2, 1):
        for ev in (2, 1):
            payload = ((2048 + ECC_LOOKUP[eu]) * units) & 0xFFFF
            if payload + 26 + ECC_OVERHEAD[ev] <= total:
                found = True
                break
        if found:
            break
    if not found:
        eu = ev = 0
    if param[0x0D] & 0x80:
        _wr16(param, 0x0E, (total - payload) & 0xFFFF)
    param[0x18] = eu & 0xFF
    param[0x19] = ev & 0xFF

    param[0x50:0x58] = FIXED_50
    param[0x58] = traits.p58[0]
    param[0x59] = traits.p58[1]
    param[0x5A:0x5E] = FIXED_5A
    param[0x5E] = traits.p5e
    param[0x5F] = traits.p5f
    param[0x60:0x64] = FIXED_60

    R = _rd16(drive, 0x228)
    Q = ((R // divisor) * p1e) & 0xFFFFFFFF
    T0 = ((s // 8) * Q) & 0xFFFFFFFF
    T1 = ((s // 8) * (R * p1e)) & 0xFFFFFFFF
    DC, CE = traits.dc, traits.ce
    if not CE or T0 % CE:
        raise ParamError("T0 not divisible by CE")
    c9 = (T0 // CE) & 0xFFFF
    cc = (DC >> 2) & 0xFFFF
    e7 = (s // 8) & 0xFF
    e8_pre = ((((CE * 4) >> 9) + 7) >> 3) & 0xFF
    e8 = (((e7 + e8_pre - 1) // e7) * e7) & 0xFF
    ea = (CE - e8) & 0xFFFF
    _wr16(param, 0x82, cc)
    _wr16(param, 0x84, CE)
    _wr16(param, 0x86, CE)
    param[0x8D] = c9 & 0xFF
    _wr32(param, 0x4C, (cc << 3) & 0xFFFFFFFF)
    param[0x8A] = ((s + ((cc * 4) >> 9) - 1) // s) & 0xFF
    param[0x8E] = e7
    param[0x8F] = ((s * p13) // 8) & 0xFF
    param[0x8B] = e8
    _wr16(param, 0x80, ea)
    param[0x8C] = (128 // s) & 0xFF

    f8 = (traits.f8_base + traits.f8_delta) & 0xFFFF
    f4 = traits.f4_low if p16 == 2 else traits.f4_high
    fa = traits.fa
    ec = drive[0xD0] if _rd32(drive, 0xD0) else traits.default_ec
    f0_pre = ((((f4 * 4) >> 9) + 7) >> 3) & 0xFF
    f0 = (((e7 + f0_pre - 1) // e7) * e7) & 0xFF
    f6 = (f4 - f0) & 0xFFFF
    if not f4 or T1 % f4:
        raise ParamError("T1 not divisible by f4")
    f1b = (T1 // f4) & 0xFF
    tlc_data = (f6 * f1b) & 0xFFFFFFFF
    slc_data = (ea * c9) & 0xFFFFFFFF
    if _rd32(drive, 0x1C) == 0:
        _wr32(drive, 0x1C, 0x40)
    _wr16(param, 0x88, f4)
    param[0x9F] = f0
    _wr16(param, 0x7C, f6)
    param[0xBC] = f1b
    _wr16(param, 0xB6, f8)
    param[0x77] = ec
    _wr32(param, 0xB0, tlc_data)
    _wr32(param, 0xB8, slc_data)
    _wr16(param, 0xB4, fa)

    param[0x90] = _l8(s // 8)
    param[0x91] = _l8(p13)
    param[0x92] = _l8(p14)
    param[0x93] = _l8(p15)
    param[0x94] = _l8(p17)
    param[0x95] = param[0x90]
    param[0x96] = (param[0x95] + param[0x91]) & 0xFF
    param[0x98] = (param[0x96] + param[0x92]) & 0xFF
    param[0x97] = (param[0x98] + param[0x94]) & 0xFF
    param[0x99] = (param[0x97] + param[0x93]) & 0xFF
    param[0x9E] = _bit_length(p38) & 0xFF
    _wr16(param, 0x9A, ((1 << param[0x9E]) - 1) & 0xFFFF)

    param[0x7E] = drive[0]
    param[0x7F] = drive[1]
    for i in range(4):
        param[0xE0 + 4 * i] = drive[0x5C]
        param[0xE0 + 4 * i + 1] = drive[0x80 + 4 * i]
        param[0xE0 + 4 * i + 2] = drive[0x90 + 4 * i]
        param[0xE0 + 4 * i + 3] = ((drive[0xB0 + 4 * i] << 4) | drive[0xA0 + 4 * i]) & 0xFF

    if p13 == 1:
        param[0x0C] &= 0xFF & ~0x20
        param[0x0D] &= 0xFF & ~0x03
    if p17 == 1:
        param[0x0B] &= 0xFF & ~0x01
    if p15 == 1 and p17 == 1:
        p12 = 1
        param[0x0B] &= 0xFF & ~0x02
    if p15 != 1 and not (param[0x0B] & 0x02):
        p12 = 1
        p16 = (p12 * p14) & 0xFF
    param[0x12] = p12
    param[0x16] = p16

    return param
