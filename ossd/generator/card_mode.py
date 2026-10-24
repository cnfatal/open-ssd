"""C1/90 payload: ParamTable + seed tail, zero padded to a 512-byte boundary."""

from __future__ import annotations

PARAM_BYTES = 1024
TAIL_CAPACITY = 8192
MAX_BYTES = PARAM_BYTES + TAIL_CAPACITY

FAMILY_2304_EARLY = (0x00, 0x01, 0x0C, 0x0D, 0x0E, 0x10, 0x11, 0x14, 0x16, 0x18, 0x1C)
FAMILY_2304_DRIVE = (0x00, 0x01, 0x0C, 0x0D, 0x0E, 0x10, 0x11, 0x14, 0x16, 0x18)


def seed_table_early(family: int) -> int:
    return 2304 if family in FAMILY_2304_EARLY else 1536


def seed_table_drive_builder(family: int, page_number: int) -> int:
    if family in FAMILY_2304_DRIVE:
        return 2304
    return 2304 if page_number > 0x0600 else 1536


def seed_table_name(table: int) -> str:
    return {1536: "SeedTable1536.bin", 2304: "SeedTable2304.bin"}.get(table, "unknown")


def layout(tail_bytes: int) -> tuple[int, int]:
    """Returns (n512, total_bytes)."""
    if tail_bytes > TAIL_CAPACITY:
        raise ValueError("tail too large")
    total = PARAM_BYTES + tail_bytes
    n512 = (total + 511) >> 9
    if n512 * 512 > MAX_BYTES:
        raise ValueError("payload too large")
    return n512, n512 << 9


def build(param: bytes, tail: bytes | None = None) -> tuple[bytes, int, int]:
    """Returns (payload, n512, total_bytes)."""
    if len(param) != PARAM_BYTES:
        raise ValueError("param must be 1024 bytes")
    tail = tail or b""
    n512, total = layout(len(tail))
    payload = bytearray(total)
    payload[:PARAM_BYTES] = param
    if tail:
        payload[PARAM_BYTES : PARAM_BYTES + len(tail)] = tail
    return bytes(payload), n512, total
