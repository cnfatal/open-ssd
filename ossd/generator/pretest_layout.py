"""Pretest layout algorithms: bad-block merge, system address, capacity, diff
shape. Ported from SWPtest.dll; pure functions over byte buffers.
"""

from __future__ import annotations

from dataclasses import dataclass

BAD_ROWS = 4096
BAD_ROW_BYTES = 64
BAD_TABLE_BYTES = BAD_ROWS * BAD_ROW_BYTES
SUMMARY_BYTES = 528


def _le16(data: bytes | bytearray, off: int) -> int:
    return data[off] | data[off + 1] << 8


def _le32(data: bytes | bytearray, off: int) -> int:
    return int.from_bytes(data[off : off + 4], "little")


def _put16(buf: bytearray, off: int, value: int) -> None:
    buf[off] = value & 0xFF
    buf[off + 1] = (value >> 8) & 0xFF


def _put32(buf: bytearray, off: int, value: int) -> None:
    buf[off : off + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")


def _ceil_div(value: int, divisor: int) -> int:
    return value // divisor + (1 if value % divisor else 0)


def merge_bad(
    param: bytearray,
    original: bytes | bytearray,
    erase: bytes | bytearray,
    other: bytes | bytearray,
    total: bytearray,
    table_bytes: int,
    compact: bytearray,
) -> int:
    rows = _le16(param, 0x32)
    if rows > BAD_ROWS or rows > table_bytes // BAD_ROW_BYTES:
        return -1
    bad_rows = 0
    for row in range(rows):
        row_sum = 0
        base = row * 64
        for byte in range(64):
            pos = base + byte
            total[pos] |= original[pos] | erase[pos] | other[pos]
            row_sum += total[pos]
        if row_sum:
            compact[row // 8] |= 1 << (row % 8)
            bad_rows += 1
    compact[0x200:0x210] = b"PhySLCBlk_PASS!!"
    _put16(param, 0x3E, bad_rows)
    return 0


def count_rows(table: bytes | bytearray, rows: int) -> int:
    """Rows with at least one bit set; the vendor uses this for P+0x3E."""
    return sum(1 for row in range(rows) if any(table[row * 64 : (row + 1) * 64]))


def count_bad(table: bytes | bytearray, table_bytes: int, counters: bytearray) -> int:
    if table_bytes < BAD_TABLE_BYTES:
        return -1
    total = 0
    bad_rows = 0
    for row in range(BAD_ROWS):
        row_sum = 0
        for ch in range(4):
            for ce in range(4):
                for plane in range(4):
                    value = table[row * 64 + ch * 16 + ce * 4 + plane]
                    row_sum += value
                    for die in range(8):
                        if value & (1 << die):
                            counters[ch * 128 + ce * 32 + die * 4 + plane] = (
                                counters[ch * 128 + ce * 32 + die * 4 + plane] + 1
                            ) & 0xFF
                            total += 1
        if row_sum:
            bad_rows += 1
    _put16(counters, 0x200, total & 0xFFFF)
    _put16(counters, 0x202, bad_rows & 0xFFFF)
    counters[0x204:0x210] = b"BadCnt-Table"
    return 0


def _physical_slot(mask: int, logical: int) -> int:
    for physical in range(4):
        if mask & (1 << physical):
            if not logical:
                return physical
            logical -= 1
    return -1


@dataclass
class SystemAddress:
    block: int = 0
    plane: int = 0
    interleave: int = 0
    logical_ch: int = 0
    logical_ce: int = 0
    ch: int = 0
    ce: int = 0
    die: int = 0
    bad_byte_offset: int = 0
    bad_bit: int = 0


def system_address(param: bytes | bytearray, index: int) -> SystemAddress | None:
    if not param[0x13] or not param[0x14] or not param[0x16] or not param[0x17]:
        return None
    per_block = param[0x16] * param[0x13]
    a = SystemAddress()
    a.block = index // per_block
    remaining = index % per_block
    a.plane = remaining // param[0x16]
    remaining %= param[0x16]
    a.interleave = remaining // param[0x14]
    a.logical_ch = remaining % param[0x14]
    a.logical_ce = a.interleave // param[0x17]
    a.die = a.interleave % param[0x17]
    ch = _physical_slot(param[0x10], a.logical_ch)
    ce = _physical_slot(param[0x11], a.logical_ce)
    if ch < 0 or ce < 0 or a.plane >= 4 or a.die >= 8 or a.block >= BAD_ROWS:
        return None
    a.ch = ch
    a.ce = ce
    a.bad_byte_offset = a.block * 64 + a.ch * 16 + a.ce * 4 + a.plane
    a.bad_bit = 1 << a.die
    return a


@dataclass
class CapacityLayout:
    sectors_per_fblock: int = 0
    total_data_sectors: int = 0
    total_fblocks: int = 0
    later_bad_fblocks: int = 0
    system_fblocks: int = 0
    static_slc: int = 0
    type2_fblocks: int = 0
    nondata_fblocks: int = 0
    max_data_fblocks: int = 0
    data_fblocks: int = 0
    nominal_data_fblocks: int = 0
    reserve_fblocks: int = 0
    min_static_tlc: int = 0
    total_static_tlc: int = 0
    good_fblocks: int = 0
    min_good_fblocks: int = 0
    surplus_fblocks: int = 0
    gc_threshold: int = 0
    extra_tcg_fblocks: int = 0


_CAPACITY_SECTORS = (
    1974672,
    3928176,
    7835184,
    15649200,
    31277232,
    58626288,
    117231408,
    234441648,
    468862128,
    937703088,
    1250263728,
    1465149168,
    1875385008,
    2813066928,
    3750748848,
)


def capacity(drive: bytes, param: bytearray) -> tuple[CapacityLayout, int]:
    r = CapacityLayout()
    mode = drive[0x74]
    spare_ratio = drive[0x1C]
    if not mode:
        return r, 3
    r.total_fblocks = _le16(param, 0x32)
    r.later_bad_fblocks = _le16(param, 0x3E)
    r.system_fblocks = _le16(param, 0x30)
    r.static_slc = param[0x77]
    r.type2_fblocks = param[0x79]
    factor = 2 if param[0x0C] & 1 else 3 if param[0x0C] & 2 else 1
    r.sectors_per_fblock = _le16(param, 0x80) * 8 * param[0x8D] * factor
    r.nondata_fblocks = r.later_bad_fblocks + r.system_fblocks + r.static_slc + r.type2_fblocks
    if r.total_fblocks <= r.nondata_fblocks:
        return r, 1
    r.max_data_fblocks = r.total_fblocks - r.nondata_fblocks
    r.total_data_sectors = _le32(drive, 0x14)
    if not r.total_data_sectors:
        raw = r.total_fblocks * r.sectors_per_fblock
        for sectors in _CAPACITY_SECTORS:
            if raw > sectors:
                r.total_data_sectors = sectors
    if not r.sectors_per_fblock or not _le32(param, 0x4C):
        return r, -1
    before_extra = _ceil_div(r.total_data_sectors, r.sectors_per_fblock)
    extra = 0
    if (drive[0x6C] | drive[0x6D]) & 0x20:
        param[0xDF] = (8 - r.total_data_sectors % 8) % 8
        extra = param[0xDF]
    if drive[0x6C] & 0x20:
        extra += 0x8A000
    if drive[0x6D] & 0x20:
        extra += 0x8000
    r.total_data_sectors += extra
    r.data_fblocks = _ceil_div(r.total_data_sectors, r.sectors_per_fblock)
    r.extra_tcg_fblocks = r.data_fblocks - before_extra
    if r.extra_tcg_fblocks and r.extra_tcg_fblocks < r.static_slc:
        r.static_slc -= r.extra_tcg_fblocks
        param[0x77] = r.static_slc & 0xFF
    elif r.extra_tcg_fblocks > r.static_slc:
        return r, 6
    if r.max_data_fblocks * r.sectors_per_fblock < r.total_data_sectors:
        return r, 2
    r.nominal_data_fblocks = _ceil_div(r.total_data_sectors, _le32(param, 0x4C))
    if not spare_ratio:
        return r, 5
    spare_blocks = _ceil_div(r.data_fblocks, spare_ratio)
    r.min_static_tlc = r.data_fblocks + spare_blocks
    r.min_good_fblocks = r.min_static_tlc + r.system_fblocks + r.static_slc
    r.good_fblocks = r.total_fblocks - r.later_bad_fblocks - r.type2_fblocks
    if spare_blocks < 12 and r.min_good_fblocks - spare_blocks + 12 > r.good_fblocks:
        return r, 7
    if r.good_fblocks < r.min_good_fblocks:
        return r, 3
    r.surplus_fblocks = r.good_fblocks - r.min_good_fblocks
    if mode in (5, 7, 9):
        r.total_static_tlc = r.min_static_tlc
    elif mode in (3, 4, 12, 6, 8, 10, 15, 13, 17, 19, 21):
        r.total_static_tlc = r.min_static_tlc + r.surplus_fblocks
    else:
        return r, 3
    used = (
        r.system_fblocks
        + r.static_slc
        + r.total_static_tlc
        + r.later_bad_fblocks
        + r.type2_fblocks
        + (r.surplus_fblocks if mode in (5, 7, 9) else 0)
    )
    if used != r.total_fblocks:
        return r, 4
    r.reserve_fblocks = r.max_data_fblocks - r.data_fblocks
    r.gc_threshold = r.data_fblocks + (r.total_static_tlc - r.data_fblocks) // 2
    _put16(param, 0x2C, r.total_static_tlc)
    _put16(param, 0xB6, r.gc_threshold)
    _put16(param, 0x34, r.nominal_data_fblocks)
    _put32(param, 0x60, r.total_data_sectors)
    _put16(param, 0x3A, r.static_slc)
    return r, 0


@dataclass
class DiffShape:
    header_words: int = 0
    rt_entries_per_slot: int = 0
    slots: int = 0
    header_bytes: int = 0
    values_bytes: int = 0
    rt_bytes: int = 0
    output_bytes: int = 0


def diff_shape(drive: bytes, param: bytearray) -> tuple[DiffShape, int]:
    r = DiffShape()
    vendor = param[0x0A]
    r.rt_entries_per_slot = (
        64 if (vendor in (0x89, 0x2C) or (vendor in (0x98, 0x45) and drive[0x74] == 3)) else 128
    )
    r.slots = param[0x1E]
    raw = 2 * r.slots + _le16(param, 0x32) + 4
    words = raw + 8 - raw % 8
    if words > 0x23C0:
        return r, -1
    r.header_words = words
    r.header_bytes = 2 * words
    r.values_bytes = 0x4800 - 2 * (words + 0x40)
    r.rt_bytes = 2 * r.rt_entries_per_slot * r.slots
    if r.rt_bytes > 0x8000:
        return r, 9
    r.output_bytes = 0x8000 + r.rt_bytes
    param[0x44] = r.rt_entries_per_slot & 0xFF
    _put16(param, 0x9C, r.header_words)
    return r, 0


def pack_diff(
    param: bytes | bytearray,
    header: bytes,
    values: bytes,
    types: bytes,
    rt: bytes,
    capacity_bytes: int,
) -> bytes | None:
    """Lays the four parts into a zeroed ``capacity_bytes`` buffer."""
    header_bytes = 2 * _le16(param, 0x9C)
    rt_bytes = 2 * param[0x44] * param[0x1E]
    if header_bytes > 0x4780 or rt_bytes > 0x8000 or capacity_bytes < 0x8000 + rt_bytes:
        return None
    out = bytearray(capacity_bytes)
    out[:header_bytes] = header[:header_bytes]
    out[header_bytes:0x4780] = values[: 0x4780 - header_bytes]
    out[0x4780:0x4800] = types[:128]
    if rt_bytes:
        out[0x8000 : 0x8000 + rt_bytes] = rt[:rt_bytes]
    return bytes(out)
