"""DiffAddr (64 KiB replacement table) builder.

Straight port of the GenDiffAddrTable reconstruction. ``EMPTY`` (0xFFFF) marks
a slot with no candidate.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import pretest_layout as layout

EMPTY = 0xFFFF


class DiffError(RuntimeError):
    def __init__(self, code: int, message: str = ""):
        super().__init__(message or f"diffaddr failed (reason {code})")
        self.code = code


@dataclass
class _Geom:
    c: int = 0
    w: int = 0
    planes: int = 0
    slots: int = 0
    rows: int = 0
    boundary: int = 0
    shift: int = 0
    mask: int = 0
    bitmap_words: int = 0
    pool: int = 0
    type2: bool = False


@dataclass
class DiffSummary:
    n1: int = 0
    n2: int = 0
    total: int = 0
    bad_rows: int = 0
    rt_counts: bytes = b""


def _slot_of(g: _Geom, ch: int, w: int, p: int) -> int:
    return (ch * g.w + w) * g.planes + p


def _nth_bit(mask: int, n: int) -> int:
    for i in range(4):
        if mask & (1 << i):
            if not n:
                return i
            n -= 1
    return -1


def _floor_log2(v: int) -> int:
    r = 0
    while v >> 1:
        v >>= 1
        r += 1
    return r


def _is_bad(param: bytes | bytearray, raw: bytes, block: int, ch: int, w: int, p: int) -> int:
    pch = _nth_bit(param[0x10] & 0x0F, ch)
    chips = param[0x17]
    if not chips:
        return -1
    lce = w // chips
    die = w % chips
    pce = _nth_bit(param[0x11] & 0x0F, lce)
    if pch < 0 or pce < 0:
        return -1
    off = block * 64 + pch * 16 + pce * 4 + p
    if off >= len(raw):
        return -1
    return (raw[off] >> die) & 1


def _split_system(param: bytes | bytearray, index: int):
    a = layout.system_address(param, index)
    if a is None:
        return None
    return a.block, a.logical_ch, a.logical_ce * param[0x17] + a.die, a.plane


def _fill_from_end(a, idx) -> None:
    count = len(idx)
    if not count:
        return
    left, right = 0, count - 1
    while left < right:
        if a[idx[left]] != EMPTY:
            left += 1
        elif a[idx[right]] == EMPTY:
            right -= 1
        else:
            a[idx[left]] = a[idx[right]]
            a[idx[right]] = EMPTY


def _type2_repack(g: _Geom, a, base: int, last: int) -> tuple[int, int]:
    """``a[base + r*slots + s]``; row 0 of the tail is row ``base/slots``."""
    if _floor_log2(g.slots) + g.shift > 16:
        return 0, 8
    for r in range(last + 1):
        for s in range(g.slots):
            pos = base + r * g.slots + s
            if a[pos] != EMPTY:
                a[pos] = (a[pos] | ((s << g.shift) & 0xFFFF)) & 0xFFFF
    for ch in range(g.c):
        idx = []
        for r in range(last + 1):
            for w in range(g.w):
                for p in range(g.planes):
                    idx.append(base + r * g.slots + _slot_of(g, ch, w, p))
        _fill_from_end(a, idx)

    same = 0
    for r in range(last + 1):
        if all(a[base + r * g.slots + s] != EMPTY for s in range(g.slots)):
            same += 1
    start = base + same * g.slots
    end = base + (last + 1) * g.slots
    if end > start:
        _fill_from_end(a, list(range(start, end)))
    mixed = 0
    for r in range(same, last + 1):
        if all(a[base + r * g.slots + s] != EMPTY for s in range(g.slots)):
            mixed += 1
    return same + mixed, 0


def _reserve_rt(g: _Geom, a, base: int, last: int, counts: bytearray, rt):
    for r in range(last + 1):
        for s in range(g.slots):
            pos = base + r * g.slots + s
            if counts[s] < g.pool and a[pos] != EMPTY:
                rt[s * g.pool + r] = a[pos]
                counts[s] = (r + 1) & 0xFF
                a[pos] = EMPTY


def _lookup(g: _Geom, param: bytes | bytearray, row: int, ch: int, w: int, p: int, header, values):
    base = header[row] & 0x7FFF
    s = _slot_of(g, ch, w, p) & 0xFF
    if not (values[base + s // 16] & (1 << (s % 16))):
        return row, ch, w, p
    rank = 0
    for j in range(s):
        rank += (values[base + j // 16] >> (j % 16)) & 1
    v = values[base + g.bitmap_words + rank]
    if header[row] & 0x8000:
        t = (v >> g.shift) & 0xFF
        q = param[0x6A]
        pl = param[0x13]
        if not q or not pl:
            return v, ch, w, p
        ch = t // q
        t %= q
        w = t // pl
        p = t % pl
        return v & g.mask, ch, w, p
    return v, ch, w, p


def _claim(g: _Geom, block: int, ch: int, w: int, p: int, occupied: bytearray) -> int:
    if block >= g.rows:
        return 3
    bit = ((block * g.c + ch) * g.w + w) * g.planes + p
    byte = bit >> 3
    if byte >= len(occupied):
        return 7
    if occupied[byte] & (1 << (bit & 7)):
        return 2
    occupied[byte] |= 1 << (bit & 7)
    return 0


def _compact_back(f, g: _Geom, last: int) -> int:
    maximum = 0
    for s in range(g.slots):
        front, back = 0, last
        left = f[front * g.slots + s]
        right = f[back * g.slots + s]
        saw_hole = left == EMPTY
        saw_good = right != EMPTY
        if back >= front:
            while True:
                while left != EMPTY and front < last:
                    front += 1
                    left = f[front * g.slots + s]
                    if left == EMPTY:
                        saw_hole = True
                while right == EMPTY and back > 0:
                    back -= 1
                    right = f[back * g.slots + s]
                    if right != EMPTY:
                        saw_good = True
                if back == front:
                    if front == last:
                        front = last + 1
                    elif back == 0:
                        front = 1
                if not (saw_hole and saw_good and back > front):
                    break
                f[front * g.slots + s] = right
                f[back * g.slots + s] = EMPTY
                saw_hole = saw_good = False
                if front >= last:
                    break
                front += 1
                left = f[front * g.slots + s]
                if left == EMPTY:
                    saw_hole = True
                if back == 0:
                    break
                back -= 1
                right = f[back * g.slots + s]
                if right != EMPTY:
                    saw_good = True
                if back < front:
                    break
        if back > maximum:
            maximum = back
    return maximum


def _encode(
    g: _Geom,
    param: bytes | bytearray,
    n1: int,
    total: int,
    full,
    compact,
    header,
    values,
    types,
    value_words: int,
) -> int:
    cursor = 0
    ordinal = 0
    type_id = 0
    for row in range(g.boundary, g.rows):
        if (compact[row >> 3] & (1 << (row & 7))) and ordinal < total:
            base = 0 if ordinal == 0 else cursor
            header[row] = base
            if ordinal >= n1:
                header[row] |= 0x8000
                types[type_id] = row
                type_id += 1
            exceptions = 0
            for s in range(g.slots):
                v = full[ordinal * g.slots + s]
                if ordinal < n1:
                    changed = v != row
                else:
                    changed = ((v & g.mask) != row) or ((v >> g.shift) != s)
                if changed:
                    if base + g.bitmap_words + exceptions >= value_words:
                        return 1
                    values[base + s // 16] |= 1 << (s % 16)
                    values[base + g.bitmap_words + exceptions] = v
                    exceptions += 1
            cursor = (base + g.bitmap_words + exceptions) & 0xFFFF
            compact[row >> 3] &= ~(1 << (row & 7)) & 0xFF
            ordinal += 1
        if ordinal == total:
            break
    if 2 * ((param[0x9C] | param[0x9D] << 8) + cursor) > 0x4800:
        return 1
    return 0


def _check_all(
    g: _Geom, param: bytes | bytearray, compact: bytes | bytearray, header, values, counts, rt
) -> tuple[int, int]:
    bitmap_bytes = (g.rows * g.slots + 7) // 8
    occupied = bytearray(bitmap_bytes)

    for i in range(8):
        split = _split_system(param, param[0x20 + i])
        if split is None:
            return 0, 3
        block, ch, w, p = split
        rc = _claim(g, block, ch, w, p, occupied)
        if rc:
            return 0, rc

    bad = 0
    for row in range(g.boundary, g.rows):
        if compact[row >> 3] & (1 << (row & 7)):
            bad += 1
            continue
        for ch in range(g.c):
            for w in range(g.w):
                for p in range(g.planes):
                    b, c2, w2, p2 = row, ch, w, p
                    if header[row] != EMPTY:
                        b, c2, w2, p2 = _lookup(g, param, row, ch, w, p, header, values)
                    rc = _claim(g, b, c2, w2, p2, occupied)
                    if rc:
                        return 0, rc

    for ch in range(g.c):
        for w in range(g.w):
            for p in range(g.planes):
                s = _slot_of(g, ch, w, p)
                for i in range(counts[s]):
                    rc = _claim(g, rt[s * g.pool + i], ch, w, p, occupied)
                    if rc:
                        return 0, rc
    return bad, 0


def _word_bytes(words) -> bytes:
    out = bytearray(2 * len(words))
    for i, v in enumerate(words):
        out[2 * i : 2 * i + 2] = (v & 0xFFFF).to_bytes(2, "little")
    return bytes(out)


def build(
    param_in: bytes, drive: bytes, raw_bad: bytes, compact_in: bytes, capacity: int = 0x10000
) -> tuple[bytes, DiffSummary, bytes]:
    param = bytearray(param_in)
    shape, rc = layout.diff_shape(drive, param)
    if rc:
        raise DiffError(rc, f"diff shape failed (reason {rc})")

    g = _Geom()
    g.c = param[0x14]
    g.w = param[0x12]
    g.planes = param[0x13]
    g.slots = param[0x1E]
    g.rows = param[0x32] | param[0x33] << 8
    g.boundary = param[0x30] | param[0x31] << 8
    g.shift = param[0x9E]
    g.mask = param[0x9A] | param[0x9B] << 8
    g.bitmap_words = param[0x6B]
    g.pool = param[0x44]
    g.type2 = param[0x69] == 2
    if (
        not g.c
        or not g.w
        or not g.planes
        or not g.slots
        or not g.rows
        or g.rows > layout.BAD_ROWS
        or g.slots > 64
        or g.c * g.w * g.planes != g.slots
        or g.boundary > g.rows
        or not g.pool
    ):
        raise DiffError(-1, "invalid geometry")

    full = [EMPTY] * (g.rows * g.slots)
    header = [EMPTY] * shape.header_words
    value_words = shape.values_bytes // 2
    values = [0] * value_words
    types = [EMPTY] * 64
    rt = [EMPTY] * (g.pool * g.slots)
    counts = bytearray(g.slots)
    compact = bytearray(compact_in[:512])

    selected = 0
    for block in range(g.boundary, g.rows):
        if not (compact[block >> 3] & (1 << (block & 7))):
            continue
        for ch in range(g.c):
            for w in range(g.w):
                for p in range(g.planes):
                    bad = _is_bad(param, raw_bad, block, ch, w, p)
                    if bad < 0:
                        raise DiffError(-1, "bad-block table too small")
                    full[selected * g.slots + _slot_of(g, ch, w, p)] = EMPTY if bad else block
        selected += 1

    index = ((g.boundary - 1) * g.slots) & 0xFF
    guard = 0
    while index < g.boundary * g.slots and guard < 256:
        guard += 1
        split = _split_system(param, index)
        if split is None:
            raise DiffError(3, "system address decode failed")
        block, ch, w, p = split
        bad = _is_bad(param, raw_bad, block, ch, w, p)
        if bad < 0:
            raise DiffError(-1, "bad-block table too small")
        full[selected * g.slots + _slot_of(g, ch, w, p)] = (
            block if (index > param[0x27] and not bad) else EMPTY
        )
        index += 1
        if not index:
            break

    max_back = _compact_back(full, g, selected)
    n1 = 0
    while n1 < g.rows:
        if any(full[n1 * g.slots + s] == EMPTY for s in range(g.slots)):
            break
        n1 += 1
    retained = max_back + 1
    if n1 > retained:
        raise DiffError(10, "complete rows exceed retained rows")
    tail_last = retained - n1
    tail_base = n1 * g.slots
    if g.type2:
        n2, trc = _type2_repack(g, full, tail_base, tail_last)
    else:
        _reserve_rt(g, full, tail_base, tail_last, counts, rt)
        n2, trc = 0, 0
    if trc:
        raise DiffError(trc)
    total = n1 + n2

    trc = _encode(g, param, n1, total, full, compact, header, values, types, value_words)
    if trc:
        raise DiffError(trc, "diff table encode overflow")

    header_words = list(header)
    header_bytes = bytearray(_word_bytes(header_words))
    header_bytes[2 * g.rows : 2 * g.rows + g.slots] = counts
    header_view = [
        header_bytes[2 * i] | header_bytes[2 * i + 1] << 8 for i in range(len(header_bytes) // 2)
    ]

    bad_rows, trc = _check_all(g, param, compact, header_view, values, counts, rt)
    if trc:
        raise DiffError(trc, "diff table allocation check failed")

    # Check All Mapping (41A23A..41A24F) publishes unrecovered rows.
    param[0x3E:0x40] = bad_rows.to_bytes(2, "little")

    out = layout.pack_diff(
        param,
        bytes(header_bytes),
        _word_bytes(values),
        _word_bytes(types),
        _word_bytes(rt),
        capacity,
    )
    if out is None:
        raise DiffError(1, "diff table packing failed")
    summary = DiffSummary(n1=n1, n2=n2, total=total, bad_rows=bad_rows, rt_counts=bytes(counts))
    return out, summary, bytes(param)
