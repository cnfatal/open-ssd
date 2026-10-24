"""Ordinary A3 ISP package: core1 + patched core0_A3."""

from __future__ import annotations

import hashlib

CORE0_BYTES = 1_048_576
CORE1_BYTES = 131_072
LIGHTSWITCH_BYTES = 4096
BOOT_TAIL = b"SM2263AABOOTTail"
BOOT_TAIL_OFFSET = 0x17F0


class PackageError(RuntimeError):
    pass


def _find_marker(core0: bytes) -> int:
    pos = core0.find(BOOT_TAIL)
    if pos < 0:
        raise PackageError("core0 里找不到 SM2263AABOOTTail")
    return pos


def build(core0: bytes, core1: bytes, lightswitch: bytes, manufacturer: str) -> tuple[bytes, dict]:
    if len(core0) > CORE0_BYTES:
        raise PackageError("core0 太大")
    if len(core1) > CORE1_BYTES:
        raise PackageError("core1 太大")
    if len(lightswitch) != LIGHTSWITCH_BYTES:
        raise PackageError("lightswitch 必须是 4096 字节")

    marker = _find_marker(core0)
    if marker < BOOT_TAIL_OFFSET:
        raise PackageError("boot tail 位置异常")
    boot_start = marker - BOOT_TAIL_OFFSET
    if boot_start + 0x17EB > len(core0):
        raise PackageError("boot 区越界")

    fmt = 1 if (core0[0x10:0x17] == b"BOOTISP" or core0[0x4010:0x4017] == b"BOOTISP") else 3
    name = manufacturer or ""
    if any(x in name for x in ("YMTC", "Samsung", "Hynix")):
        mfg = 0xDA
    elif any(x in name for x in ("Sandisk", "Toshiba")):
        mfg = 0xA2
        fmt |= 0x04
    else:
        raise PackageError("厂商需要额外的外部字节，暂不支持")

    if len(core0) < 0x10000:
        raise PackageError("core0 小于 64 KiB")
    ls_off = len(core0) - 0x10000

    package = bytearray(len(core1) + len(core0))
    package[: len(core1)] = core1
    package[len(core1) :] = core0
    core = memoryview(package)[len(core1) :]

    core[ls_off : ls_off + LIGHTSWITCH_BYTES] = lightswitch
    core[boot_start + 0x17E0] = mfg
    core[boot_start + 0x17E1] = 0x03
    core[boot_start + 0x17E2] = fmt
    core[boot_start + 0x17E3] = 0x01
    core[boot_start + 0x17E4] = 0x02 if fmt & 0x04 else 0x03
    core[boot_start + 0x17E5] = 0x03 if fmt & 0x04 else 0x02
    core[boot_start + 0x17E7 : boot_start + 0x17EB] = b"\0\0\0\0"

    sha_applied = 0
    if len(core1) > CORE1_BYTES and 0x2A0 + 32 <= len(core0):
        offset = int.from_bytes(core[0x294:0x298], "little")
        length = int.from_bytes(core[0x298:0x29C], "little")
        if offset + length > len(core0):
            raise PackageError("SHA 区间越界")
        core[0x2A0:0x2C0] = hashlib.sha256(bytes(core[offset : offset + length])).digest()
        sha_applied = 1

    meta = {
        "boot_start": boot_start,
        "format": fmt,
        "manufacturer": mfg,
        "sha_applied": sha_applied,
        "bytes": len(package),
    }
    return bytes(package), meta
