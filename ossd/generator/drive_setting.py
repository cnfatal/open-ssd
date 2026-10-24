"""DriveSetting D: template + the 69 Flash.SET columns + a few fields."""

from __future__ import annotations

from ..config.flash_set import SetRow


def _wr32(buf: bytearray, offset: int, value: int) -> None:
    buf[offset : offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")


def build_drive_setting(
    template: bytes,
    row: SetRow,
    family: int,
    apply_masks: bool = False,
    ch_mask: int = 0,
    ce_mask: int = 0,
) -> bytearray:
    if len(template) != 2048:
        raise ValueError("DriveSetting template must be 2048 bytes")
    if row.count < 69:
        raise ValueError("SET row must have 69 columns")
    drive = bytearray(template)
    for index, value in enumerate(row.columns[:69]):
        _wr32(drive, 0x200 + 4 * index, value)
    _wr32(drive, 0x74, family)
    _wr32(drive, 0x20, 0)
    _wr32(drive, 0x24, 0)
    _wr32(drive, 0x28, 0)
    if apply_masks:
        _wr32(drive, 0x24, ch_mask & 0x0F)
        _wr32(drive, 0x28, ce_mask & 0x0F)
    return drive
