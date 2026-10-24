"""SQE framing for the physical read/write/erase/checksum commands.

Every builder returns 64 bytes. ``n512`` counts 512-byte sectors. These are
pure encoders: nothing here touches a device.
"""

from __future__ import annotations

from dataclasses import dataclass

SQE_BYTES = 64


@dataclass
class PhysAddr:
    block: int = 0
    page: int = 0
    channel: int = 0
    ce: int = 0
    die: int = 0
    plane: int = 0
    read_byte34: int = 0
    mode: int = 0


def _le32(value: int) -> bytes:
    return (value & 0xFFFFFFFF).to_bytes(4, "little")


def command(opcode: int, n512: int, cdw12: int, cdw13: int, cdw14: int) -> bytes:
    sqe = bytearray(SQE_BYTES)
    sqe[0] = opcode & 0xFF
    sqe[40:44] = _le32((n512 << 9) >> 2)
    sqe[48:52] = _le32(cdw12)
    sqe[52:56] = _le32(cdw13)
    sqe[56:60] = _le32(cdw14)
    return bytes(sqe)


def _address14(a: PhysAddr, rdt: bool = False, read: bool = False) -> int:
    plane = a.plane if rdt else a.plane & 0x7F
    return (
        (a.die & 0xFF) << 24
        | ((a.read_byte34 & 0xFF) << 16 if read else 0)
        | (plane << 8)
        | (a.channel & 15)
        | ((a.ce & 15) << 4)
    )


def _normal12(a: PhysAddr, sub: int) -> int:
    return ((a.mode & 0xFF) << 8) | sub | ((a.plane >> 7) << 16)


def _page_block(a: PhysAddr) -> int:
    return ((a.page & 0xFFFF) << 16) | (a.block & 0xFFFF)


def read_sqe(n512: int, a: PhysAddr) -> bytes:
    return command(0xC2, n512, _normal12(a, 0x4E), _page_block(a), _address14(a, read=True))


def write_sqe(n512: int, a: PhysAddr) -> bytes:
    return command(0xC1, n512, _normal12(a, 0x83), _page_block(a), _address14(a))


def rdt_sqe(n512: int, a: PhysAddr) -> bytes:
    return command(
        0xC2,
        n512,
        ((a.mode & 0xFF) << 8) | 0x8A,
        _page_block(a),
        _address14(a, rdt=True, read=True),
    )


def erase_sqe(a: PhysAddr) -> bytes:
    return command(0xC0, 0, _normal12(a, 0x03), a.block & 0xFFFF, _address14(a))


def debug_info_sqe(n512: int) -> bytes:
    return command(0xC2, n512, 0x88, 0, 0)


def card_mode_sqe(n512: int) -> bytes:
    return command(0xC1, n512, 0x90, 0, 0)


def reset_sqe() -> bytes:
    return command(0xC0, 0, 0x01, 0, 0)


def checksum_query_sqe(
    n512: int, count: int, block: int, plane: int, channel: int, ce: int, die: int, extra: int
) -> bytes:
    cdw13 = ((count & 0xFFFF) << 16) | (block & 0xFFFF)
    cdw14 = (die & 0xFF) << 24 | (plane & 0xFF) << 8 | (channel & 15) | ((ce & 15) << 4)
    sqe = bytearray(command(0xC2, n512, 0x8D82, cdw13, cdw14))
    sqe[60:64] = _le32(extra)
    return bytes(sqe)


def read_ram_sqe(n512: int, address: int) -> bytes:
    return command(0xC2, n512, 0x52, address, 0)


def connectivity_sqe(n512: int, cdw13: int) -> bytes:
    return command(0xC2, n512, 0x80, cdw13, 0)


def scan_org_submit_sqe(n512: int) -> bytes:
    return command(0xC1, n512, 0x91, 0, 0)


def scan_org_result_sqe(n512: int) -> bytes:
    return command(0xC2, n512, 0x85, 0, 0)


def scan_erase_submit_sqe(n512: int) -> bytes:
    return command(0xC1, n512, 0x92, 0, 0)


def scan_erase_result_sqe(
    n512: int, first: int, last: int, mode: int, blocks_per_batch: int
) -> bytes:
    return command(
        0xC2,
        n512,
        ((mode & 0xFF) << 8) | 0x83,
        ((last & 0xFFFF) << 16) | (first & 0xFFFF),
        blocks_per_batch,
    )


def checksum_reply_value(reply: bytes) -> int:
    return int.from_bytes(reply[:4], "little")


def scan_result_n512(blocks_per_batch: int) -> int:
    return blocks_per_batch // 8


def scan_debug(reply: bytes) -> dict:
    error = reply[0x12]
    fault = {0xE0: "timeout", 0xFE: "address-over", 0xFF: "address-error"}.get(error, "unknown")
    return {"done": reply[0x11], "error": error, "fault": fault}


def scan_map_bad(bitmap: bytes, block: int, channel: int, ce: int, plane: int, die: int) -> int:
    offset = block * 64 + channel * 16 + ce * 4 + plane
    return (bitmap[offset] >> die) & 1


@dataclass
class FBlockAddress:
    block: int
    plane: int
    intlv: int
    channel: int
    ce: int
    die: int


def split_fblock(
    linear: int, planes: int, channels: int, slots: int, dies_per_ce: int
) -> FBlockAddress:
    group = planes * slots
    remainder = linear % group
    lane = remainder % slots
    intlv = lane // channels
    return FBlockAddress(
        block=linear // group,
        plane=remainder // slots,
        intlv=intlv,
        channel=lane % channels,
        ce=intlv // dies_per_ce,
        die=intlv % dies_per_ce,
    )
