"""Exact read-request policy and the two decoders the CLI prints."""

from __future__ import annotations

MODE_UNKNOWN, MODE_MPISP, MODE_ISP = 0, 1, 2

MODE_NAMES = {MODE_MPISP: "MPISP", MODE_ISP: "ISP", MODE_UNKNOWN: "unknown"}

ROM_TAGS = {b"2263ROM:SVN00235": "A1", b"2263ROM:SVN00350": "A2", b"2263ROM:SVN02777": "A3"}


def rom_branch(data: bytes) -> str | None:
    if len(data) != 512:
        return None
    return ROM_TAGS.get(data[:16])


def run_mode(data: bytes) -> int:
    if len(data) != 1024:
        return MODE_UNKNOWN
    if data[0x210] == 1 and data[0x211:0x216] == b"MPISP":
        return MODE_MPISP
    if data[0x210] == 2 and data[0x211:0x214] == b"ISP":
        return MODE_ISP
    return MODE_UNKNOWN


def read_allowed(opcode: int, cdw10: int, cdw12: int, cdw13: int, size: int) -> bool:
    if opcode == 6:
        return cdw10 == 1 and cdw12 == 0 and cdw13 == 0 and size == 4096
    if opcode != 0xC2:
        return False
    return (
        (cdw10 == 0x200 and cdw12 == 0x40 and cdw13 <= 1 and size == 2048)
        or (cdw10 == 0x80 and cdw12 == 0x52 and cdw13 == 0x9FF0 and size == 512)
        or (cdw10 == 0x100 and cdw12 == 0x87 and cdw13 == 0 and size == 1024)
        or (cdw10 == 0x80 and cdw12 == 0x88 and cdw13 == 0 and size == 512)
    )


MANUFACTURERS = (
    0x01,
    0x04,
    0x07,
    0x20,
    0x2C,
    0x45,
    0x4A,
    0x51,
    0x89,
    0x92,
    0x98,
    0x9B,
    0xAD,
    0xB5,
    0xC2,
    0xC8,
    0xEC,
    0xEF,
)


def decode_flash_id(data: bytes) -> tuple[list[tuple[int, bytes]], list[int]]:
    """Returns (banks, unrecognised slot numbers)."""
    banks: list[tuple[int, bytes]] = []
    unknown: list[int] = []
    for off in range(0x30, 0x1F0, 8):
        chunk = data[off : off + 8]
        if all(b == 0 for b in chunk) or all(b == 0xFF for b in chunk):
            continue
        slot = (off - 0x30) // 8
        if chunk[0] not in MANUFACTURERS:
            unknown.append(slot)
            continue
        banks.append((slot, bytes(chunk)))
    return banks, unknown


def printable(data: bytes, width: int) -> str:
    raw = data[:width].split(b"\0")[0]
    return "".join(chr(b) if 32 <= b <= 126 else "." for b in raw)
