"""System-block probe framing, connectivity derivation/decoding."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import physical

CONNECTIVITY_CELLS = 16
CONNECTIVITY_RECORDS = 16
CDW13_TABLE = (6, 7, 8, 9, 10, 11, 12, 13)


def _rd32(buf: bytes, off: int) -> int:
    return int.from_bytes(buf[off : off + 4], "little")


def _floor_log2(value: int) -> int:
    result = 0
    while value >> 1:
        value >>= 1
        result += 1
    return result


@dataclass
class ProbeFrames:
    erase: bytes = b""
    write: list = field(default_factory=list)
    checksum: bytes = b""


def frames(
    block: int, plane: int, ch: int, ce: int, die: int, n512: int, sum_sectors: int
) -> ProbeFrames | None:
    if not n512 or not sum_sectors:
        return None
    address = physical.PhysAddr(
        block=block, plane=plane | 0x80, channel=ch, ce=ce, die=die, mode=0x84
    )
    erase = physical.erase_sqe(address)
    writes = []
    for page in range(16):
        address.page = page
        address.mode = 0xC5
        writes.append(physical.write_sqe(n512, address))
    checksum = physical.checksum_query_sqe(n512, 16, block, plane, ch, ce, die, 0)
    return ProbeFrames(erase=erase, write=writes, checksum=checksum)


def connectivity_cdw13(drive: bytes) -> int:
    index = _rd32(drive, 0x248) >> 5
    if index >= len(CDW13_TABLE):
        raise ValueError("drive: CDW13 derivation index out of range")
    derived = (_floor_log2(_rd32(drive, 0x234)) + CDW13_TABLE[index]) & 7
    return drive[0x23C] | derived << 8


@dataclass
class Connectivity:
    cell: list = field(default_factory=lambda: [0] * CONNECTIVITY_CELLS)
    id: list = field(default_factory=lambda: [b""] * CONNECTIVITY_RECORDS)
    match: list = field(default_factory=lambda: [0] * CONNECTIVITY_RECORDS)


def connectivity_parse(matrix: bytes, id_data: bytes, expected_id: bytes) -> Connectivity:
    out = Connectivity()
    out.cell = list(matrix[:CONNECTIVITY_CELLS])
    for record in range(CONNECTIVITY_RECORDS):
        source = id_data[0x30 + record * 8 : 0x30 + record * 8 + 6]
        out.id[record] = bytes(source)
        out.match[record] = 1 if source == expected_id else 0
    return out
