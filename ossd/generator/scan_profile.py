"""Derive the Org/erase scan descriptors from DriveSetting D."""

from __future__ import annotations

from dataclasses import dataclass, field

BATCH_TABLE = (0, 64, 128, 256, 512, 1024)


def _rd16(buf: bytes, off: int) -> int:
    return buf[off] | buf[off + 1] << 8


def _rd32(buf: bytes, off: int) -> int:
    return int.from_bytes(buf[off : off + 4], "little")


@dataclass
class ScanConfig:
    pretest_option: int = 0
    show_scan_bad_count: int = 0
    scan_bad_count: int = 1


@dataclass
class ScanDerived:
    total: int = 0
    batch: int = 0
    mode: int = 0
    byte5: int = 0
    byte6: int = 0
    byte7: int = 0
    pages: list = field(default_factory=lambda: [0xFFFF] * 5)
    offsets: list = field(default_factory=lambda: [0xFFFF] * 7)
    batches: int = 0
    nresult: int = 0


def _page_list(mask: int, page_number: int) -> list[int]:
    pages = []
    for bit in range(5):
        if not (mask & (1 << bit)):
            continue
        if bit == 0:
            pages.append(0)
        elif bit == 1:
            pages.append(1)
        elif bit == 2:
            pages.append((page_number - 2) & 0xFFFF)
        elif bit == 3:
            pages.append((page_number - 1) & 0xFFFF)
        # bit 4 is checked but never appended
    return pages


def _offset_list(mask: int, page_size: int) -> list[int]:
    offsets = []
    base = (page_size << 10) & 0xFFFF
    for bit in (4, 5, 6, 0, 1):
        if not (mask & (1 << bit)):
            continue
        offsets.append({4: 0, 5: 6, 6: 12, 0: base, 1: (base + 6) & 0xFFFF}[bit])
    return offsets


def derive(drive: bytes, config: ScanConfig) -> tuple[ScanDerived, int]:
    planes = _rd32(drive, 0x238)
    if not planes:
        return ScanDerived(), -2
    total = _rd32(drive, 0x22C) // planes
    if total > 0xFFFF:
        return ScanDerived(), -1

    batch = 64
    if config.show_scan_bad_count:
        if config.scan_bad_count >= len(BATCH_TABLE):
            return ScanDerived(), -3
        batch = BATCH_TABLE[config.scan_bad_count]
    if config.pretest_option == 1:
        batch = 0

    page_mask = _rd32(drive, 0x28C)
    offset_mask = _rd32(drive, 0x290)
    pattern = _rd32(drive, 0x294)
    extend = _rd32(drive, 0x298)
    page_number = _rd16(drive, 0x228)
    page_size = _rd16(drive, 0x21C)

    out = ScanDerived(total=total, batch=batch, mode=0 if extend & 0x10 else 1)
    if out.mode:
        pages = _page_list(page_mask, page_number)
        out.pages = pages + [0xFFFF] * (5 - len(pages))
        offsets = _offset_list(offset_mask, page_size)
        out.offsets = offsets + [0xFFFF] * (7 - len(offsets))
    else:
        out.pages[0] = 0
    out.byte5 = 1 if pattern & 0x80 else 0
    out.byte6 = 0xFF if (pattern & 0x0F) == 0x0F else 0
    out.byte7 = 1 if extend & 0x04 else 0
    if out.batch:
        batches = (out.total + out.batch - 1) // out.batch
        if batches > 0xFF:
            return out, -4
        out.batches = batches
        out.nresult = out.batch // 8
    return out, 0


def batch_range(total: int, batch: int, index: int) -> tuple[int, int]:
    start = index * batch
    end = (index + 1) * batch - 1
    if end > total:
        end = total - 1 if total else 0
    return start, end


@dataclass
class EraseConfig:
    pretest_option: int = 0
    do_not_erase_bad: int = 0


@dataclass
class EraseDerived:
    total: int = 0
    batch: int = 0
    mode: int = 0
    batches: int = 0
    nresult: int = 0


def erase_derive(drive: bytes, config: EraseConfig) -> tuple[EraseDerived, int]:
    planes = _rd32(drive, 0x238)
    if not planes:
        return EraseDerived(), -2
    total = _rd32(drive, 0x22C) // planes
    if total > 0xFFFF:
        return EraseDerived(), -1
    batch = 64 if (config.pretest_option == 3 or not config.do_not_erase_bad) else 0
    out = EraseDerived(total=total, batch=batch, mode=0 if config.pretest_option == 1 else 1)
    if batch:
        batches = (total + batch - 1) // batch
        if batches > 0xFF:
            return out, -4
        out.batches = batches
        out.nresult = batch // 8
    return out, 0
