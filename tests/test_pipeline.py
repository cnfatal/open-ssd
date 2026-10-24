"""离线产物的逐字节回归测试。

fixture 在 tmp/ 下（不入库）；缺失时自动跳过。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ossd import stages
from ossd.generator import (
    bbt,
    card_mode,
    cid,
    diffaddr,
    infoblock,
    isp_package,
    layout,
    mpisp,
    physical,
)
from ossd.generator import pretest_layout as pl
from ossd.transport import codec

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "assets" / "SM2263XT_YMTC_TAS_PKGV0217A_FWV0126A"
W = ROOT / "tmp" / "open-ours"
ORACLE = (
    ROOT / "tmp" / "evidence-archive-2026-10-23" / "sm2263xt-ad" / "vendor-open-success-2026-10-23"
)

HAVE_PKG = PKG.is_dir()
HAVE_W = W.is_dir()


def _need(*paths):
    return all(Path(p).exists() for p in paths)


def _sectors(data: bytes) -> int:
    return (len(data) + 511) // 512


class CidTest(unittest.TestCase):
    @unittest.skipUnless(HAVE_PKG and HAVE_W, "缺少原厂包或 fixture")
    def test_identity_matches_vendor_lightswitch(self):
        base = (PKG / "LightSwitch/YMTC/TAS/SM2263XT_YMTC_TAS_LightSwitch.bin").read_bytes()
        out = cid.identity(base, "V0126A0", "SN000000000000000000", "SMI 2263XT")
        self.assertEqual(out, (W / "cid-work.bin").read_bytes())
        self.assertEqual(sum(1 for a, b in zip(out, base) if a != b), 33)

    def test_apply_map_sets_bitfield(self):
        base = bytes(4096)
        text = "0,ignored,0,dec,0,0,0\n1,x,3,dec,10,4,2\n"
        out, report = cid.apply_map(base, text)
        self.assertEqual(report.applied, 1)
        self.assertEqual(out[0x10], 0x30)


class CidVectorTest(unittest.TestCase):
    """CID 子区的取值与 C 版 self-test 的向量一致。"""

    def test_pcie_nvme(self):
        c = cid.CidConfig(
            pci_vendor_id="126F",
            pci_device_id="2263",
            subsys_vendor_id="126F",
            subsys_id="2263",
            pcie_speed_index=2,
            pcie_lane_index=2,
            aspm_support=1,
            clock_pm=1,
            aspm_l1_2=1,
            aspm_l1_1=1,
            npss=2,
            apsta=1,
            gate_apsta=1,
            warning_temp=27,
            gate_warning=1,
            critical_temp=47,
            gate_critical=1,
            nvme_vid="126F",
            nvme_ssvid="126F",
            ieee="000000",
            eui64="0000000000000001",
            eui64_by_nvme=0,
            precr=1,
            disable_hmb=1,
            multi_ns=1,
            irst=1,
            ps4_max_power=0x1234,
            gate_ps4=1,
            fna_format=1,
            gate_fna_format=1,
            fna_erase=1,
            gate_fna_erase=1,
        )
        out = bytearray(4096)
        cid.apply_pcie_nvme(out, c)
        self.assertEqual(bytes(out[0x200:0x204]), bytes((0x6F, 0x12, 0x63, 0x22)))
        self.assertEqual(out[0x214], 0x43)
        self.assertEqual(out[0x215] & 0x0C, 0x04)
        self.assertTrue(out[0x216] & 0x04)
        self.assertEqual(out[0x220] & 0x0C, 0x0C)
        self.assertEqual(out[0x247], 2)
        self.assertTrue(out[0x248] & 1)
        self.assertEqual(out[0x24A:0x24E], bytes((0x2C, 0x01, 0x40, 0x01)))
        self.assertEqual(out[0x26A:0x26E], bytes((0x6F, 0x12, 0x6F, 0x12)))
        self.assertEqual(out[0x2A0], 0x01)
        self.assertEqual(out[0x2A7], 0x00)
        self.assertTrue(out[0x2B6] & 1)
        self.assertEqual(out[0x2B7] & 7, 7)
        self.assertEqual(out[0x2A8:0x2AA], bytes((0x34, 0x12)))
        self.assertEqual(out[0x26F] & 3, 3)

    def test_security_runtime(self):
        r = cid.CidConfig(
            security=2,
            gate_security=1,
            support_rpmb=1,
            gate_rpmb=1,
            ata_passthrough=1,
            gate_ata=1,
            fw_auth=1,
            thermal_throttle=1,
            ffu_keep_cid=1,
            mt1=25,
            mt2=30,
            mt3=35,
            mt1_delta=10,
            mt2_delta=20,
            mt3_delta=30,
            gate_mt_delta=1,
            ps0_sys=3,
            ps0_ldpc=3,
            ps0_flash=3,
            ps1_sys=3,
            ps1_ldpc=3,
            ps1_flash=3,
            ps2_sys=3,
            ps2_ldpc=3,
            ps2_flash=3,
            ps5_sys=3,
            ps5_ldpc=3,
            ps5_flash=3,
            gate_ps_clocks=1,
            smart_temp_option=1,
            smart_temp_value="54",
            gate_smart_temp=1,
            temp_offset=(1, 2, 3, 4, 5, 6),
            gate_smart_temp_offset=1,
        )
        out = bytearray(4096)
        cid.apply_security_runtime(out, r)
        self.assertEqual(out[0x300], 0x13)
        self.assertEqual(out[0x301], 1)
        self.assertEqual(out[0x304], 1)
        self.assertEqual(out[0x305], 1)
        self.assertEqual(out[0x390], 0x09)
        self.assertEqual(out[0x393:0x399], bytes((75, 10, 80, 20, 85, 30)))
        self.assertEqual(out[0x3A0:0x3A4], bytes((0xF4, 0x01, 0xC8, 0x00)))
        self.assertEqual(out[0x3A8], 0xF4)
        self.assertEqual(out[0x3B8], 0xF4)
        self.assertEqual((out[0x3CC], out[0x3CD]), (1, 54))
        self.assertEqual((out[0x3C1], out[0x3CB]), (1, 6))
        r.ps0_sys = 99
        with self.assertRaises(cid.CidError):
            cid.apply_security_runtime(bytearray(4096), r)

    def test_small_and_rdt(self):
        q = cid.CidConfig(
            en_output_uart=1,
            fix_mode_erase_th=0x1F3,
            gate_seq_read_th=1,
            pe_cycle=0x1B58,
            gate_pe_cycle=1,
            enable_write_protect=1,
            gate_write_protect=1,
            enable_bdg_scan=1,
            gate_bdg_scan=1,
            vdt_enable_27_23=1,
            vdt_enable_12=1,
            gate_vdt=1,
            vdt_level_27=14,
            vdt_level_23=13,
            vdt_level_12=4,
            bypass_ext_pwr_dn=1,
            gate_bypass=1,
            cache_program=1,
            d8=0,
            seq_read_th=0x40,
            watch_dog=7,
            bg_gc=1,
            cache_read=1,
            read_scrub=1,
            mt1_510=25,
            mt2_510=30,
            mt3_510=35,
            asic_shutdown=9,
            c4=1,
        )
        out = bytearray(4096)
        cid.apply_small(out, q)
        self.assertTrue(out[0x182] & 1)
        self.assertEqual(out[0x1D0:0x1D2], bytes((0xF3, 0x01)))
        self.assertEqual(out[0x1D4:0x1D6], bytes((0x58, 0x1B)))
        self.assertEqual(out[0x3F0] & 0x0C, 0x0C)
        self.assertEqual(out[0x500] & 0x0C, 0x0C)
        self.assertEqual((out[0x501], out[0x502], out[0x504]), (14, 13, 4))
        self.assertEqual(out[0x59C], 7)
        self.assertTrue(out[0x59D] & 1)
        self.assertEqual(out[0x59E] & 0x0F, 0x0F)
        self.assertEqual(out[0x59F], 0x40)
        self.assertEqual((out[0x5A0], out[0x5A2], out[0x5A3], out[0x5A5]), (75, 80, 85, 9))

        r = cid.CidConfig(
            slc_loop=5,
            erase=1,
            program=1,
            read_en=1,
            rdt_test_mode_b4=1,
            rdt_test_mode=1,
            gate_rdt_test_mode=1,
            disable_thermal=1,
            gate_disable_thermal=1,
            read_write_seq=1,
            ref_mode=2,
            slc_ecc_bit_th=0,
            tlc_ecc_bit_th=3,
            temperature_th=0x20,
            total_fail_th=1,
            erase_fail_th=2,
            program_fail_th=3,
            read_fail_th=4,
            read_loop_th=7,
            gate_read_loop=1,
            test_block_cnt="1234",
            gate_debug=1,
            rdt_test_mode_loop=9,
            disable_thermal_temp=0x11,
            erase_disturb=1,
            gate_erase_disturb=1,
            led_mode=3,
            gate_led=1,
            tlc_loop=4,
            retry_enable=1,
            gate_retry=1,
            slc_delay=10,
            tlc_delay=20,
            gate_delay=1,
            read_write_seq_cnt=5,
            gate_rw_seq=1,
            tlc_prog_en=1,
            slc_prog_en=1,
            tlc_block_num=100,
            slc_block_num=200,
            slc_prog_th=300,
            tlc_prog_th=400,
            tlc_bers_en=1,
            slc_bers_en=1,
            slc_bers_th=500,
            tlc_bers_th=600,
            gate_tprog=1,
            gate_tbers=1,
            prog_timeout_ratio=7,
            bser_timeout_ratio=8,
            gate_prog_timeout=1,
            gate_bser_timeout=1,
            chce_matrix=bytes(range(48)),
            gate_chce=1,
        )
        out = bytearray(4096)
        cid.apply_rdt(out, r)
        self.assertEqual((out[0xE00], out[0xE01], out[0xE04], out[0xE05]), (5, 0xF7, 2, 0xFF))
        self.assertEqual((out[0xE06], out[0xE07]), (3, 0x20))
        self.assertEqual(out[0xE08], 1)
        self.assertEqual(out[0xE0A:0xE10], bytes((2, 0, 3, 0, 4, 0)))
        self.assertEqual(out[0xE11], 7)
        self.assertEqual(out[0xE12:0xE14], bytes((0xD2, 0x04)))
        self.assertEqual((out[0xE14], out[0xE15]), (9, 0x11))
        self.assertTrue(out[0xE16] & 2)
        self.assertEqual(out[0xE17], 3)
        self.assertEqual(out[0xE20], 4)
        self.assertEqual(out[0xE21], 1)
        self.assertEqual((out[0xE26], out[0xE28], out[0xE38]), (10, 20, 5))
        self.assertEqual(out[0xE40], 0x0F)
        self.assertEqual(out[0xE44:0xE48], bytes((100, 0, 200, 0)))
        self.assertEqual(out[0xE48:0xE4C], bytes((0x2C, 0x01, 0x90, 0x01)))
        self.assertEqual(out[0xE4C:0xE50], bytes((0xF4, 0x01, 0x58, 0x02)))
        self.assertEqual((out[0xE50], out[0xE51]), (7, 8))
        self.assertEqual((out[0xE80], out[0xE81], out[0xEAF]), (0, 1, 47))


@unittest.skipUnless(HAVE_PKG and HAVE_W, "缺少原厂包或 fixture")
class IspTest(unittest.TestCase):
    def test_package_matches_fixture(self):
        working = (W / "cid-work.bin").read_bytes()
        package, meta = isp_package.build(
            (PKG / "Firmware/YMTC/TAS/ISP2263XT_core0_A3.bin").read_bytes(),
            (PKG / "Firmware/YMTC/TAS/ISP2263XT_core1.bin").read_bytes(),
            working,
            "YMTC",
        )
        self.assertEqual(package, (W / "isp/sm2263xt-isp-package-a3.bin").read_bytes())
        self.assertEqual(meta["boot_start"], 0xE0000)
        self.assertEqual(meta["format"], 3)
        self.assertEqual(meta["manufacturer"], 0xDA)


@unittest.skipUnless(HAVE_W, "缺少 fixture")
class CardModeTest(unittest.TestCase):
    def test_payload_matches_fixture(self):
        param = (W / "ib/param-after-infoblock.bin").read_bytes()
        tail = (PKG / "Tables/SeedTable2304.bin").read_bytes()
        payload, n512, total = card_mode.build(param, tail)
        self.assertEqual(payload, (W / "device/card-mode/card-mode-payload.bin").read_bytes())
        self.assertEqual((n512, total), (11, 5632))


@unittest.skipUnless(HAVE_W, "缺少 fixture")
class PipelineTest(unittest.TestCase):
    """p1 -> p6 -> ib -> mpinfo 与 C 版产物逐字节一致。"""

    @classmethod
    def setUpClass(cls):
        cls.param = (W / "p1/param.bin").read_bytes()
        cls.drive = (W / "p1/drive.bin").read_bytes()

    def test_bbt(self):
        result = bbt.build(
            self.param,
            [
                ROOT / "tmp/scan-org-a2",
                ROOT / "tmp/scan-org-a2-repeat",
                ROOT / "tmp/scan-org-a2-repeat2",
            ],
        )
        self.assertEqual(result.org_combined, (W / "p2/org-combined.bin").read_bytes())
        self.assertEqual(result.bbt, (W / "p2/bbt.bin").read_bytes())
        self.assertEqual(result.compact, (W / "p2/bbt-compact.bin").read_bytes())
        self.assertEqual(result.counters, (W / "p2/counters.bin").read_bytes())
        self.assertEqual(result.param_after, (W / "p2/param-after-bbt.bin").read_bytes())
        expected = (
            (W / "p2/report.txt")
            .read_text()
            .replace("tmp/scan-org-a2", str(ROOT / "tmp/scan-org-a2"))
        )
        self.assertEqual(result.report, expected)

    def test_system_and_capacity(self):
        scan = layout.system_candidates(
            (W / "p2/param-after-bbt.bin").read_bytes(), (W / "p2/bbt.bin").read_bytes()
        )
        filled = layout.fill_system((W / "p2/param-after-bbt.bin").read_bytes(), scan)
        self.assertEqual(filled, (W / "p3/param-system-candidate.bin").read_bytes())

        param = bytearray(filled)
        result, rc = pl.capacity(self.drive, param)
        self.assertEqual(rc, 0)
        self.assertEqual(bytes(param), (W / "p4/param-capacity.bin").read_bytes())
        self.assertEqual(result.data_fblocks, 398)

    def test_diffaddr(self):
        out, summary, param_after = diffaddr.build(
            (W / "p4/param-capacity.bin").read_bytes(),
            self.drive,
            (W / "p2/bbt.bin").read_bytes(),
            (W / "p2/bbt-compact.bin").read_bytes(),
        )
        self.assertEqual(out, (W / "p5/diffaddr.bin").read_bytes())
        fixture = (W / "p5/param-after-diffaddr.bin").read_bytes()
        self.assertEqual(param_after, fixture)
        self.assertEqual(int.from_bytes(param_after[0x3E:0x40], "little"), 6)
        self.assertEqual((summary.n1, summary.n2, summary.total, summary.bad_rows), (12, 0, 12, 6))

    def test_infoblock(self):
        fix = (W / "ib/infoblock.bin").read_bytes()
        rdt = fix[19 * 16384 : 29 * 16384]
        param = bytearray((W / "p6/param-capacity.bin").read_bytes())
        boot = (PKG / "Firmware/BootISP2263A3.bin").read_bytes()
        seed = (PKG / "Tables/SeedTable2304.bin").read_bytes()
        org = (W / "p2/org-combined.bin").read_bytes()
        erase = bytes(0x8000)
        total = (W / "p2/bbt.bin").read_bytes()[:0x8000]
        compact = (W / "p2/bbt-compact.bin").read_bytes()
        diff = (W / "p5/diffaddr.bin").read_bytes()
        bank = (W / "isp/sm2263xt-isp-package-a3.bin").read_bytes()

        sizes = infoblock.Sizes(
            boot_bytes=len(boot),
            seed_bytes=len(seed),
            org_sectors=_sectors(org),
            erase_sectors=_sectors(erase),
            total_sectors=_sectors(total),
            compact_sectors=_sectors(compact),
            diff_sectors=_sectors(diff),
            oprom_sectors=_sectors(bytes(0x9E00)),
            rdt_sectors=_sectors(rdt),
            bank_part0_sectors=2048,
            bank_part1_sectors=256,
        )
        plan, rc = infoblock.calculate(param, sizes)
        self.assertEqual(rc, 0)
        self.assertEqual(
            list(plan.descriptor), [0, 1, 3, 2, 4, 5, 7, 204, 9, 11, 12, 16, 19, 29, 37]
        )
        payloads = infoblock.Payloads(
            param=bytes(param),
            org=org,
            org_sectors=_sectors(org),
            erase=erase,
            erase_sectors=_sectors(erase),
            total=total,
            total_sectors=_sectors(total),
            compact=compact,
            compact_sectors=_sectors(compact),
            diff=diff,
            diff_sectors=_sectors(diff),
            oprom=bytes(0x9E00),
            oprom_sectors=_sectors(bytes(0x9E00)),
            rdt=rdt,
            rdt_sectors=_sectors(rdt),
        )
        out, typemap, boot_patched, bank_patched, special, rc = infoblock.generate(
            param, plan, plan.total_sectors, boot, seed, payloads, bank, 2304
        )
        self.assertEqual(rc, 0)
        self.assertFalse(special)
        self.assertEqual(out, fix)
        self.assertEqual(typemap, (W / "ib/infoblock-typemap.bin").read_bytes())
        self.assertEqual(boot_patched, (W / "ib/boot-patched.bin").read_bytes())
        self.assertEqual(bank_patched, (W / "ib/bank-patched.bin").read_bytes())
        self.assertEqual(bytes(param), (W / "ib/param-after-infoblock.bin").read_bytes())


@unittest.skipUnless(ORACLE.is_dir(), "缺少原厂证据目录")
class MpispTest(unittest.TestCase):
    def test_prepare_matches_vendor_download(self):
        raw = (ORACLE / "linux-tool/MPISP2263XT.bin").read_bytes()
        prepared, info, rc = mpisp.prepare(raw)
        self.assertEqual(rc, 0)
        self.assertEqual(prepared, (ORACLE / "oracle/Port0_downloadMPISP.bin").read_bytes())
        self.assertEqual(mpisp.packet_count(len(prepared)), 6)


class PhysicalSqeTest(unittest.TestCase):
    """与 C 版 self-test 的 64 字节向量一致。"""

    def setUp(self):
        self.addr = physical.PhysAddr(
            block=0x1234,
            page=0xFEDC,
            channel=0x12,
            ce=0x13,
            die=0x56,
            plane=0x83,
            read_byte34=0xAB,
            mode=0x84,
        )

    def test_read(self):
        expected = bytearray(64)
        expected[0] = 0xC2
        expected[40:42] = b"\x80\x11"
        expected[48:51] = b"\x4e\x84\x01"
        expected[52:60] = b"\x34\x12\xdc\xfe\x32\x03\xab\x56"
        self.assertEqual(physical.read_sqe(35, self.addr), bytes(expected))

    def test_write(self):
        expected = bytearray(64)
        expected[0] = 0xC1
        expected[40:42] = b"\x80\x11"
        expected[48:51] = b"\x83\x84\x01"
        expected[52:60] = b"\x34\x12\xdc\xfe\x32\x03\x00\x56"
        self.assertEqual(physical.write_sqe(35, self.addr), bytes(expected))

    def test_erase(self):
        expected = bytearray(64)
        expected[0] = 0xC0
        expected[48:51] = b"\x03\x84\x01"
        expected[52:54] = b"\x34\x12"
        expected[56:58] = b"\x32\x03"
        expected[59] = 0x56
        self.assertEqual(physical.erase_sqe(self.addr), bytes(expected))

    def test_card_mode(self):
        sqe = physical.card_mode_sqe(11)
        self.assertEqual(sqe[0], 0xC1)
        self.assertEqual(int.from_bytes(sqe[40:44], "little"), 0x580)
        self.assertEqual(int.from_bytes(sqe[48:52], "little"), 0x90)


class EraseMergeTest(unittest.TestCase):
    """total = org|erase, but P+3E counts only the org rows (vendor rule)."""

    def test_merge_and_p3e(self):
        param = bytearray(1024)
        param[0x32] = 4
        org = bytearray(4 * 64)
        org[1 * 64 + 3] = 0x02
        erase = bytearray(4 * 64)
        erase[2 * 64 + 5] = 0x01
        with tempfile.TemporaryDirectory() as tmp:
            scan = Path(tmp) / "scan"
            scan.mkdir()
            desc = bytearray(512)
            desc[0:2] = (0).to_bytes(2, "little")
            desc[2:4] = (3).to_bytes(2, "little")
            desc[32:34] = (8).to_bytes(2, "little")
            (scan / "batch-000-descriptor.bin").write_bytes(desc)
            (scan / "batch-000-result.bin").write_bytes(bytes(org).ljust(512, b"\0"))
            result = bbt.build(param, [scan], "union", bytes(erase))
        rows = [r for r in range(4) if any(result.bbt[r * 64 : (r + 1) * 64])]
        self.assertEqual(rows, [1, 2])
        self.assertEqual(result.param_after[0x3E], 1)
        self.assertEqual(result.bad_rows, 2)


class SpareTest(unittest.TestCase):
    def test_s1_s2_idx_land_at_plane_offset(self):
        s1 = infoblock.spare_s1(0x05, 7, 2)
        self.assertEqual(len(s1), 512)
        self.assertEqual(s1[64], 0xE1)
        self.assertEqual(s1[65], 0x05)
        self.assertEqual(s1[69], 7)
        self.assertEqual(s1[80], 0xE1)
        self.assertEqual(sum(s1) - 0xE1 - 0x05 - 7 - 0xE1, 0)
        s2 = infoblock.spare_s2(9, 1)
        self.assertEqual(s2[37], 9)
        idx = infoblock.spare_idx(0)
        self.assertEqual(idx[0:12], b"\xff" * 12)
        self.assertEqual(idx[12:18], b"\x5a\xaa\x5a\xaa\xe5\x25")


class CodecTest(unittest.TestCase):
    def _sqe(self) -> bytes:
        sqe = bytearray(64)
        sqe[0] = 0xC2
        sqe[40:44] = (1).to_bytes(4, "little")
        return bytes(sqe)

    def test_plan_layout(self):
        plan, rc = codec.build_plan(self._sqe(), codec.IN, 512, 1)
        self.assertEqual(rc, codec.OK)
        self.assertEqual(plan.command[:4], b"NVME")
        self.assertEqual([p.tag for p in plan.phases], [1, 2, 3])
        self.assertEqual(plan.phases[1].cdb[1], 0x82)
        self.assertEqual(plan.phases[2].cdb[1], 0x8F)

    def test_unsupported_sqe(self):
        sqe = bytearray(self._sqe())
        sqe[8] = 1
        _, rc = codec.build_plan(bytes(sqe), codec.IN, 512, 1)
        self.assertEqual(rc, codec.UNSUPPORTED_SQE)

    def test_residue_is_not_success(self):
        phase = codec.Phase(kind=codec.DATA_PHASE, direction=codec.OUT, length_bytes=512, tag=2)
        obs = codec.Observation(
            submitted=1,
            cbw_actual=31,
            data_actual=512,
            csw_actual=13,
            csw=b"USBS" + (2).to_bytes(4, "little") + (512).to_bytes(4, "little") + b"\0",
        )
        verdict = codec.check_stage(phase, obs)
        self.assertEqual(verdict.outcome, codec.UNKNOWN)
        self.assertEqual(verdict.reason, codec.REASON_RESIDUE)


@unittest.skipUnless(HAVE_PKG and HAVE_W, "缺少原厂包或 fixture")
class StagesTest(unittest.TestCase):
    def test_infoblock_matches_generator(self):
        P = PKG
        built = stages.build_infoblock(
            (W / "p6/param-capacity.bin").read_bytes(),
            (P / "Firmware/BootISP2263A3.bin").read_bytes(),
            (P / "Tables/SeedTable2304.bin").read_bytes(),
            (W / "p2/org-combined.bin").read_bytes(),
            bytes(0x8000),
            (W / "p2/bbt.bin").read_bytes(),
            (W / "p2/bbt-compact.bin").read_bytes(),
            (W / "p5/diffaddr.bin").read_bytes(),
            _need(ROOT / "tmp/py-pipeline/rdt.bin")
            and (ROOT / "tmp/py-pipeline/rdt.bin").read_bytes()
            or bytes(163840),
            (W / "isp/sm2263xt-isp-package-a3.bin").read_bytes(),
            total_bytes=0x8000,
        )
        self.assertEqual(built.pages, 101)
        self.assertEqual(
            list(built.descriptor), [0, 1, 3, 2, 4, 5, 7, 204, 9, 11, 12, 16, 19, 29, 37]
        )


if __name__ == "__main__":
    unittest.main()
