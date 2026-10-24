"""MPISP image preparation (body SHA-256) and 16 KiB upload packets."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

PACKET_BYTES = 16384

OK = 0
ARGUMENT = -1
SIZE = -2
METADATA = -4
CAPACITY = -5
INDEX = -6

_MESSAGES = {
    OK: "ok",
    ARGUMENT: "invalid argument",
    SIZE: "invalid image length or packet alignment",
    METADATA: "body range outside image",
    CAPACITY: "output capacity too small",
    INDEX: "packet index outside image",
}


def error_text(result: int) -> str:
    return _MESSAGES.get(result, "unknown error")


@dataclass
class MpispInfo:
    metadata_word0: int = 0
    body_offset: int = 0
    body_bytes: int = 0
    metadata_word3: int = 0
    body_sha256: bytes = b""


def prepare(data: bytes) -> tuple[bytes, MpispInfo, int]:
    if len(data) < 0x2C0:
        return b"", MpispInfo(), SIZE
    info = MpispInfo(
        metadata_word0=int.from_bytes(data[0x290:0x294], "little"),
        body_offset=int.from_bytes(data[0x294:0x298], "little"),
        body_bytes=int.from_bytes(data[0x298:0x29C], "little"),
        metadata_word3=int.from_bytes(data[0x29C:0x2A0], "little"),
    )
    if info.body_offset > len(data) or info.body_bytes > len(data) - info.body_offset:
        return b"", info, METADATA
    info.body_sha256 = hashlib.sha256(
        data[info.body_offset : info.body_offset + info.body_bytes]
    ).digest()
    out = bytearray(data)
    out[0x2A0:0x2C0] = info.body_sha256
    return bytes(out), info, OK


def packet_count(length: int) -> int:
    if not length or length % 512 or length > (1 << 40):
        return 0
    return 1 + (length - 1) // PACKET_BYTES


@dataclass
class Packet:
    index: int
    source_offset_bytes: int
    valid_bytes: int
    transfer_bytes: int
    offset_sectors: int
    last: bool
    sqe: bytes
    payload: bytes


def packet(prepared: bytes, length: int, index: int) -> tuple[Packet, int]:
    count = packet_count(length)
    if not count:
        return Packet(0, 0, 0, 0, 0, False, b"", b""), SIZE
    if index >= count:
        return Packet(0, 0, 0, 0, 0, False, b"", b""), INDEX
    offset = index * PACKET_BYTES
    amount = min(length - offset, PACKET_BYTES)
    chunked = length >= PACKET_BYTES
    sqe = bytearray(64)
    sqe[0:4] = (0xC1).to_bytes(4, "little")
    sqe[40:44] = (amount // 4).to_bytes(4, "little")
    sqe[48:52] = (0x80000088 if chunked else 0x88).to_bytes(4, "little")
    sector = offset // 512
    if chunked and index + 1 == count:
        sector |= 0x80000000
    sqe[52:56] = sector.to_bytes(4, "little")
    pkt = Packet(
        index=index,
        source_offset_bytes=offset,
        valid_bytes=amount,
        transfer_bytes=amount,
        offset_sectors=offset // 512,
        last=index + 1 == count,
        sqe=bytes(sqe),
        payload=prepared[offset : offset + amount],
    )
    return pkt, OK
