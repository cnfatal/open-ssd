"""Pure step functions: bytes in, bytes out.

No function in the first half touches the filesystem. Callers read inputs once
and use ``save_*`` to write the returned images. Device steps stay I/O by
nature.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import device
from ..generator import bbt as bbt_gen
from ..generator import cid as cid_gen
from ..generator import diffaddr as diffaddr_gen
from ..generator import drive_setting, isp_package, layout, param_table, scan_profile
from ..generator import infoblock as ib
from ..generator import mpinfo as mpinfo_gen
from ..generator import pretest_layout as pl
from ..generator.families import builtin_traits


@dataclass
class ParamImages:
    drive: bytes
    param: bytes


@dataclass
class BbtImages:
    org_combined: bytes
    bbt: bytes
    compact: bytes
    counters: bytes
    param_after: bytes
    report: str
    summary: dict
    bad_rows: int
    bad_bits: int
    total: int
    policy: str


@dataclass
class LayoutResult:
    param: bytes
    candidates: layout.SystemScan


@dataclass
class CapacityResult:
    param: bytes
    layout: pl.CapacityLayout


@dataclass
class DiffResult:
    diff: bytes
    summary: diffaddr_gen.DiffSummary
    param_after: bytes


@dataclass
class InfoBlockImages:
    info: bytes
    typemap: bytes
    boot_patched: bytes
    bank_patched: bytes
    param: bytes
    pages: int
    descriptor: bytes


def _sectors(data: bytes) -> int:
    return (len(data) + 511) // 512


def build_param(
    flash_set, part, template: bytes, matrix: str, internal: int, ch_mask: int, ce_mask: int
) -> ParamImages:
    row = flash_set.resolve(part)
    if row is None:
        raise ValueError(f"Flash.SET 里找不到 {part}")
    traits = builtin_traits(row.columns[0])
    if traits is None:
        raise ValueError(f"颗粒家族 0x{row.columns[0]:02x} 未内置")
    drive = drive_setting.build_drive_setting(template, row, traits.family, True, ch_mask, ce_mask)
    param = param_table.build_param_table(
        drive, row, bytes.fromhex(matrix), internal, ch_mask, ce_mask, traits
    )
    return ParamImages(bytes(drive), bytes(param))


def build_cid(lightswitch: bytes, *, version="V0126A0", model="SMI 2263XT") -> bytes:
    return cid_gen.identity(lightswitch, version, "SN000000000000000000", model)


def build_isp(core0: bytes, core1: bytes, cid: bytes):
    return isp_package.build(core0, core1, cid, "YMTC")


def build_bbt(param: bytes, scan_dirs, erase=None, *, policy="union") -> BbtImages:
    result = bbt_gen.build(param, scan_dirs, policy, erase)
    return BbtImages(
        result.org_combined,
        result.bbt,
        result.compact,
        result.counters,
        result.param_after,
        result.report,
        result.summary,
        result.bad_rows,
        result.bad_bits,
        result.total,
        result.policy,
    )


def layout_system(param: bytes, bbt: bytes) -> LayoutResult:
    candidates = layout.system_candidates(param, bbt, 16)
    return LayoutResult(layout.fill_system(param, candidates), candidates)


def capacity(param: bytes, drive: bytes) -> CapacityResult:
    buf = bytearray(param)
    result, rc = pl.capacity(drive, buf)
    if rc:
        raise ValueError(f"capacity failed (reason {rc})")
    return CapacityResult(bytes(buf), result)


def build_diffaddr(param: bytes, drive: bytes, bbt: bytes, compact: bytes) -> DiffResult:
    diff, summary, after = diffaddr_gen.build(param, drive, bbt, compact)
    return DiffResult(diff, summary, after)


def build_infoblock(
    param: bytes,
    boot: bytes,
    seed: bytes,
    org: bytes,
    erase: bytes,
    total: bytes,
    compact: bytes,
    diff: bytes,
    rdt: bytes,
    bank: bytes,
    *,
    oprom: bytes | None = None,
    oprom_bytes: int = 0x9E00,
    total_bytes: int | None = None,
    bank_part0: int = 2048,
) -> InfoBlockImages:
    if len(param) != 1024:
        raise ValueError("param must be 1024 bytes")
    if total_bytes is not None:
        total = total[:total_bytes]
    if oprom is None:
        oprom = bytes(oprom_bytes)
    sizes = ib.Sizes(
        boot_bytes=len(boot),
        seed_bytes=len(seed),
        org_sectors=_sectors(org),
        erase_sectors=_sectors(erase),
        total_sectors=_sectors(total),
        compact_sectors=_sectors(compact),
        diff_sectors=_sectors(diff),
        oprom_sectors=_sectors(oprom),
        rdt_sectors=_sectors(rdt),
        bank_part0_sectors=bank_part0,
        bank_part1_sectors=len(bank) // 512 - bank_part0,
    )
    buf = bytearray(param)
    plan, rc = ib.calculate(buf, sizes)
    if rc:
        raise ValueError(f"infoblock calculate failed (0x{rc:x})")
    payloads = ib.Payloads(
        param=bytes(buf),
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
        oprom=oprom,
        oprom_sectors=_sectors(oprom),
        rdt=rdt,
        rdt_sectors=_sectors(rdt),
    )
    info, typemap, boot_p, bank_p, _special, rc = ib.generate(
        buf, plan, plan.total_sectors, boot, seed, payloads, bank, len(bank) // 512
    )
    if rc:
        raise ValueError(f"infoblock generate failed (0x{rc:x})")
    return InfoBlockImages(
        info, typemap, boot_p, bank_p, bytes(buf), plan.total_pages, plan.descriptor
    )


def build_mpinfo(
    cid: bytes,
    seed: bytes,
    drive: bytes,
    typemap: bytes | None,
    *,
    sn,
    model,
    nqn,
    version,
    stamp,
    counter: int = 1,
    stats_a: int = 0,
    stats_b: int = 0,
    cid_final: bytes | None = None,
    time_text: str | None = None,
) -> bytes:
    template = mpinfo_gen.build_template(
        cid, seed, drive, version=version, sn=sn, model=model, nqn=nqn
    )
    return mpinfo_gen.finalize(
        template,
        typemap=typemap,
        cid_final=cid_final or cid,
        counter=counter,
        time=time_text or stamp,
        stat_a=stats_a,
        stat_b=stats_b,
    )


def save_param(images: ParamImages, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "drive.bin").write_bytes(images.drive)
    (out_dir / "param.bin").write_bytes(images.param)


def save_bbt(images: BbtImages, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, data in (
        ("org-combined.bin", images.org_combined),
        ("bbt.bin", images.bbt),
        ("bbt-compact.bin", images.compact),
        ("counters.bin", images.counters),
        ("param-after-bbt.bin", images.param_after),
    ):
        (out_dir / name).write_bytes(data)
    (out_dir / "report.txt").write_text(images.report)


def save_layout(result: LayoutResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "param-system-candidate.bin").write_bytes(result.param)


def save_capacity(result: CapacityResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "param-capacity.bin").write_bytes(result.param)


def save_diff(result: DiffResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "diffaddr.bin").write_bytes(result.diff)
    (out_dir / "param-after-diffaddr.bin").write_bytes(result.param_after)


def save_infoblock(images: InfoBlockImages, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, data in (
        ("infoblock.bin", images.info),
        ("infoblock-typemap.bin", images.typemap),
        ("boot-patched.bin", images.boot_patched),
        ("bank-patched.bin", images.bank_patched),
        ("param-after-infoblock.bin", images.param),
    ):
        (out_dir / name).write_bytes(data)
    lines = [
        f"total_pages={images.pages}",
        f"total_sectors={len(images.info) // 512}",
        f"bytes={len(images.info)}",
        "special_bank=0",
    ]
    lines += [f"d{i}={v}" for i, v in enumerate(images.descriptor)]
    (out_dir / "infoblock-layout.txt").write_text(chr(10).join(lines) + chr(10))


def save_mpinfo(image: bytes, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "mpinfo.bin").write_bytes(image)


# ---------------- device steps ----------------


def card_mode(target, param: bytes, tail: bytes, out_dir=None):
    return device.card_mode(target, param, tail, out_dir)


def scan_org(target, drive: bytes, out_dir: Path, *, pretest_option: int = 3):
    derived, rc = scan_profile.derive(drive, scan_profile.ScanConfig(pretest_option=pretest_option))
    if rc:
        raise ValueError(f"scan-profile failed ({rc})")
    return device.scan_org(target, derived, out_dir)


def erase_scan(
    target,
    drive: bytes,
    bbt: bytes,
    out_dir,
    *,
    config=None,
    pretest_option: int = 3,
    max_batches: int = 0,
):
    cfg = config or scan_profile.EraseConfig(pretest_option=pretest_option)
    return device.erase_run(target, drive, cfg, bbt, out_dir, max_batches)


def save_infoblock_run(
    target, param: bytes, info: bytes, typemap: bytes, out_dir, fill_type: int = 0xFF
):
    return device.save_infoblock(target, param, info, typemap, out_dir, fill_type)


def verify_infoblock(target, param: bytes, info: bytes, out_dir=None):
    sums = device.infoblock_checksum(target, param, info, out_dir)
    expected = ib.sum32(info)
    if any(value != expected for value in sums):
        raise device.DeviceError("InfoBlock checksum MISMATCH")
    return sums


def write_mpinfo(target, image: bytes, param: bytes, out_dir: Path):
    device.mpinfo_write(target, image, param, out_dir)
    return device.mpinfo_verify(target, image, param, out_dir)
