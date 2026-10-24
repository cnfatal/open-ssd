"""配置解析与选择的单元测试（不访问设备）。

包内文件缺失时相关用例自动跳过，便于在没解压原厂包的机器上跑。
"""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from typing import cast

from ossd.config.flash_set import SetRow, parse_flash_set
from ossd.config.ini import parse_ini
from ossd.config.package import Package, PackageError
from ossd.generator.drive_setting import build_drive_setting
from ossd.generator.families import Traits, builtin_traits
from ossd.generator.param_table import build_param_table
from ossd.select import SelectionError, select

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "assets" / "SM2263XT_YMTC_TAS_PKGV0217A_FWV0126A"

SET_TEXT = """[SM2263XT-DataBase-V0209]
A0=YMTC,2Tbit,YMN09TC1B1HC6C(TAS)(SM2263XT)
YMTC,2Tbit,YMN09TC1B1HC6C(TAS)(SM2263XT)=9B,C4,28,49,20,00,4,16,2048,036864,2304,01980,00000,00800,04,01,04,2,D1
A2=YMTC,8Tbit,YMN09TC1B1OC6C(TAS)(2Die)(SM2263XT)
YMTC,8Tbit,YMN09TC1B1OC6C(TAS)(2Die)(SM2263XT)=9B,C5,29,49,20,00,4,16,2048,036864,2304,01980,00000,00800,04,02,08,2,D1
ID0(H),ID1(H),ID2(H),ID3(H),ID4(H),ID5(H)=H,H,H,H,H,H
"""


class IniTest(unittest.TestCase):
    def test_sections_and_case(self):
        ini = parse_ini("[A]\nKey=  1 \n; c\n[B]\nX=2\n")
        self.assertEqual(ini.get("A", "Key"), "1")
        self.assertEqual(ini.get("B", "X"), "2")
        self.assertIsNone(ini.get("A", "Missing"))


class FlashSetTest(unittest.TestCase):
    def test_rows_and_alias(self):
        fs = parse_flash_set(SET_TEXT)
        self.assertEqual(fs.header, "SM2263XT-DataBase-V0209")
        self.assertEqual(len(fs.rows), 2)  # 模板行被跳过
        row = fs.resolve("A2")
        self.assertIsNotNone(row)
        row = cast(SetRow, row)
        self.assertEqual(row.flash_id_text, "9b c5 29 49 20 00")
        self.assertEqual(row.ce_count, 8)
        self.assertEqual(row.die_per_ce, 2)
        self.assertEqual(row.channel_count, 2)

    def test_unknown_alias(self):
        self.assertIsNone(parse_flash_set(SET_TEXT).resolve("A9"))


@unittest.skipUnless(PKG.is_dir(), "assets 下没有原厂包")
class PackageTest(unittest.TestCase):
    def test_load_real_package(self):
        pkg = Package.load(PKG)
        self.assertEqual(pkg.ini_name, "YMTC_TAS_ISP_2DIE")
        self.assertEqual(pkg.version(), "V0217V1")
        self.assertTrue(pkg.firmware("MPISP2263.bin").is_file())

    def test_vendor_default_does_not_match_this_drive(self):
        pkg = Package.load(PKG)
        with self.assertRaises(SelectionError) as ctx:
            select(pkg, rom_tag="SVN02777", flash_id="9b c5 29 49 20 00", ce=8, die_per_ce=2)
        self.assertTrue(ctx.exception.candidates)
        self.assertEqual({c.ce_count for c in ctx.exception.candidates}, {4, 8})

    def test_explicit_override(self):
        pkg = Package.load(PKG)
        pkg.profile_ini.sections["TESTPROCEDURE"]["FlashPartNum"] = pkg.flash_set.aliases["A2"]
        choice = select(pkg, rom_tag="SVN02777", flash_id="9b c5 29 49 20 00", ce=8, die_per_ce=2)
        self.assertEqual(choice.row.ce_count, 8)
        self.assertEqual(choice.revision, "AD")
        self.assertEqual(choice.bootisp, "BootISP2263A3.bin")

    def test_param_build_matches_c(self):
        pkg = Package.load(PKG)
        row = cast(SetRow, pkg.flash_set.resolve("A2"))
        traits = cast(Traits, builtin_traits(row.columns[0]))
        template = pkg.drive_setting("DriveSettingTable_modify.bin").read_bytes()
        matrix = bytes.fromhex("03000300030003000300030003000300")
        drive = build_drive_setting(template, row, traits.family, True, 0x0F, 0x05)
        param = build_param_table(drive, row, matrix, 2, 0x0F, 0x05, traits)
        # 与 C 版（原厂 P 的 before-SetSystemBlock 快照）逐字节一致
        self.assertEqual(
            hashlib.sha256(param).hexdigest(),
            "6260d8918e352880da034acc4ba9dea4380ba55c9a14c739afae7686820a377f",
        )
        self.assertEqual(
            hashlib.sha256(bytes(drive)).hexdigest(),
            "52c9820e7fadb75e21f9ef23f9e22257e950cc4c9ac4ba2e69895b8cd4add7e9",
        )

    def test_missing_dir(self):
        with self.assertRaises(PackageError):
            Package.load(ROOT / "assets" / "no-such-package")


if __name__ == "__main__":
    unittest.main()
