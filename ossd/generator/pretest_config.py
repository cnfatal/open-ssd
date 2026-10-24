"""SetChCeMap: derive channel/CE masks and per-CE internal chip counts."""

from __future__ import annotations

CELLS = 16


def _popcount(value: int) -> int:
    return bin(value).count("1")


def set_chce_map(matrix: bytes, internal: int, ch_mask: int, ce_mask: int, param: bytearray) -> int:
    """Returns 0 or the original error code (0x0C..0x10)."""
    row_ce = [0, 0, 0, 0]
    for ch in range(4):
        for ce in range(4):
            cell = matrix[ch * 4 + ce]
            if not cell:
                continue
            if _popcount(cell) != internal:
                return 0x0C
            row_ce[ch] |= 1 << ce

    derived_ce = 0
    derived_ch = 0
    for ch in range(4):
        if not row_ce[ch]:
            continue
        if derived_ce and derived_ce != row_ce[ch]:
            return 0x0D
        derived_ce = row_ce[ch]
        derived_ch |= 1 << ch

    if ch_mask and ce_mask:
        derived_ce &= ce_mask
        if derived_ce != ce_mask:
            return 0x0E
        derived_ch &= ch_mask
        if derived_ch != ch_mask:
            return 0x0F
    else:
        ce_mask, ch_mask = derived_ce, derived_ch

    channels = _popcount(ch_mask)
    ces = _popcount(ce_mask)
    param[0x10] = ch_mask
    param[0x11] = ce_mask
    param[0x14] = channels
    param[0x15] = ces

    internal_span = 0
    for ch in range(channels):
        if not (ch_mask & (1 << ch)):
            continue
        highest = 0
        for ce in range(4):
            cell = matrix[ch * 4 + ce]
            param[0xF8 + ce] = cell
            for bit in range(8):
                if cell & (1 << bit) and highest < bit:
                    highest = bit
        internal_span = highest + 1
        param[0xBD] = internal_span
        break

    if ch_mask and ce_mask and channels and ces and internal_span:
        return 0
    return 0x10
