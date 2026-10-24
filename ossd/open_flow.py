"""`ossd open`: the whole card-opening flow as one command.

Follows the vendor MPTool state machine (Step0..Step7 in the 2026-10-23 trace):

    Step1 Download MPISP -> Step2 Do Pretest -> Step3/4 ISP + InfoBlock
    -> Step5 MPInfo -> Step6 Reset -> Step7 Check ISP mode

Stops at the first failed stage. The only manual step is the final power cycle.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from . import device, stages
from . import info as info_mod
from .config.package import Package
from .generator import card_mode as card_mode_gen
from .generator import drive_setting
from .generator.families import BUILTIN
from .select import core0_name, select
from .transport import policy
from .transport.usb import Target

PHASES = (
    ("mpisp", "device"),
    ("rom/connectivity", "device"),
    ("param", "offline"),
    ("cid", "offline"),
    ("isp", "offline"),
    ("card-mode", "device"),
    ("scan", "device"),
    ("bbt", "offline"),
    ("erase", "device"),
    ("bbt-merge", "offline"),
    ("system", "offline"),
    ("diffaddr", "offline"),
    ("capacity", "offline"),
    ("infoblock", "offline"),
    ("mpinfo", "offline"),
    ("card-mode-final", "device"),
    ("save-infoblock", "device"),
    ("write-mpinfo", "device"),
    ("reset", "device"),
    ("power-cycle", "physical"),
    ("check-isp", "device"),
)


class OpenError(RuntimeError):
    def __init__(self, message: str, code: int = 5):
        super().__init__(message)
        self.code = code


@dataclass
class OpenOptions:
    package: Path
    part: str
    work: Path
    template: Path | None = None
    rdt: Path | None = None
    matrix: str | None = None
    internal: int | None = None
    ch_mask: int | None = None
    ce_mask: int | None = None
    pretest_option: int | None = None
    scans: int = 3
    probe: bool = False
    dry_run: bool = False
    no_wait: bool = False
    timeout_s: int = 60
    sn: str = "AA000000000000000002"
    model: str = "SMI 2263XT"
    version: str = "V0126A"
    nqn: str = "nqn.2026-10.com.smi:nvm-subsystem-sn-AA000000000000000002"
    stamp: str = ""

    def say(self, text: str) -> None:
        print(text)


@dataclass(frozen=True)
class Paths:
    p1: Path
    p2: Path
    p5: Path
    ib: Path
    mpinfo: Path
    erase: Path
    scan: Path
    isp: Path
    dev: Path


def seed_table(pkg, drive: bytes) -> bytes:
    family = drive[0x74]
    pages = drive[0x228] | drive[0x229] << 8
    table = card_mode_gen.seed_table_drive_builder(family, pages)
    return pkg.table(card_mode_gen.seed_table_name(table)).read_bytes()


def paths(o: OpenOptions) -> Paths:
    return Paths(
        **{
            name: o.work / name
            for name in ("p1", "p2", "p5", "ib", "mpinfo", "erase", "scan", "isp", "dev")
        }
    )


def describe(o: OpenOptions) -> str:
    lines = [
        f"package  {o.package}",
        f"part     {o.part}",
        f"work     {o.work}",
        f"scans    {o.scans}",
        f"system   {'probe' if o.probe else 'fill (vendor)'}",
        "",
    ]
    for name, kind in PHASES:
        lines.append(f"  {kind:<8} {name}")
    return "\n".join(lines)


def run(o: OpenOptions) -> int:
    if o.dry_run:
        print(describe(o))
        return 0
    pkg = Package.load(o.package)
    row = select(pkg, part=o.part).row
    template = (o.template or pkg.drive_setting("DriveSettingTable_modify.bin")).read_bytes()
    traits = BUILTIN[row.columns[0]]
    probe_drive = bytes(drive_setting.build_drive_setting(template, row, traits.family))
    pretest = (
        o.pretest_option
        if o.pretest_option is not None
        else int(pkg.testprocedure()["PretestOption"])
    )
    if pretest == 1:
        raise OpenError(
            "PretestOption=1 的 Org-skip 流程尚未实现；完整扫描使用 --pretest-option 3", 2
        )
    p = paths(o)
    for path in (p.p1, p.p2, p.p5, p.ib, p.mpinfo, p.erase, p.scan, p.isp, p.dev):
        path.mkdir(parents=True, exist_ok=True)
    o.stamp = o.stamp or time.strftime("%Y%m%d%H%M")

    with Target.open() as target:
        device.identify(target)
        mode, _ = target.read(0xC2, 0x100, 0x87, 0, 1024)
        target.read(0xC2, 0x80, 0x88, 0, 512)
        state = policy.run_mode(mode)
        if state == policy.MODE_ISP:
            raise OpenError("target 已在 ISP；请短接 P13 重新上电进入 ROM", 6)
        if state != policy.MODE_MPISP:
            device.upload(target, pkg.firmware("MPISP2263.bin").read_bytes())

        rom, _ = target.read(0xC2, 0x80, 0x52, 0x9FF0, 512)
        target.read(0xC2, 0x80, 0x88, 0, 512)
        rom_tag = rom[:16].decode("ascii").rstrip("\0")
        o.say(f"Step1 ROM {rom_tag}")
        conn = device.connectivity(target, probe_drive, p.dev / "connectivity")
        active = [(ch, ce) for ch in range(4) for ce in range(4) if conn.cell[ch * 4 + ce]]
        first_ch, first_ce = active[0]
        actual_id = conn.id[first_ce * 4 + first_ch]
        internal = (
            o.internal if o.internal is not None else conn.cell[first_ch * 4 + first_ce].bit_count()
        )
        selected = select(
            pkg,
            rom_tag=rom_tag,
            flash_id=actual_id,
            ce=len(active),
            die_per_ce=internal,
            part=o.part,
        )
        matrix = o.matrix if o.matrix is not None else bytes(conn.cell).hex()
        ch_mask = (
            o.ch_mask if o.ch_mask is not None else sum(1 << ch for ch in {ch for ch, _ in active})
        )
        ce_mask = (
            o.ce_mask if o.ce_mask is not None else sum(1 << ce for ce in {ce for _, ce in active})
        )
        images = stages.build_param(
            pkg.flash_set, o.part, template, matrix, internal, ch_mask, ce_mask
        )
        stages.save_param(images, p.p1)
        drive, param = images.drive, images.param
        o.say(
            f"Step2 param: ID={actual_id.hex()} CE={len(active)} die/CE={internal} matrix={matrix}"
        )
        o.say(f"       D00={drive[0]:02x} P1A={param[0x1A]} P43={param[0x43]} pretest={pretest}")
        cid_base = pkg.lightswitch("YMTC/TAS/SM2263XT_YMTC_TAS_LightSwitch.bin").read_bytes()
        cid_work = stages.build_cid(cid_base, version=o.version + "0", model=o.model)
        (o.work / "cid.bin").write_bytes(cid_work)
        package_bytes, meta = stages.build_isp(
            pkg.firmware(core0_name(cast(str, selected.revision))).read_bytes(),
            pkg.firmware("YMTC/TAS/ISP2263XT_core1.bin").read_bytes(),
            cid_work,
        )
        (p.isp / "isp-package.bin").write_bytes(package_bytes)
        seed = seed_table(pkg, drive)
        if not device.card_mode(target, param, seed, p.dev / "card-mode").ok:
            raise OpenError("card-mode 回读不一致")
        param = device.tran_rtc(target, param, p.dev / "rtc")

        o.say(f"Step2 scan-org x{o.scans}")
        scan_dirs = []
        for index in range(o.scans):
            path = p.scan / f"run{index + 1}"
            path.mkdir(parents=True, exist_ok=True)
            for old in path.glob("batch-*"):
                old.unlink()
            stages.scan_org(target, drive, path, pretest_option=pretest)
            scan_dirs.append(path)
        bbt = _bbt(param, scan_dirs, p.p2, None)
        o.say(f"       bad_rows={bbt.bad_rows} bad_bits={bbt.bad_bits}")
        o.say("Step2 erase-scan")
        erase = stages.erase_scan(target, drive, bbt.bbt, p.erase, pretest_option=pretest)
        bbt = _bbt(param, scan_dirs, p.p2, erase)
        o.say(f"       merged bad_rows={bbt.bad_rows} bad_bits={bbt.bad_bits}")
        system = stages.layout_system(bbt.param_after, bbt.bbt)
        if o.probe:
            for candidate in system.candidates.selected:
                o.say(f"Step2 probe I={candidate.index} block={candidate.address.block}")
                device.probe_run(
                    target, bbt.param_after, candidate.index, p.dev / f"probe{candidate.index}"
                )
        stages.save_layout(system, p.p2)
        diff = stages.build_diffaddr(system.param, drive, bbt.bbt, bbt.compact)
        stages.save_diff(diff, p.p5)
        cap = stages.capacity(diff.param_after, drive)
        stages.save_capacity(cap, p.p5)
        o.say(
            f"Step2 capacity: data={cap.layout.data_fblocks} nominal={cap.layout.nominal_data_fblocks}"
        )

        built = stages.build_infoblock(
            cap.param,
            pkg.firmware(cast(str, selected.bootisp)).read_bytes(),
            seed,
            bbt.org_combined,
            erase,
            bbt.bbt[:0x8000],
            bbt.compact,
            diff.diff,
            o.rdt.read_bytes() if o.rdt else b"",
            package_bytes,
        )
        stages.save_infoblock(built, p.ib)
        o.say(f"Step3/4 InfoBlock: {built.pages} pages")
        final = stages.build_mpinfo(
            cid_work,
            pkg.firmware("MPINFO.bin").read_bytes(),
            drive,
            built.typemap,
            sn=o.sn,
            model=o.model,
            nqn=o.nqn,
            version=o.version,
            stamp=o.stamp,
        )
        stages.save_mpinfo(final, p.mpinfo)
        if not device.card_mode(target, built.param, seed, p.dev / "card-mode2").ok:
            raise OpenError("card-mode-final 回读不一致")
        o.say("Step4 save-infoblock")
        device.save_infoblock(target, built.param, built.info, built.typemap, p.dev / "save")
        stages.verify_infoblock(target, built.param, built.info, p.dev / "save")
        o.say("Step5 write-mpinfo")
        if stages.write_mpinfo(target, final, built.param, p.dev / "mpinfo"):
            raise OpenError("MPInfo verify 不一致")
        o.say("Step6 reset")
        device.reset_controller(target)

    o.say("Step7: 请完全断电，断开 P13 短接，再接回")
    if o.no_wait:
        o.say("镜像已写入；冷启动验收尚未执行")
        return 0
    input("完成后按回车继续验收（Ctrl-C 退出）... ")
    if not _wait_for_device(o.timeout_s):
        raise OpenError(f"{o.timeout_s}s 内没有重新枚举到设备", 7)
    return _verify(built.param)


def _bbt(param: bytes, scan_dirs, out: Path, erase: bytes | None):
    result = stages.build_bbt(param, scan_dirs, erase)
    stages.save_bbt(result, out)
    return result


def _wait_for_device(timeout_s: int) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            target = Target.open()
        except Exception:
            time.sleep(1)
            continue
        target.close()
        return True
    return False


def _verify(param: bytes) -> int:
    target = Target.open()
    try:
        mode, _ = target.read(0xC2, 0x100, 0x87, 0, 1024)
        target.read(0xC2, 0x80, 0x88, 0, 512)
        state = policy.run_mode(mode)
        print(f"Step7 check: {policy.MODE_NAMES[state]} (byte 0x{mode[0x210]:02x})")
        if state != policy.MODE_ISP:
            raise OpenError("Run mode 不是 ISP，开卡未生效")
        data, _ = target.read(6, 1, 0, 0, 4096)
        model = policy.printable(data[24:64], 40)
        ns = info_mod.read(target, "namespace", 1)
        actual = {f["name"]: f["value"] for f in ns.fields}["Capacity (B)"]
        expected = int.from_bytes(param[0x60:0x64], "little") * 512
        print(
            f"Step7 model={model} actual={actual} expected={expected} "
            f"({'match' if actual == expected else 'MISMATCH'})"
        )
        if actual != expected:
            raise OpenError("容量不一致", 5)
    finally:
        target.close()
    print("open: done")
    return 0
