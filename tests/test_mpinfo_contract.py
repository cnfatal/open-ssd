"""Compare MPInfo production fields with an actual vendor export."""

import unittest
from pathlib import Path

from ossd.generator import mpinfo

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "tmp/evidence-archive-2026-10-23/sm2263xt-ad/vendor-open-success-2026-10-23"
PKG = ROOT / "assets/SM2263XT_YMTC_TAS_PKGV0217A_FWV0126A"


@unittest.skipUnless(VENDOR.is_dir() and PKG.is_dir(), "vendor evidence absent")
class MpInfoContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vendor = (VENDOR / "oracle/Port0_downloadMPInfo.bin").read_bytes()
        cls.drive = (VENDOR / "linux-tool/DriveSettingTable.bin").read_bytes()
        cls.built = mpinfo.build_template(
            cls.vendor[:4096],
            (PKG / "Firmware/MPINFO.bin").read_bytes(),
            cls.drive,
            version="V0126A0",
            sn="AA000000000000000002",
            model="SMI 2263XT",
        )

    def test_id_copies_match_vendor_producer(self):
        self.assertEqual(self.built[0x1280:0x128C], self.vendor[0x1280:0x128C])

    def test_id_enable_and_model_flags_match_vendor(self):
        flags = int.from_bytes(self.built[0x1214:0x1218], "little")
        self.assertEqual(flags & 0xFE3, 0xFE3)
        self.assertEqual(self.built[0x1220:0x1248], self.vendor[0x1220:0x1248])

    def test_snapshot_is_drive_setting_with_fixed_image_size(self):
        self.assertEqual(len(self.built), 8192)
        self.assertEqual(self.built[0x1400:0x1800], self.vendor[0x1400:0x1800])

    def test_finalize_preserves_vendor_identity_and_encodes_recorded_typemap(self):
        typemap = (VENDOR / "oracle/Port0_upInfoDataType.bin").read_bytes()
        final = mpinfo.finalize(
            self.vendor, typemap=typemap, cid_final=self.vendor[:4096], counter=1
        )
        self.assertEqual(final[:4096], self.vendor[:4096])
        self.assertEqual(final[0x1214:0x1218], self.vendor[0x1214:0x1218])
        self.assertEqual(final[0x1280:0x128C], self.vendor[0x1280:0x128C])
        self.assertEqual(final[0x1350:0x1390], self.vendor[0x1350:0x1390])
