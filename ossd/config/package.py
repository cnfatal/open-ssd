"""Locate and read an extracted vendor MPTool package.

The package is the single source of configuration: we never re-declare its
contents.  Missing directories are reported as errors instead of falling back
to defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .flash_set import FlashSet, load_flash_set
from .ini import Ini, load_ini

REQUIRED_DIRS = ("Config", "FlashDB", "Firmware")
REQUIRED_FILES = (
    "System.ini",
    "FlashDB/Flash.SET",
    "Firmware/MPISP2263.bin",
    "Tables/SeedTable2304.bin",
    "DriveSetting/DriveSettingTable_modify.bin",
)


class PackageError(RuntimeError):
    pass


@dataclass
class Package:
    root: Path
    system_ini: Ini
    ini_name: str
    profile_ini: Ini
    flash_set: FlashSet

    @classmethod
    def load(cls, root: str | Path, ini_name: str | None = None) -> Package:
        root = Path(root)
        if not root.is_dir():
            raise PackageError(f"package directory not found: {root}")
        for name in REQUIRED_DIRS:
            if not (root / name).is_dir():
                raise PackageError(f"missing directory: {root / name}")
        for name in REQUIRED_FILES:
            if not (root / name).is_file():
                raise PackageError(f"missing file: {root / name}")

        system_ini = load_ini(str(root / "System.ini"))
        chosen = ini_name or system_ini.get("INITIAL", "IniName")
        if not chosen:
            raise PackageError("System.ini 没有 [INITIAL] IniName")
        ini_path = root / "Config" / f"{chosen}.ini"
        if not ini_path.is_file():
            raise PackageError(f"profile ini 不存在: {ini_path}")
        profile_ini = load_ini(str(ini_path))
        flash_set = load_flash_set(str(root / "FlashDB" / "Flash.SET"))
        return cls(
            root=root,
            system_ini=system_ini,
            ini_name=chosen,
            profile_ini=profile_ini,
            flash_set=flash_set,
        )

    # ---- 包内路径 ----
    def firmware(self, name: str) -> Path:
        return self.root / "Firmware" / name

    def table(self, name: str) -> Path:
        return self.root / "Tables" / name

    def drive_setting(self, name: str) -> Path:
        return self.root / "DriveSetting" / name

    def config(self, name: str) -> Path:
        return self.root / "Config" / name

    def lightswitch(self, name: str) -> Path:
        return self.root / "LightSwitch" / name

    # ---- profile ini ----
    def testprocedure(self) -> dict[str, str]:
        return self.profile_ini.section("TESTPROCEDURE")

    def cid_section(self) -> dict[str, str]:
        return self.profile_ini.section("CID")

    def rdt_section(self) -> dict[str, str]:
        return self.profile_ini.section("RDT")

    def flash_part_num(self) -> str | None:
        return self.testprocedure().get("FlashPartNum")

    def version(self) -> str:
        return self.system_ini.get("MPINFO", "PACKAGEVER", "") or ""
