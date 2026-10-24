"""Host-side system-block candidates and the capacity stage."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import pretest_layout as pl


@dataclass
class SystemCandidate:
    index: int
    address: pl.SystemAddress


@dataclass
class SystemScan:
    total: int
    limit: int
    usable: int
    listed: list = field(default_factory=list)
    selected: list = field(default_factory=list)


def system_candidates(param: bytes, bbt: bytes, limit: int = 16) -> SystemScan:
    total = param[0x32] | param[0x33] << 8
    if not total or total > pl.BAD_ROWS:
        raise ValueError(f"param: invalid row count {total}")
    scan = SystemScan(total=total, limit=limit, usable=0)
    for index in range(255):
        address = pl.system_address(param, index)
        if address is None:
            raise ValueError(f"system: index {index} decode failed")
        if (
            address.bad_byte_offset < len(bbt)
            and (bbt[address.bad_byte_offset] >> address.bad_bit) & 1
        ):
            continue
        if len(scan.listed) < limit:
            scan.listed.append(SystemCandidate(index, address))
        if len(scan.selected) < 8:
            scan.selected.append(SystemCandidate(index, address))
        scan.usable += 1
    return scan


def fill_system(param: bytes, scan: SystemScan) -> bytes:
    if scan.usable < 8:
        raise ValueError("fewer than eight candidates; refusing to fill")
    out = bytearray(param)
    out[0x20:0x28] = bytes(c.index for c in scan.selected)
    system_block = scan.selected[7].address.block + 1
    out[0x30] = system_block & 0xFF
    out[0x31] = (system_block >> 8) & 0xFF
    return bytes(out)
