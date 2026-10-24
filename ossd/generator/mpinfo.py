"""MPInfo 8 KiB: template assembly, RLE typeMap, per-drive fields."""

from __future__ import annotations

import struct

BYTES = 8192
SECTOR = 512


def spare(plane: int) -> bytes:
    out = bytearray(SECTOR)
    base = plane * 32
    out[base] = 0xE7
    out[base + 0x10] = 0xE7
    return bytes(out)


def payload(image: bytes, n512: int, plane: int) -> bytes:
    buf = bytearray(n512 * SECTOR)
    buf[:BYTES] = image
    buf[(n512 - 1) * SECTOR : (n512 - 1) * SECTOR + SECTOR] = spare(plane)
    return bytes(buf)


def inspect(image: bytes) -> dict:
    if len(image) < BYTES:
        raise ValueError("需要至少 8192 字节")

    def text(off: int, width: int) -> str:
        raw = image[off : off + width].split(b"\0")[0]
        return raw.decode("latin-1", "replace")

    return {
        "sn": text(0x1200, 20),
        "model": text(0x1220, 40),
        "nqn": text(0x1800, 255),
        "time": text(0x1910, 16),
        "flags": int.from_bytes(image[0x1214:0x1218], "little"),
        "counter": int.from_bytes(image[0x130E:0x1310], "little"),
    }


def rle(src: bytes, input_n: int, capacity: int = 64) -> bytes:
    if not src or not input_n or not capacity:
        raise ValueError("参数为空")
    out = bytearray()
    value = src[0]
    count = 1
    i = 1
    while i < input_n:
        if src[i] == value and count < 255:
            count += 1
        else:
            if len(out) + 2 > capacity:
                raise ValueError("RLE 溢出")
            out += bytes((value, count))
            value = src[i]
            count = 1
        i += 1
    # 原实现会多比较 input_n 之后的那个字节；调用方缓冲区更长时该字节才存在
    if input_n < len(src) and src[input_n] == value and count < 255:
        count += 1
    if len(out) + 2 > capacity:
        raise ValueError("RLE 溢出")
    out += bytes((value, count, 0xFF, 0x00))
    return bytes(out)


def _fill(dst: bytearray, off: int, width: int, text: str | None, pad: int) -> None:
    dst[off : off + width] = bytes((pad,)) * width
    if text:
        raw = text.encode("latin-1", "replace")[:width]
        dst[off : off + len(raw)] = raw


def build_template(
    cid: bytes,
    seed: bytes,
    drive: bytes,
    *,
    version: str | None = None,
    sn: str | None = None,
    model: str | None = None,
    nqn: str | None = None,
) -> bytes:
    out = bytearray(BYTES)
    out[0:4096] = cid[:4096]
    out[4096:8192] = seed[:4096]
    out[0x1400:0x1800] = drive[:1024]
    # Original producer 446C2E..446C84: IDs are also consumed outside CID.
    for index, offset in enumerate((0x200, 0x202, 0x230, 0x232, 0x26A, 0x26C)):
        out[0x1280 + 2 * index : 0x1282 + 2 * index] = cid[offset : offset + 2]
    flags = int.from_bytes(out[0x1214:0x1218], "little") | 0xFE0
    out[0x1214:0x1218] = flags.to_bytes(4, "little")

    if version:
        _fill(out, 0x0008, 8, version, ord(" "))
        for i in range(8):
            if out[0x0008 + i] == 0:
                out[0x0008 + i] = ord(" ")
        out[0x1214] |= 0x20
    if sn:
        _fill(out, 0x1200, 20, sn, 0)
        out[0x1214] |= 0x01
    if model:
        _fill(out, 0x1220, 40, model, ord(" "))
        out[0x1214] |= 0x02
    if nqn:
        raw = nqn.encode("latin-1", "replace")[:255]
        out[0x1800 : 0x1800 + len(raw)] = raw
        out[0x1214] |= 0x20
        flags = int.from_bytes(out[0x1214:0x1218], "little") | 0x2000
        out[0x1214:0x1218] = flags.to_bytes(4, "little")
    return bytes(out)


def finalize(
    base: bytes,
    *,
    typemap: bytes | None = None,
    cid_final: bytes | None = None,
    counter: int = 0,
    time: str | None = None,
    stat_a: int = 0,
    stat_b: int = 0,
) -> bytes:
    out = bytearray(base)
    if cid_final:
        out[0:4096] = cid_final
    if typemap:
        encoded = rle(typemap, len(typemap))
        if len(encoded) > 0x40:
            raise ValueError("RLE 超过 64 字节")
        out[0x1350:0x1390] = b"\0" * 0x40
        out[0x1350 : 0x1350 + len(encoded)] = encoded
    out[0x130E:0x1310] = struct.pack("<H", counter & 0xFFFF)
    out[0x1910:0x1920] = b"\0" * 16
    if time:
        raw = time.encode("latin-1", "replace")[:16]
        out[0x1910 : 0x1910 + len(raw)] = raw
    out[0x1900:0x1902] = struct.pack("<H", stat_a & 0xFFFF)
    out[0x1902:0x1904] = struct.pack("<H", stat_b & 0xFFFF)
    out[0x1904:0x1906] = struct.pack("<H", (stat_a - stat_b) & 0xFFFF)
    return bytes(out)
