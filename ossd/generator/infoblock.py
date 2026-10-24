"""InfoBlock sizing, generation and SaveInfoBlock framing."""

from __future__ import annotations

from dataclasses import dataclass

from . import physical
from . import pretest_layout as layout


@dataclass
class Sizes:
    boot_bytes: int = 0
    param_sectors: int = 2
    seed_bytes: int = 0
    org_sectors: int = 0
    erase_sectors: int = 0
    third_sectors: int = 0
    total_sectors: int = 0
    compact_sectors: int = 0
    diff_sectors: int = 0
    oprom_sectors: int = 0
    rdt_sectors: int = 0
    bank_part0_sectors: int = 256
    bank_part1_sectors: int = 0


@dataclass
class Layout:
    descriptor: bytes = b""
    total_sectors: int = 0
    total_pages: int = 0


@dataclass
class Payloads:
    param: bytes = b""
    param_sectors: int = 2
    org: bytes = b""
    org_sectors: int = 0
    erase: bytes = b""
    erase_sectors: int = 0
    total: bytes = b""
    total_sectors: int = 0
    compact: bytes = b""
    compact_sectors: int = 0
    diff: bytes = b""
    diff_sectors: int = 0
    oprom: bytes = b""
    oprom_sectors: int = 0
    rdt: bytes = b""
    rdt_sectors: int = 0


ORDER = (0, 1, 3, 2, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14)

CHECKS = (
    (0, 0x19),
    (2, 0x17),
    (3, 0x18),
    (4, 0x20),
    (1, 0x21),
    (5, 0x22),
    (9, 0x23),
    (10, 0x24),
    (11, 0x27),
)

WRITES = (
    (0x70, 5),
    (0x71, 6),
    (0x73, 8),
    (0x74, 9),
    (0x75, 10),
    (0x45, 13),
    (0x76, 14),
    (0x7B, 4),
    (0xBE, 11),
    (0xBF, 12),
)


def _pages(sectors: int, per_page: int) -> int:
    return (sectors + per_page - 1) // per_page


def calculate(param: bytearray, z: Sizes) -> tuple[Layout, int]:
    per_page = param[0x43]
    if not per_page:
        return Layout(), -1
    boot_sectors = (z.boot_bytes + 511) >> 9
    seed_sectors = (z.seed_bytes + 511) >> 9
    qboot = boot_sectors // 3

    counts = [0] * 15
    counts[0] = _pages(qboot, per_page)
    counts[2] = counts[0]
    counts[3] = counts[0]
    counts[1] = _pages(z.param_sectors & 0xFF, per_page)
    counts[4] = _pages(seed_sectors, per_page)
    counts[5] = _pages(z.org_sectors, per_page)
    counts[6] = _pages(z.erase_sectors, per_page)
    counts[8] = _pages(z.total_sectors, per_page)
    counts[9] = _pages(z.compact_sectors, per_page)
    counts[10] = _pages(z.diff_sectors, per_page)
    counts[11] = _pages(z.oprom_sectors, per_page)
    counts[12] = _pages(z.rdt_sectors, per_page)
    counts[13] = _pages(z.bank_part1_sectors, per_page)

    for slot, reason in CHECKS:
        if not counts[slot]:
            return Layout(), reason
    if not counts[12] and z.rdt_sectors:
        return Layout(), 0x28

    bank0 = _pages(z.bank_part0_sectors, per_page)
    if not bank0 or not counts[13]:
        return Layout(), 0x25

    d = [0] * 15
    d[7] = 0xCC
    for i in range(len(ORDER) - 1):
        start, end = ORDER[i], ORDER[i + 1]
        d[end] = d[start] + counts[start]
    if d[13] > d[14] or d[12] > d[13]:
        return Layout(), 0x29
    total_pages = d[14] + bank0
    total_sectors = total_pages * per_page
    if total_pages > (param[0x48] | param[0x49] << 8):
        return Layout(), 0x26

    for dst, src in WRITES:
        param[dst] = d[src]
    return Layout(descriptor=bytes(d), total_sectors=total_sectors, total_pages=total_pages), 0


def _tag6(p: bytes, tag: bytes) -> bool:
    return p[:6] == tag


def _special_tag(bank: bytes, bank_sectors: int) -> bool:
    if bank_sectors * 512 < 0x30000:
        return False
    p = bank[0x2FFFA : 0x2FFFA + 6]
    return any(_tag6(p, t) for t in (b" BiCS3", b" BiCS4", b" IMB16", b"  SSV3", b"  SSV4"))


def _patch(
    target: bytearray, base: int, param: bytes | bytearray, d: bytes, mirror: bool, length: int
) -> bool:
    if base + 0x17EB > length:
        return False
    div = param[0x16] * param[0x13]
    if not div:
        return False
    target[base + 0x17E0] = 0xDA if param[0x0A] == 0xAD else param[0x58]
    if param[0x0C] & 0x02:
        target[base + 0x17E1] = 0x03
    target[base + 0x17E2] = 0x03 if mirror else 0x01
    if param[0x58] == 0xA2:
        target[base + 0x17E2] |= 0x02
    if param[0x0A] in (0x98, 0x45):
        target[base + 0x17E2] |= 0x04
    target[base + 0x17E3] = d[1]
    target[base + 0x17E4] = d[2]
    target[base + 0x17E5] = d[3]
    b0 = (param[0x20] // div) & 0xFFFF
    b1 = (param[0x21] // div) & 0xFFFF
    target[base + 0x17E7 : base + 0x17E9] = b0.to_bytes(2, "little")
    target[base + 0x17E9 : base + 0x17EB] = b1.to_bytes(2, "little")
    return True


def _copy_slot(
    out: bytearray, page_bytes: int, slot: int, src: bytes | bytearray, length: int
) -> bool:
    """Copies ``length`` bytes; a short payload is zero padded like the
    original callers' sector-padded buffers."""
    start = slot * page_bytes
    if not length:
        return True
    if src is None or start + length > len(out):
        return False
    take = min(len(src), length)
    out[start : start + take] = src[:take]
    return True


SEGMENTS = (
    (0, 1, 0xFF),
    (1, 3, 0xFF),
    (3, 2, 0xFF),
    (2, 4, 0xFF),
    (4, 5, 0x00),
    (5, 6, 0x01),
    (6, 8, 0x02),
    (8, 9, 0x04),
    (9, 10, 0x05),
    (10, 11, 0x06),
    (11, 12, 0x07),
    (12, 13, 0x08),
)


def generate(
    param: bytearray,
    layout_in: Layout,
    out_sectors: int,
    boot: bytes,
    seed: bytes,
    pl: Payloads,
    bank: bytes,
    bank_sectors: int,
) -> tuple[bytes, bytes, bytes, bytes, bool, int]:
    """Returns (infoblock, typemap, patched_boot, patched_bank, special, rc)."""
    per_page = param[0x43]
    if not per_page:
        return b"", b"", boot, bank, False, -1
    page_bytes = per_page * 512
    total_pages = out_sectors // per_page
    out_bytes = out_sectors * 512
    d = layout_in.descriptor

    special = _special_tag(bank, bank_sectors)
    mirror = 0
    if special:
        if bank_sectors * 512 < 0x20000:
            return b"", b"", boot, bank, special, 0x27
        mirror = bank_sectors * 512 - 0x20000
        if mirror + 12 > bank_sectors * 512 or bank[mirror : mirror + 12] != b"SM2263AABTAO":
            return b"", b"", boot, bank, special, 0x27

    boot_buf = bytearray(boot)
    bank_buf = bytearray(bank)
    if not _patch(boot_buf, 0, param, d, False, len(boot_buf)):
        return b"", b"", boot, bank, special, -1
    if special and not _patch(bank_buf, mirror, param, d, True, len(bank_buf)):
        return b"", b"", boot, bank, special, -1

    out = bytearray(out_bytes)
    type_map = bytearray(b"\xaa" * (total_pages + 1))
    third = len(boot_buf) // 3

    pieces = (
        (d[0], boot_buf, third),
        (d[1], pl.param, pl.param_sectors * 512),
        (d[2], boot_buf[0x1800:], third),
        (d[3], boot_buf[0x3000:], third),
        (d[4], seed, len(seed)),
        (d[5], pl.org, pl.org_sectors * 512),
        (d[6], pl.erase, pl.erase_sectors * 512),
        (d[8], pl.total, pl.total_sectors * 512),
        (d[9], pl.compact, pl.compact_sectors * 512),
        (d[10], pl.diff, pl.diff_sectors * 512),
        (d[11], pl.oprom, pl.oprom_sectors * 512),
        (d[12], pl.rdt, pl.rdt_sectors * 512),
        (d[13], bytes(bank_buf), bank_sectors * 512),
    )
    for slot, src, length in pieces:
        if not _copy_slot(out, page_bytes, slot, src, length):
            return b"", b"", boot, bank, special, -1

    for a, b, kind in SEGMENTS:
        type_map[d[a] : d[b]] = bytes([kind]) * (d[b] - d[a])
    type_map[d[13] : total_pages] = b"\x09" * (total_pages - d[13])

    sig = d[1] * page_bytes
    if sig + 9 > out_bytes or out[sig : sig + 9] != b"SM2263PAR":
        return b"", b"", boot, bank, special, 0x26
    return bytes(out), bytes(type_map), bytes(boot_buf), bytes(bank_buf), special, 0


def sum32(data: bytes) -> int:
    return sum(data) & 0xFFFFFFFF


# ---- SaveInfoBlock framing ----


def _phys_from_system(a: layout.SystemAddress, mode: int = 0, page: int = 0) -> physical.PhysAddr:
    return physical.PhysAddr(
        block=a.block, page=page, channel=a.ch, ce=a.ce, die=a.die, plane=a.plane | 0x80, mode=mode
    )


def erase_sqe(a: layout.SystemAddress) -> bytes:
    return physical.erase_sqe(_phys_from_system(a, mode=0x84))


def write_mode_sqe(a: layout.SystemAddress, page: int, n512: int, mode: int) -> bytes:
    return physical.write_sqe(n512, _phys_from_system(a, mode=mode, page=page))


def write_sqe(a: layout.SystemAddress, page: int, n512: int) -> bytes:
    return write_mode_sqe(a, page, n512, 0x84)


def spare_s1(type_byte: int, page: int, plane: int) -> bytes:
    spare = bytearray(512)
    b = plane * 32
    spare[b + 0x00] = 0xE1
    spare[b + 0x01] = type_byte & 0xFF
    spare[b + 0x05] = page & 0xFF
    spare[b + 0x10] = 0xE1
    return bytes(spare)


def spare_s2(page: int, plane: int) -> bytes:
    spare = bytearray(512)
    b = plane * 32
    spare[b + 0x05] = page & 0xFF
    return bytes(spare)


def spare_idx(plane: int) -> bytes:
    spare = bytearray(512)
    b = plane * 32
    spare[b : b + 12] = b"\xff" * 12
    spare[b + 0x0C : b + 0x12] = b"\x5a\xaa\x5a\xaa\xe5\x25"
    return bytes(spare)


def checksum_sqe(a: layout.SystemAddress, count: int, n512: int, extra: int) -> bytes:
    return physical.checksum_query_sqe(n512, count, a.block, a.plane, a.ch, a.ce, a.die, extra)


def compare_reply(reply: bytes, expected: int) -> tuple[int, int]:
    if len(reply) < 4:
        return -1, 0
    device = physical.checksum_reply_value(reply)
    return (1 if device != expected else 0), device
