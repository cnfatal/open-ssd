"""Derive the configuration from the vendor package plus live device readings.

No profiles are stored: the selection is recomputed from
System.ini -> Config/<ini> -> FlashPartNum -> Flash.SET row, plus the ROM tag and
the measured NAND geometry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config.flash_set import SetRow
from .config.package import Package

ROM_REVISIONS = {
    "SVN00235": ("AB", "BootISP2263A1.bin"),
    "SVN00350": ("AC", "BootISP2263A2.bin"),
    "SVN02777": ("AD", "BootISP2263A3.bin"),
}


class SelectionError(RuntimeError):
    def __init__(self, message: str, candidates: list[SetRow] | None = None):
        super().__init__(message)
        self.candidates = candidates or []


@dataclass
class Selection:
    package: Path
    ini_name: str
    flash_part_num: str
    row: SetRow
    revision: str | None
    bootisp: str | None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "package": str(self.package),
            "ini": self.ini_name,
            "flash_part_num": self.flash_part_num,
            "flash_id": self.row.flash_id_text,
            "ce": self.row.ce_count,
            "die_per_ce": self.row.die_per_ce,
            "channels": self.row.channel_count,
            "revision": self.revision,
            "bootisp": self.bootisp,
            "notes": self.notes,
        }


def _normalise_id(text: str | None) -> bytes | None:
    if not text:
        return None
    cleaned = text.replace("0x", "").replace(",", " ").replace(":", " ")
    parts = [p for p in cleaned.split() if p]
    if len(parts) == 1 and len(parts[0]) >= 12:
        value = parts[0]
        return bytes(int(value[i : i + 2], 16) for i in range(0, 12, 2))
    if len(parts) != 6:
        raise SelectionError(f"flash-id 需要 6 个字节，收到 {text!r}")
    return bytes(int(p, 16) for p in parts)


def select(
    package: Package,
    rom_tag: str | None = None,
    flash_id: str | bytes | None = None,
    ce: int | None = None,
    die_per_ce: int | None = None,
    part: str | None = None,
) -> Selection:
    part = part or package.flash_part_num()
    if not part:
        raise SelectionError("Config 里没有 [TESTPROCEDURE] FlashPartNum")

    row = package.flash_set.resolve(part)
    if row is None:
        raise SelectionError(f"FlashPartNum 在 Flash.SET 里不存在: {part}")

    notes: list[str] = []
    wanted = _normalise_id(flash_id) if isinstance(flash_id, str) else flash_id
    if wanted is not None and row.flash_id != wanted:
        raise SelectionError(
            f"ini 选中的行 ID 是 {row.flash_id_text}，设备读到 {' '.join(f'{b:02x}' for b in wanted)}",
            package.flash_set.by_flash_id(wanted),
        )

    if ce is not None and row.ce_count != ce:
        raise SelectionError(
            f"ini 选中的行 CE={row.ce_count}，设备实测 CE={ce}",
            [c for c in package.flash_set.by_flash_id(row.flash_id)],
        )
    if die_per_ce is not None and row.die_per_ce != die_per_ce:
        raise SelectionError(
            f"ini 选中的行 die/CE={row.die_per_ce}，设备实测 {die_per_ce}",
            [c for c in package.flash_set.by_flash_id(row.flash_id)],
        )

    revision = bootisp = None
    if rom_tag is not None:
        label = rom_tag.split(":")[-1] if ":" in rom_tag else rom_tag
        entry = ROM_REVISIONS.get(label)
        if entry is None:
            raise SelectionError(f"未知 ROM 标签: {rom_tag}")
        revision, bootisp = entry
        if not package.firmware(bootisp).is_file():
            raise SelectionError(f"包内缺少 {bootisp}")
    else:
        notes.append("未提供 ROM 标签，跳过 BootISP 选择")

    if package.testprocedure().get("PretestOption") == "1":
        notes.append("PretestOption=1：原厂流程会跳过 Org 扫描")
    if package.testprocedure().get("DoQC") == "0":
        notes.append("DoQC=0：不跑 QC")

    return Selection(
        package=package.root,
        ini_name=package.ini_name,
        flash_part_num=part,
        row=row,
        revision=revision,
        bootisp=bootisp,
        notes=notes,
    )


def core0_name(revision: str) -> str:
    suffix = {"AB": "", "AC": "_A2", "AD": "_A3"}[revision]
    return f"YMTC/TAS/ISP2263XT_core0{suffix}.bin"
