"""Command line entry points (Python port of the C tool)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from . import stages, tables
from .config.flash_set import load_flash_set
from .config.package import Package, PackageError
from .generator import bbt as bbt_gen
from .generator import card_mode as card_mode_gen
from .generator import cid as cid_gen
from .generator import diffaddr as diffaddr_gen
from .generator import infoblock as ib
from .generator import isp_package, layout, param_table
from .generator import mpinfo as mpinfo_gen
from .generator import mpisp as mpisp_gen
from .generator import pretest_layout as pl
from .select import SelectionError, select


def _read(path) -> bytes:
    return Path(path).read_bytes()


def _read_exact(path, size: int) -> bytes:
    data = Path(path).read_bytes()
    if len(data) != size:
        raise SystemExit(f"{path}: expected {size} bytes, got {len(data)}")
    return data


def _out_dir(path) -> Path:
    out = Path(path)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _fail(message: str, code: int = 1) -> int:
    print(message, file=sys.stderr)
    return code


# ---- select / param ----


def _cmd_select(args) -> int:
    try:
        package = Package.load(args.package, ini_name=args.ini)
    except PackageError as exc:
        return _fail(str(exc), 2)
    try:
        choice = select(
            package,
            rom_tag=args.rom_tag,
            flash_id=args.flash_id,
            ce=args.ce,
            die_per_ce=args.die_per_ce,
            part=args.allow_part,
        )
    except SelectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        for row in exc.candidates:
            print(f"  ce={row.ce_count} die/ce={row.die_per_ce}  {row.name}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(choice.as_dict(), ensure_ascii=False, indent=2))
        return 0
    print(f"package   {choice.package}")
    print(
        f"config    {choice.ini_name}.ini  "
        f"(PretestOption={package.testprocedure().get('PretestOption')}, "
        f"DoQC={package.testprocedure().get('DoQC')})"
    )
    if choice.bootisp:
        print(f"rom       {args.rom_tag} → {choice.revision} → {choice.bootisp}")
    else:
        print("rom       (未提供标签)")
    row = choice.row
    print(f"nand      {row.flash_id_text}  ce={row.ce_count} die/ce={row.die_per_ce}")
    print(f"part      {choice.flash_part_num}")
    for note in choice.notes:
        print(f"note      {note}")
    return 0


def _cmd_param_build(args) -> int:
    if not args.set_path and not args.package:
        return _fail("需要 --set Flash.SET 或 --package <包目录>")
    if args.set_path:
        try:
            flash_set = load_flash_set(args.set_path)
        except OSError as exc:
            return _fail(str(exc), 2)
    else:
        try:
            package = Package.load(args.package)
        except PackageError as exc:
            return _fail(str(exc), 2)
        flash_set = package.flash_set
    out = _out_dir(args.out_dir)
    try:
        images = stages.build_param(
            flash_set,
            args.part,
            Path(args.template).read_bytes(),
            args.matrix,
            args.internal,
            args.ch_mask or 0,
            args.ce_mask or 0,
        )
        stages.save_param(images, out)
    except (ValueError, param_table.ParamError) as exc:
        return _fail(str(exc), 4)
    print(f"wrote {out}/drive.bin (2048) and {out}/param.bin (1024)")
    return 0


# ---- cid / isp ----


def _cmd_cid_identity(args) -> int:
    base = _read_exact(args.base, 4096)
    out = cid_gen.identity(base, args.version, args.serial, args.model)
    Path(args.out).write_bytes(out)
    changed = sum(1 for a, b in zip(out, base) if a != b)
    print(f"cid identity: bytes=4096 changed={changed}")
    return 0


def _cmd_cid_map(args) -> int:
    base = _read_exact(args.base, 4096)
    try:
        out, report = cid_gen.apply_map(base, Path(args.csv).read_text(encoding="latin-1"))
    except cid_gen.CidError as exc:
        return _fail(str(exc))
    Path(args.out).write_bytes(out)
    print(f"cid map: applied={report.applied} skipped={report.skipped} sections={report.sections}")
    return 0


def _cmd_cid_build(args) -> int:
    base = _read_exact(args.base, 4096)
    config = cid_gen.CidConfig()
    for item in args.set:
        if "=" not in item:
            return _fail(f"--set 需要 key=value，收到 {item!r}")
        key, value = item.split("=", 1)
        if not hasattr(config, key):
            return _fail(f"未知字段 {key}")
        current = getattr(config, key)
        if key == "chce_matrix":
            matrix = bytes(int(x, 0) for x in value.split(","))
            if len(matrix) != 48:
                return _fail("chce_matrix 需要 48 字节")
            setattr(config, key, matrix)
        elif isinstance(current, str) or current is None:
            setattr(config, key, value)
        else:
            setattr(config, key, int(value, 0))
    try:
        out = cid_gen.build(base, config)
    except cid_gen.CidError as exc:
        return _fail(str(exc))
    Path(args.out).write_bytes(out)
    changed = sum(1 for a, b in zip(out, base) if a != b)
    print(f"cid build: bytes=4096 changed={changed}")
    print(
        f"cid build: PCI {out[0x201]:02X}{out[0x200]:02X}:"
        f"{out[0x203]:02X}{out[0x202]:02X} NVMe {out[0x26B]:02X}"
        f"{out[0x26A]:02X}:{out[0x26D]:02X}{out[0x26C]:02X}"
    )
    return 0


def _cmd_isp_package(args) -> int:
    core0 = _read(args.core0)
    core1 = _read(args.core1)
    try:
        package, meta = isp_package.build(
            core0, core1, _read_exact(args.lightswitch, 4096), args.manufacturer
        )
    except isp_package.PackageError as exc:
        return _fail(str(exc), 2)
    out = _out_dir(args.out)
    (out / "sm2263xt-isp-package-a3.bin").write_bytes(package)
    (out / "package-report.txt").write_text(
        f"core1_bytes={len(core1)}\ncore0_bytes={len(core0)}\n"
        f"package_bytes={meta['bytes']}\nboot_start=0x{meta['boot_start']:x}\n"
        f"format=0x{meta['format']:02x}\n"
        f"manufacturer=0x{meta['manufacturer']:02x}\n"
        f"sha_applied={meta['sha_applied']}\n"
    )
    print(
        f"isp package: bytes={meta['bytes']} "
        f"boot_start=0x{meta['boot_start']:x} "
        f"format={meta['format']:02x} mfg={meta['manufacturer']:02x} "
        f"sha={meta['sha_applied']}"
    )
    return 0


# ---- bbt / diffaddr ----


def _cmd_bbt_build(args) -> int:
    param = _read_exact(args.param, 1024)
    out = _out_dir(args.out)
    try:
        result = stages.build_bbt(
            param, args.scan, _read(args.erase) if args.erase else None, policy=args.policy
        )
        stages.save_bbt(result, out)
    except bbt_gen.BbtError as exc:
        return _fail(str(exc))
    (out / "summary.json").write_text(bbt_gen.summary_json(result.summary))
    print(
        f"bbt: policy={result.policy} runs={len(args.scan)} T={result.total} "
        f"bad_rows={result.bad_rows} bad_bits={result.bad_bits}"
    )
    print(
        f"bbt: counters total_bits="
        f"{result.counters[0x200] | result.counters[0x201] << 8} "
        f"bad_rows={result.counters[0x202] | result.counters[0x203] << 8}"
    )
    print(f"wrote {out}/bbt.bin, bbt-compact.bin, counters.bin, summary.json")
    return 0


def _cmd_diffaddr_build(args) -> int:
    param = _read_exact(args.param, 1024)
    drive = _read_exact(args.drive, 2048)
    out = _out_dir(args.out)
    try:
        res = stages.build_diffaddr(param, drive, _read(args.bbt), _read(args.compact))
        stages.save_diff(res, out)
        out_bytes, summary = res.diff, res.summary
    except diffaddr_gen.DiffError as exc:
        return _fail(str(exc), 2)
    (out / "diffaddr-summary.txt").write_text(
        f"n1={summary.n1}\nn2={summary.n2}\ntotal={summary.total}\n"
        f"bad_rows={summary.bad_rows}\noutput_bytes={len(out_bytes)}\n"
    )
    print(
        f"diffaddr: n1={summary.n1} n2={summary.n2} total={summary.total} "
        f"bad_rows={summary.bad_rows}"
    )
    return 0


# ---- infoblock ----


def _cmd_infoblock_build(args) -> int:
    param = _read_exact(args.param, 1024)
    boot = _read(args.boot)
    seed = _read(args.seed)
    bank = _read(args.bank)
    if len(bank) % 512:
        return _fail("bank: size must be a sector multiple")
    out = _out_dir(args.out)
    try:
        built = stages.build_infoblock(
            param,
            boot,
            seed,
            _read(args.org),
            _read(args.erase),
            _read(args.total),
            _read(args.compact),
            _read(args.diff),
            _read(args.rdt) if args.rdt else b"",
            bank,
            oprom=_read(args.oprom) if args.oprom else None,
            oprom_bytes=args.oprom_bytes or 0x9E00,
            total_bytes=args.total_bytes,
            bank_part0=args.bank_part0_sectors,
        )
    except ValueError as exc:
        return _fail(str(exc), 2)
    stages.save_infoblock(built, out)
    size = len(built.info)
    print(
        f"infoblock: pages={built.pages} sectors={size // 512} "
        "descriptor=" + ",".join(str(v) for v in built.descriptor)
    )
    print(f"infoblock: bytes={size} special_bank=0; wrote infoblock.bin")
    return 0


def _cmd_infoblock_compare(args) -> int:
    info = _read(args.info)
    expected = ib.sum32(info)
    print(f"compare: bytes={len(info)} expected=0x{expected:08x}")
    rc = 0
    for copy, path in enumerate((args.reply0, args.reply1)):
        result, device = ib.compare_reply(_read(path), expected)
        if result < 0:
            return _fail(f"copy{copy} response needs at least 4 bytes")
        print(f"copy{copy}: device=0x{device:08x} {'MISMATCH' if result else 'match'}")
        if result:
            rc = 5
    return rc


def _cmd_infoblock_save_frame(args) -> int:
    param = _read_exact(args.param, 1024)
    info = _read(args.info)
    typemap = _read(args.typemap)
    per_page = param[0x43]
    pages = int.from_bytes(param[0x48:0x4A], "little")
    if not per_page or len(info) % 512 or not pages:
        return _fail("invalid P43/P48 or InfoBlock size")
    total_sectors = len(info) // 512
    k = (total_sectors + per_page - 1) // per_page
    if len(typemap) < k:
        return _fail(f"typeMap needs at least {k} bytes")
    n512 = per_page + 1
    host_sum = ib.sum32(info)
    print(
        f"save-frame: K={k} L={pages} n512={n512} "
        f"host_sum=0x{host_sum:08x} fill_type=0x{args.fill_type:02x}"
    )
    out = _out_dir(args.out)
    erases = writes = 0

    def save(name: str, data: bytes) -> None:
        (out / name).write_bytes(data)

    for copy in range(2):
        address = pl.system_address(param, param[0x20 + copy])
        if address is None:
            return _fail(f"save-frame: copy {copy} decode failed")
        repeat = param[0x17] if param[0x0C] & 0x04 else 1
        repeat = repeat or 1
        for d in range(repeat):
            current = address
            current.die = address.die + d
            save(f"copy{copy}-die{d}-erase.bin", ib.erase_sqe(current))
            erases += 1
            spares = bytearray(pages * 512)
            for page in range(pages):
                type_byte = typemap[page] if page < k else args.fill_type
                spares[page * 512 : (page + 1) * 512] = ib.spare_s1(type_byte, page, current.plane)
                save(
                    f"copy{copy}-die{d}-write-{page:03d}.bin",
                    ib.write_mode_sqe(current, page, n512, 0x95 if page < 4 else 0xC5),
                )
                writes += 1
            save(f"copy{copy}-die{d}-spares.bin", bytes(spares))
        save(f"copy{copy}-checksum.bin", ib.checksum_sqe(address, k, n512, param[0x7B]))
        print(
            f"copy{copy}: block={address.block} plane={address.plane} "
            f"ch={address.ch} ce={address.ce} die={address.die}"
        )

    if param[0xD3] & 0x01:
        pos = (param[0x27] + 1) & 0xFF
        limit = int.from_bytes(param[0x30:0x32], "little") * (param[0x16] * param[0x13])
        guard = 0
        while pos < limit and guard < 256:
            guard += 1
            address = pl.system_address(param, pos)
            if address is None:
                return _fail(f"save-frame: extra {pos} decode failed")
            save(f"extra-{pos:03d}-erase.bin", ib.erase_sqe(address))
            erases += 1
            for page in range(pages):
                save(
                    f"extra-{pos:03d}-write-{page:03d}.bin",
                    ib.write_mode_sqe(address, page, n512, 0x95 if page < 4 else 0xC5),
                )
                writes += 1
            pos = (pos + 1) & 0xFF

    address = pl.system_address(param, param[0x23])
    if address is None:
        return _fail("save-frame: idx decode failed")
    save("idx-erase.bin", ib.erase_sqe(address))
    erases += 1
    idx = bytearray(n512 * 512)
    idx[per_page * 512 : per_page * 512 + 512] = ib.spare_idx(address.plane)
    save("idx-write-000.bin", ib.write_mode_sqe(address, 0, n512, 0xC5))
    save("idx-page.bin", bytes(idx))
    writes += 1
    print(
        f"idx: block={address.block} plane={address.plane} "
        f"ch={address.ch} ce={address.ce} die={address.die}"
    )
    (out / "save-plan.txt").write_text(
        f"K={k}\nL={pages}\nn512={n512}\nhost_sum=0x{host_sum:08x}\n"
        f"fill_type=0x{args.fill_type:02x}\nfill_main=zero\n"
        f"erases={erases}\nwrites={writes}\n"
    )
    print(f"save-frame: erases={erases} writes={writes}")
    return 0


# ---- layout ----


def _cmd_layout_system(args) -> int:
    param = _read_exact(args.param, 1024)
    bbt = _read(args.bbt)
    try:
        scan = layout.system_candidates(param, bbt, args.limit)
    except ValueError as exc:
        return _fail(str(exc))
    print(f"system candidates: T={scan.total} slots=8 limit={scan.limit}")
    for candidate in scan.listed:
        a = candidate.address
        print(
            f"  I={candidate.index:3d} block={a.block} plane={a.plane} "
            f"ch={a.logical_ch}/{a.ch} ce={a.logical_ce}/{a.ce} "
            f"die={a.die} bit={a.bad_bit}"
        )
    print(
        f"system candidates: {scan.usable} not marked bad; first eight ="
        + "".join(f" {c.index}" for c in scan.selected)
    )
    if args.fill:
        try:
            filled = layout.fill_system(param, scan)
        except ValueError as exc:
            return _fail(str(exc))
        if not args.out:
            return _fail("--fill requires --out")
        out = _out_dir(args.out)
        (out / "param-system-candidate.bin").write_bytes(filled)
        system_block = filled[0x30] | filled[0x31] << 8
        last = scan.selected[7]
        print(
            f"system: wrote unprobed P+20..P+27 and P+30={system_block} "
            f"(slot7 I={last.index} block={last.address.block})"
        )
    return 0


def _cmd_layout_capacity(args) -> int:
    from .generator import pretest_layout as pl

    param = bytearray(_read_exact(args.param, 1024))
    drive = _read_exact(args.drive, 2048)
    if args.system_blocks is not None:
        param[0x30] = args.system_blocks & 0xFF
        param[0x31] = (args.system_blocks >> 8) & 0xFF
        print(f"capacity: provisional P+30={args.system_blocks} (not device-probed)")
    elif not (param[0x30] | param[0x31] << 8):
        return _fail(
            "capacity: P+30 is zero; run the system-block stage or "
            "pass --system-blocks N explicitly"
        )
    result, rc = pl.capacity(drive, param)
    if rc:
        return _fail(f"capacity: arithmetic failed (reason {rc})", 2)
    print(
        f"capacity: total={result.total_fblocks} "
        f"later_bad={result.later_bad_fblocks} "
        f"system={result.system_fblocks} static_slc={result.static_slc} "
        f"type2={result.type2_fblocks}"
    )
    print(
        f"capacity: data={result.data_fblocks} "
        f"nominal={result.nominal_data_fblocks} "
        f"reserve={result.reserve_fblocks} good={result.good_fblocks} "
        f"min_good={result.min_good_fblocks}"
    )
    print(
        f"capacity: total_static_tlc={result.total_static_tlc} "
        f"gc={result.gc_threshold} surplus={result.surplus_fblocks} "
        f"extra_tcg={result.extra_tcg_fblocks}"
    )
    print(
        f"capacity: sectors_per_fblock={result.sectors_per_fblock} "
        f"total_sectors={result.total_data_sectors}"
    )
    out = _out_dir(args.out)
    (out / "param-capacity.bin").write_bytes(bytes(param))
    (out / "capacity.txt").write_text(
        "\n".join(
            f"{name}={value}"
            for name, value in [
                ("total_fblocks", result.total_fblocks),
                ("later_bad_fblocks", result.later_bad_fblocks),
                ("system_fblocks", result.system_fblocks),
                ("static_slc", result.static_slc),
                ("type2_fblocks", result.type2_fblocks),
                ("nondata_fblocks", result.nondata_fblocks),
                ("max_data_fblocks", result.max_data_fblocks),
                ("data_fblocks", result.data_fblocks),
                ("nominal_data_fblocks", result.nominal_data_fblocks),
                ("reserve_fblocks", result.reserve_fblocks),
                ("min_static_tlc", result.min_static_tlc),
                ("total_static_tlc", result.total_static_tlc),
                ("good_fblocks", result.good_fblocks),
                ("min_good_fblocks", result.min_good_fblocks),
                ("surplus_fblocks", result.surplus_fblocks),
                ("gc_threshold", result.gc_threshold),
                ("extra_tcg_fblocks", result.extra_tcg_fblocks),
                ("sectors_per_fblock", result.sectors_per_fblock),
                ("total_data_sectors", result.total_data_sectors),
            ]
        )
        + "\n"
    )
    return 0


# ---- mpinfo ----


def _cmd_mpinfo_build(args) -> int:
    cid = _read_exact(args.cid, 4096)
    out = _out_dir(args.out)
    final = stages.build_mpinfo(
        cid,
        _read_exact(args.seed, 4096),
        _read(args.drive),
        _read(args.typemap) if args.typemap else None,
        sn=args.sn,
        model=args.model,
        nqn=args.nqn,
        version=args.version,
        stamp=args.time or "",
        counter=args.counter,
        stats_a=args.stats_a,
        stats_b=args.stats_b,
        cid_final=_read_exact(args.cid_final, 4096) if args.cid_final else None,
        time_text=args.time,
    )
    stages.save_mpinfo(final, out)
    print(f"mpinfo build: template=8192 final={len(final)}")
    return 0


def _cmd_mpinfo_inspect(args) -> int:
    view = mpinfo_gen.inspect(_read(args.mpinfo))
    print(f"mpinfo: flags=0x{view['flags']:08x} counter={view['counter']}")
    for key in ("sn", "model", "time", "nqn"):
        print(f'mpinfo: {key}="{view[key]}"')
    return 0


# ---- device ----


def _open_target():
    from .transport.usb import Target

    return Target.open()


def _cmd_dev_scan(args) -> int:
    from .transport import usb

    try:
        found = usb.scan()
    except usb.UsbError as exc:
        return _fail(str(exc), 2)
    for identity in found:
        print(
            f"{identity.vid:04x}:{identity.pid:04x} bus={identity.bus} "
            f"address={identity.address} "
            f"ep_in=0x{identity.endpoint_in:02x} "
            f"ep_out=0x{identity.endpoint_out:02x} "
            f"serial={identity.serial or '(none)'}"
        )
    if not found:
        return _fail(f"no {usb.VID:04x}:{usb.PID:04x} target", 4)
    return 0


def _cmd_dev_probe(args) -> int:
    from . import device

    try:
        with _open_target() as target:
            device.identify(target)
    except Exception as exc:
        return _fail(str(exc), 4)
    return 0


def _cmd_dev_reset(args) -> int:
    from . import device

    try:
        with _open_target() as target:
            device.reset_controller(target)
    except Exception as exc:
        return _fail(str(exc), 4)
    return 0


def _cmd_dev_usbreset(args) -> int:
    from .transport import usb

    try:
        usb.reset_bridge()
    except usb.UsbError as exc:
        return _fail(str(exc), 4)
    print("usbreset: done")
    return 0


def _cmd_read(args) -> int:
    from . import device, info
    from .transport import policy

    if args.read_command in ("controller", "namespace", "smart", "summary"):
        kinds = (
            ["controller", "namespace", "smart"]
            if args.read_command == "summary"
            else [args.read_command]
        )
        if args.decode and args.read_command == "summary":
            return _fail("--decode 不支持 summary")
        try:
            if args.decode:
                data = Path(args.decode).read_bytes()
                results = [
                    info.ReadResult(
                        kind=args.read_command,
                        nsid=args.nsid,
                        sqe=b"",
                        data=data,
                        fields=info.decode(args.read_command, data, args.nsid),
                    )
                ]
            else:
                with _open_target() as target:
                    results = [info.read(target, kind, args.nsid) for kind in kinds]
            for result in results:
                if args.out:
                    info.save(result, Path(args.out) / result.kind)
                if args.table:
                    result.fields = tables.decode(result.data, tables.load_table(args.table))
        except Exception as exc:
            return _fail(str(exc), 4)
        if args.format == "json":
            data = [info.as_dict(result) for result in results]
            print(
                json.dumps(
                    data if args.read_command == "summary" else data[0],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            for result in results:
                if not args.decode:
                    print(f"== {result.kind} ==")
                if args.table:
                    print(tables.render(result.fields))
                else:
                    print(info.render(result, args.format))
        return 0

    if args.read_command == "flash-id" and args.decode:
        data = _read_exact(args.decode, 2048)
        print("offline decode only; completion status is not validated")
        print(f"Flash-ID controller field: {policy.printable(data[0x1F0:], 32)}")
        banks, unknown = policy.decode_flash_id(data)
        for slot in unknown:
            print(f"Slot{slot:02d}: unrecognized prefix {data[0x30 + slot * 8]:02x}, excluded")
        for slot, chunk in banks:
            print(f"Bank{slot:02d}: " + " ".join(f"{b:02x}" for b in chunk))
        print(f"Candidate NAND banks: {len(banks)} (not a physical chip or die count)")
        return 0 if banks else 1
    if args.read_command == "rom" and args.decode:
        rom = _read_exact(args.decode[0], 512)
        mode = _read_exact(args.decode[1], 1024)
        print("offline decode only; completion status is not validated")
        branch = policy.rom_branch(rom)
        state = policy.run_mode(mode)
        print(f"ROM tag (first 16 bytes): {policy.printable(rom, 16)}")
        print(f"Reviewed package branch: {branch or 'not recognized'}")
        print(f"DriveInfo raw mode byte: {mode[0x210]:02x}")
        print(f"Run mode: {policy.MODE_NAMES[state]}")
        return 5 if branch is None or state == policy.MODE_UNKNOWN else 0

    handler = {
        "flash-id": device.read_flash_id,
        "rom": device.read_rom,
        "mode": device.read_mode,
        "drive-info": device.read_drive_info,
    }[args.read_command]
    try:
        with _open_target() as target:
            device.identify(target)
            handler(target)
    except Exception as exc:
        return _fail(str(exc), 4)
    return 0


def _cmd_mpisp(args) -> int:
    from . import device

    if args.mpisp_command == "inspect":
        data = _read(args.file)
        prepared, info, rc = mpisp_gen.prepare(data)
        print(
            f"mpisp: bytes={len(data)} body_offset=0x{info.body_offset:x} "
            f"body_bytes={info.body_bytes} "
            f"packets={mpisp_gen.packet_count(len(prepared))} "
            f"sha256={info.body_sha256.hex()}"
        )
        if rc:
            return _fail(mpisp_gen.error_text(rc))
        return 0
    if args.mpisp_command == "prepare":
        prepared, info, rc = mpisp_gen.prepare(_read(args.file))
        if rc:
            return _fail(mpisp_gen.error_text(rc))
        Path(args.out).write_bytes(prepared)
        print(f"mpisp prepare: bytes={len(prepared)} sha256={info.body_sha256.hex()}")
        return 0
    try:
        with _open_target() as target:
            device.identify(target)
            device.upload(target, _read(args.file))
    except Exception as exc:
        return _fail(str(exc), 4)
    return 0


def _cmd_pretest_card_mode(args) -> int:

    param = _read_exact(args.param, 1024)
    if args.tail:
        tail = _read(args.tail)
    else:
        if args.drive:
            drive = _read_exact(args.drive, 2048)
            family = drive[0x74]
            pages = drive[0x228] | drive[0x229] << 8
        else:
            family = args.family
            pages = args.page_number
        table = (
            card_mode_gen.seed_table_early(family)
            if args.stage == "early"
            else card_mode_gen.seed_table_drive_builder(family, pages)
        )
        name = card_mode_gen.seed_table_name(table)
        print(f"tail: family=0x{family:02x} page_number={pages} stage={args.stage} -> {name}")
        tail = _read(Path(args.tables_dir) / name)
    if len(tail) > card_mode_gen.TAIL_CAPACITY:
        return _fail(f"tail: {len(tail)} bytes exceeds {card_mode_gen.TAIL_CAPACITY}")
    if args.dry_run:
        payload, n512, total = card_mode_gen.build(param, tail)
        print(
            f"card-mode: param=1024 tail={len(tail)} n512={n512} "
            f"total={total} cdw10=0x{n512 * 128:x}"
        )
        if args.out:
            (_out_dir(args.out) / "card-mode-payload.bin").write_bytes(payload)
        print("dry-run: payload built; no device command sent")
        return 0
    try:
        with _open_target() as target:
            result = stages.card_mode(target, param, tail, Path(args.out) if args.out else None)
    except Exception as exc:
        return _fail(str(exc), 4)
    return 0 if result.ok else 5


def _cmd_pretest_tran_rtc(args) -> int:
    from . import device

    param = _read_exact(args.param, 1024)
    try:
        with _open_target() as target:
            device.tran_rtc(target, param, Path(args.out) if args.out else None)
    except Exception as exc:
        return _fail(str(exc), 4)
    return 0


def _cmd_infoblock_save_run(args) -> int:
    param = _read_exact(args.param, 1024)
    info = _read(args.info)
    typemap = _read(args.typemap)
    if args.dry_run:
        per_page = param[0x43]
        pages = int.from_bytes(param[0x48:0x4A], "little")
        k = (len(info) // 512 + per_page - 1) // per_page
        print(f"save-run: K={k} L={pages} host_sum=0x{ib.sum32(info):08x}")
        print("save-run: dry-run, 3 erases, 1537 writes expected; no device")
        return 0
    try:
        with _open_target() as target:
            erases, writes = stages.save_infoblock_run(
                target, param, info, typemap, Path(args.out), args.fill_type
            )
            stages.verify_infoblock(target, param, info, Path(args.out))
    except Exception as exc:
        return _fail(str(exc), 4)
    print(f"save-run: erases={erases} writes={writes}")
    return 0


def _cmd_mpinfo_write(args) -> int:
    from . import device

    try:
        with _open_target() as target:
            device.mpinfo_write(
                target,
                _read(args.mpinfo),
                _read_exact(args.param, 1024),
                Path(args.out),
                args.pages,
            )
    except Exception as exc:
        return _fail(str(exc), 4)
    return 0


def _cmd_mpinfo_verify(args) -> int:
    from . import device

    try:
        with _open_target() as target:
            return device.mpinfo_verify(
                target,
                _read(args.mpinfo),
                _read_exact(args.param, 1024),
                Path(args.out),
                args.pages,
            )
    except Exception as exc:
        return _fail(str(exc), 4)


def _cmd_mpinfo_dump(args) -> int:
    from . import device

    try:
        with _open_target() as target:
            device.mpinfo_dump(
                target,
                _read_exact(args.param, 1024),
                Path(args.out),
                args.page,
                args.index,
                args.mode,
            )
    except Exception as exc:
        return _fail(str(exc), 4)
    return 0


def _cmd_pretest_scan_profile(args) -> int:
    from .generator import scan_profile

    drive = _read_exact(args.drive, 2048)
    config = scan_profile.ScanConfig(
        pretest_option=args.pretest_option,
        show_scan_bad_count=args.show_scan_bad_count,
        scan_bad_count=args.scan_bad_count,
    )
    derived, rc = scan_profile.derive(drive, config)
    if rc:
        return _fail(f"scan-profile: derivation failed ({rc})")
    pages = ",".join(f"{value:04x}" for value in derived.pages)
    offsets = ",".join(f"{value:04x}" for value in derived.offsets)
    print(
        f"scan-profile: T={derived.total} R={derived.batch} "
        f"mode={derived.mode} pages={pages} offsets={offsets} "
        f"flags={derived.byte5}/{derived.byte6}/{derived.byte7} "
        f"batches={derived.batches} nresult={derived.nresult}"
    )
    if not derived.batch:
        print("note: R=0; the original PretestOption=1 path does not submit Org scan")
    return 0


def _cmd_pretest_scan_org(args) -> int:
    from . import device
    from .generator import scan_profile

    if args.drive:
        if args.total or args.batch:
            return _fail("--total/--batch cannot be combined with --drive")
        drive = _read_exact(args.drive, 2048)
        config = scan_profile.ScanConfig(
            pretest_option=args.pretest_option,
            show_scan_bad_count=args.show_scan_bad_count,
            scan_bad_count=args.scan_bad_count,
        )
        derived, rc = scan_profile.derive(drive, config)
        if rc:
            return _fail(f"scan-org: derivation failed ({rc})")
        print(
            f"scan-org: T={derived.total} R={derived.batch} "
            f"mode={derived.mode} byte5={derived.byte5} "
            f"byte6=0x{derived.byte6:02x} byte7={derived.byte7}"
        )
        print("pages  " + ",".join(str(v) for v in derived.pages))
        print("offsets " + ",".join(str(v) for v in derived.offsets))
    else:
        if not args.total or not args.batch:
            return _fail("需要 --drive 或 --total/--batch")
        derived = scan_profile.ScanDerived(
            total=args.total,
            batch=args.batch,
            mode=args.mode,
            byte5=args.byte5,
            byte6=args.byte6,
            byte7=args.byte7,
            pages=list(args.pages),
            offsets=list(args.offsets),
        )
        derived.batches = (derived.total + derived.batch - 1) // derived.batch
        derived.nresult = derived.batch // 8
    if not derived.batch:
        return _fail("scan-org: R=0; the original workflow skips the scan", 6)
    try:
        with _open_target() as target:
            device.scan_org(target, derived, Path(args.result_dir))
    except Exception as exc:
        return _fail(str(exc), 4)
    return 0


def _cmd_pretest_erase_run(args) -> int:
    from .generator import scan_profile

    drive = _read_exact(args.drive, 2048)
    config = scan_profile.EraseConfig(
        pretest_option=args.pretest_option, do_not_erase_bad=args.do_not_erase_bad
    )
    try:
        with _open_target() as target:
            stages.erase_scan(
                target,
                drive,
                _read(args.bbt),
                Path(args.out),
                config=config,
                max_batches=args.max_batches,
            )
    except Exception as exc:
        return _fail(str(exc), 4)
    return 0


def _cmd_pretest_erase_frame(args) -> int:
    from .generator import physical, scan_profile

    drive = _read_exact(args.drive, 2048)
    config = scan_profile.EraseConfig(
        pretest_option=args.pretest_option, do_not_erase_bad=args.do_not_erase_bad
    )
    derived, rc = scan_profile.erase_derive(drive, config)
    if rc:
        return _fail(f"erase-frame: derivation failed ({rc})")
    if not derived.batch:
        return _fail("erase-frame: R=0; the original workflow skips erase scan", 6)
    if not derived.nresult:
        return _fail("erase-frame: R<8 yields no whole result rows")
    bbt = _read(args.bbt)
    if len(bbt) < derived.total * 64:
        return _fail(f"erase-frame: bbt too small for T={derived.total}")
    out = _out_dir(args.out)
    result_bytes = derived.nresult * 512
    print(
        f"erase-frame: T={derived.total} R={derived.batch} "
        f"mode={derived.mode} batches={derived.batches} "
        f"nresult={derived.nresult}"
    )
    for i in range(derived.batches):
        first, last = scan_profile.batch_range(derived.total, derived.batch, i)
        chunk = bytearray(result_bytes)
        offset = first * 64
        take = min(result_bytes, max(0, len(bbt) - offset))
        chunk[:take] = bbt[offset : offset + take]
        submit = physical.scan_erase_submit_sqe(derived.nresult)
        result = physical.scan_erase_result_sqe(
            derived.nresult, first, last, derived.mode, derived.batch
        )
        (out / f"batch-{i:03d}-submit.bin").write_bytes(submit)
        (out / f"batch-{i:03d}-input.bin").write_bytes(bytes(chunk))
        (out / f"batch-{i:03d}-result.sqe.bin").write_bytes(result)
        print(
            f"batch {i}: blocks {first}..{last}  "
            f"C1/92 CDW10=0x{derived.nresult * 128:x}  "
            f"C2/83 CDW12=0x{(derived.mode << 8 | 0x83):x} "
            f"CDW13=0x{(last << 16 | first):x} CDW14=0x{derived.batch:x}"
        )
    return 0


def _cmd_pretest_probe_frame(args) -> int:
    from . import device

    param = _read_exact(args.param, 1024)
    try:
        device.probe_frame(param, args.index, Path(args.out), args.sum_sectors)
    except Exception as exc:
        return _fail(str(exc))
    return 0


def _cmd_pretest_probe_run(args) -> int:
    from . import device

    param = _read_exact(args.param, 1024)
    try:
        with _open_target() as target:
            device.probe_run(target, param, args.index, Path(args.out), args.sum_sectors)
    except Exception as exc:
        return _fail(str(exc), 4)
    return 0


def _cmd_pretest_connectivity(args) -> int:
    from . import device

    drive = _read_exact(args.drive, 2048)
    try:
        with _open_target() as target:
            device.connectivity(target, drive, Path(args.out))
    except Exception as exc:
        return _fail(str(exc), 4)
    return 0


def _cmd_dev_passthru(args) -> int:
    from . import passthru

    try:
        request = passthru.from_namespace(args)
    except passthru.PassthruError as exc:
        return _fail(str(exc))
    if request.dry_run:
        print(passthru.dry_run(request))
        return 0
    return passthru.run(request)


def _cmd_dev_scsi(args) -> int:
    from .transport import codec

    cdb = bytes.fromhex(args.cdb.replace(" ", ""))
    if not cdb or len(cdb) > 16:
        return _fail("--cdb 需要 1..16 字节的十六进制")
    direction = codec.IN if args.data_in else codec.OUT if args.data_out else codec.NONE
    payload = None
    length = args.data_in or 0
    if direction == codec.OUT:
        payload = _read(args.data_out)
        length = len(payload)
    elif direction == codec.IN:
        payload = bytearray(length)
    plan, code = codec.build_cdb_plan(cdb, direction, length, 1)
    if code:
        return _fail(f"unsupported CDB/direction/length: codec={code}")
    if args.dry_run:
        print(
            json.dumps(
                {
                    "cdb": cdb.hex(),
                    "direction": direction,
                    "payload_bytes": length,
                    "phases": [
                        {"cdb_hex": ph.cdb.hex(), "bytes": ph.length_bytes} for ph in plan.phases
                    ],
                },
                indent=2,
            )
        )
        return 0
    out = _out_dir(args.output_dir) if args.output_dir else None
    with _open_target() as target:
        result, accepted = target.transport.execute_cdb(cdb, direction, payload, length)
        if not accepted:
            return _fail("rejected before submission", 4)
        if out:
            (out / "request.cdb.bin").write_bytes(cdb)
            if direction == codec.IN:
                (out / "data-in.bin").write_bytes(result.payload[:length])
            elif direction == codec.OUT:
                (out / "data-out.bin").write_bytes(cast(bytes, payload))
            (out / "csw.bin").write_bytes(
                result.phases[0].observation.csw[: result.phases[0].observation.csw_actual]
            )
        print(
            json.dumps(
                {
                    "outcome": result.outcome,
                    "fault": result.fault,
                    "actual": result.phases[0].observation.data_actual,
                    "residue": result.phases[0].verdict.residue,
                    "csw_hex": result.phases[0].observation.csw.hex(),
                },
                indent=2,
            )
        )
    return 0 if result.outcome == codec.CONFIRMED else 5


def _cmd_dev_gpio(args) -> int:
    from . import bridge

    if args.dry_run:
        print(
            json.dumps(
                {
                    "prepare_cdb": bridge.PREPARE_CDB.hex(),
                    "read_cdb": bridge.READ_CDB.hex(),
                    "selector": args.selector,
                    "device_word": args.device_word,
                    "prepare_payload_head": bridge.prepare_payload(args.selector, args.device_word)[
                        :0x48
                    ].hex(),
                },
                indent=2,
            )
        )
        return 0
    with _open_target() as target:
        try:
            value = bridge.gpio_read(target, args.selector, args.device_word)
        except bridge.BridgeError as exc:
            return _fail(str(exc), 4)
    print(bridge.render(args.selector, value))
    return 0


def _cmd_open(args) -> int:
    from . import open_flow

    options = open_flow.OpenOptions(
        package=Path(args.package),
        part=args.part,
        work=Path(args.work),
        template=Path(args.template) if args.template else None,
        rdt=Path(args.rdt) if args.rdt else None,
        matrix=args.matrix,
        internal=args.internal,
        ch_mask=args.ch_mask,
        ce_mask=args.ce_mask,
        scans=args.scans,
        pretest_option=args.pretest_option,
        probe=args.probe,
        dry_run=args.dry_run,
        no_wait=args.no_wait,
        timeout_s=args.timeout,
        sn=args.sn,
        model=args.model,
        version=args.version,
        nqn=args.nqn,
    )
    try:
        return open_flow.run(options)
    except open_flow.OpenError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    except Exception as exc:  # noqa: BLE001
        print(f"open failed: {exc}", file=sys.stderr)
        return 4


def _cmd_self_test(args) -> int:
    import unittest

    root = Path(__file__).resolve().parents[1] / "tests"
    suite = unittest.TestLoader().discover(str(root) if root.is_dir() else "tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


# ---- parser ----


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ossd",
        description="open-ssd tools",
        epilog=(
            "exit codes: 0 ok, 1 argument/IO, 2 device open, 4 device error, "
            "5 verify mismatch, 6 refused. "
            "macOS: unmountDisk before vendor reads; replug afterwards."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sel = sub.add_parser("select", help="从原厂包与设备读数推导配置")
    sel.add_argument("--package", required=True)
    sel.add_argument("--ini")
    sel.add_argument("--rom-tag")
    sel.add_argument("--flash-id")
    sel.add_argument("--ce", type=int)
    sel.add_argument("--die-per-ce", type=int)
    sel.add_argument("--json", action="store_true")
    sel.set_defaults(func=_cmd_select)

    par = sub.add_parser("param", help="生成 DriveSetting 与 ParamTable")
    par_sub = par.add_subparsers(dest="param_command", required=True)
    build = par_sub.add_parser("build")
    build.add_argument("--package")
    build.add_argument("--set", dest="set_path", metavar="Flash.SET")
    build.add_argument("--part", required=True)
    build.add_argument("--template", required=True)
    build.add_argument("--matrix", required=True)
    build.add_argument("--internal", type=int, required=True)
    build.add_argument("--ch-mask", type=lambda v: int(v, 0))
    build.add_argument("--ce-mask", type=lambda v: int(v, 0))
    build.add_argument("--out-dir", required=True)
    build.set_defaults(func=_cmd_param_build)

    cid = sub.add_parser("cid", help="CID / LightSwitch 工具")
    cid_sub = cid.add_subparsers(dest="cid_command", required=True)
    ident = cid_sub.add_parser("identity")
    ident.add_argument("--base", required=True)
    ident.add_argument("--version")
    ident.add_argument("--serial")
    ident.add_argument("--model")
    ident.add_argument("--out", required=True)
    ident.set_defaults(func=_cmd_cid_identity)
    cmap = cid_sub.add_parser("map")
    cmap.add_argument("--base", required=True)
    cmap.add_argument("--csv", required=True)
    cmap.add_argument("--out", required=True)
    cmap.set_defaults(func=_cmd_cid_map)
    cbuild = cid_sub.add_parser("build")
    cbuild.add_argument("--base", required=True)
    cbuild.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    cbuild.add_argument("--out", required=True)
    cbuild.set_defaults(func=_cmd_cid_build)

    isp = sub.add_parser("isp", help="ISP 包")
    isp_sub = isp.add_subparsers(dest="isp_command", required=True)
    pkg = isp_sub.add_parser("package")
    pkg.add_argument("--core0", required=True)
    pkg.add_argument("--core1", required=True)
    pkg.add_argument("--lightswitch", required=True)
    pkg.add_argument("--manufacturer", required=True)
    pkg.add_argument("--out", required=True)
    pkg.set_defaults(func=_cmd_isp_package)

    bbt = sub.add_parser("bbt", help="Org 扫描坏块表")
    bbt_sub = bbt.add_subparsers(dest="bbt_command", required=True)
    bbuild = bbt_sub.add_parser("build")
    bbuild.add_argument("--scan", action="append", required=True)
    bbuild.add_argument("--param", required=True)
    bbuild.add_argument("--out", required=True)
    bbuild.add_argument("--policy", choices=bbt_gen.POLICIES, default="union")
    bbuild.add_argument("--erase", metavar="FILE")
    bbuild.set_defaults(func=_cmd_bbt_build)

    diff = sub.add_parser("diffaddr", help="替换表")
    diff_sub = diff.add_subparsers(dest="diff_command", required=True)
    dbuild = diff_sub.add_parser("build")
    dbuild.add_argument("--param", required=True)
    dbuild.add_argument("--drive", required=True)
    dbuild.add_argument("--bbt", required=True)
    dbuild.add_argument("--compact", required=True)
    dbuild.add_argument("--out", required=True)
    dbuild.set_defaults(func=_cmd_diffaddr_build)

    info = sub.add_parser("infoblock", help="InfoBlock")
    info_sub = info.add_subparsers(dest="infoblock_command", required=True)
    ibuild = info_sub.add_parser("build")
    for name in (
        "--param",
        "--boot",
        "--seed",
        "--org",
        "--erase",
        "--total",
        "--compact",
        "--diff",
        "--bank",
        "--out",
    ):
        ibuild.add_argument(name, required=True)
    ibuild.add_argument("--rdt")
    ibuild.add_argument("--oprom")
    ibuild.add_argument("--oprom-bytes", type=lambda v: int(v, 0))
    ibuild.add_argument("--total-bytes", type=lambda v: int(v, 0))
    ibuild.add_argument("--bank-part0-sectors", type=lambda v: int(v, 0), default=2048)
    ibuild.set_defaults(func=_cmd_infoblock_build)
    iframe = info_sub.add_parser("save-frame")
    iframe.add_argument("--param", required=True)
    iframe.add_argument("--info", required=True)
    iframe.add_argument("--typemap", required=True)
    iframe.add_argument("--out", required=True)
    iframe.add_argument("--fill-type", type=lambda v: int(v, 0), default=0xFF)
    iframe.set_defaults(func=_cmd_infoblock_save_frame)
    icmp = info_sub.add_parser("compare")
    icmp.add_argument("--info", required=True)
    icmp.add_argument("--reply0", required=True)
    icmp.add_argument("--reply1", required=True)
    icmp.set_defaults(func=_cmd_infoblock_compare)
    irun = info_sub.add_parser("save-run")
    irun.add_argument("--param", required=True)
    irun.add_argument("--info", required=True)
    irun.add_argument("--typemap", required=True)
    irun.add_argument("--out", required=True)
    irun.add_argument("--fill-type", type=lambda v: int(v, 0), default=0xFF)
    irun.add_argument("--dry-run", action="store_true")
    irun.set_defaults(func=_cmd_infoblock_save_run)

    lay = sub.add_parser("layout", help="系统块与容量")
    lay_sub = lay.add_subparsers(dest="layout_command", required=True)
    sysp = lay_sub.add_parser("system")
    sysp.add_argument("--param", required=True)
    sysp.add_argument("--bbt", required=True)
    sysp.add_argument("--limit", type=lambda v: int(v, 0), default=16)
    sysp.add_argument("--fill", action="store_true")
    sysp.add_argument("--out")
    sysp.set_defaults(func=_cmd_layout_system)
    capp = lay_sub.add_parser("capacity")
    capp.add_argument("--param", required=True)
    capp.add_argument("--drive", required=True)
    capp.add_argument("--system-blocks", type=lambda v: int(v, 0))
    capp.add_argument("--out", required=True)
    capp.set_defaults(func=_cmd_layout_capacity)

    mp = sub.add_parser("mpinfo", help="MPInfo")
    mp_sub = mp.add_subparsers(dest="mpinfo_command", required=True)
    mpb = mp_sub.add_parser("build")
    mpb.add_argument("--cid", required=True)
    mpb.add_argument("--seed", required=True)
    mpb.add_argument("--drive", required=True)
    mpb.add_argument("--typemap")
    mpb.add_argument("--cid-final")
    mpb.add_argument("--sn")
    mpb.add_argument("--model")
    mpb.add_argument("--nqn")
    mpb.add_argument("--version")
    mpb.add_argument("--time")
    mpb.add_argument("--counter", type=lambda v: int(v, 0), default=0)
    mpb.add_argument("--stats-a", type=lambda v: int(v, 0), default=0)
    mpb.add_argument("--stats-b", type=lambda v: int(v, 0), default=0)
    mpb.add_argument("--out", required=True)
    mpb.set_defaults(func=_cmd_mpinfo_build)
    mpi = mp_sub.add_parser("inspect")
    mpi.add_argument("--mpinfo", required=True)
    mpi.set_defaults(func=_cmd_mpinfo_inspect)
    mpw = mp_sub.add_parser("write")
    mpw.add_argument("--mpinfo", required=True)
    mpw.add_argument("--param", required=True)
    mpw.add_argument("--out", required=True)
    mpw.add_argument("--pages", type=lambda v: int(v, 0), default=0)
    mpw.set_defaults(func=_cmd_mpinfo_write)
    mpv = mp_sub.add_parser("verify")
    mpv.add_argument("--mpinfo", required=True)
    mpv.add_argument("--param", required=True)
    mpv.add_argument("--out", required=True)
    mpv.add_argument("--pages", type=lambda v: int(v, 0), default=0)
    mpv.set_defaults(func=_cmd_mpinfo_verify)
    mpd = mp_sub.add_parser("dump")
    mpd.add_argument("--param", required=True)
    mpd.add_argument("--out", required=True)
    mpd.add_argument("--page", type=lambda v: int(v, 0), default=0)
    mpd.add_argument("--index", type=lambda v: int(v, 0), default=0xFFFF)
    mpd.add_argument("--mode", type=lambda v: int(v, 0), default=-1)
    mpd.set_defaults(func=_cmd_mpinfo_dump)

    dev = sub.add_parser("dev", help="设备")
    dev_sub = dev.add_subparsers(dest="dev_command", required=True)
    dev_sub.add_parser("scan").set_defaults(func=_cmd_dev_scan)
    dev_sub.add_parser("probe").set_defaults(func=_cmd_dev_probe)
    rs = dev_sub.add_parser("reset")
    rs.set_defaults(func=_cmd_dev_reset)
    dev_sub.add_parser("usbreset").set_defaults(func=_cmd_dev_usbreset)
    gp = dev_sub.add_parser("gpio", help="桥 GPIO 只读查询（实验）")
    gp.add_argument("--selector", type=lambda v: int(v, 0), required=True)
    gp.add_argument(
        "--device-word",
        type=lambda v: int(v, 0),
        default=0x10000,
        help="device+19Ch value; default is vendor initializer",
    )
    gp.add_argument("--dry-run", action="store_true")
    gp.set_defaults(func=_cmd_dev_gpio)
    sc = dev_sub.add_parser("scsi", help="原始 SCSI CDB（脚手架）")
    sc.add_argument("--cdb", required=True, help="十六进制，最多 16 字节")
    sc.add_argument("--data-in", type=lambda v: int(v, 0))
    sc.add_argument("--data-out")
    sc.add_argument("--output-dir")
    sc.add_argument("--dry-run", action="store_true")
    sc.set_defaults(func=_cmd_dev_scsi)
    pt = dev_sub.add_parser("passthru")
    pt.add_argument("--opcode", type=lambda v: int(v, 0))
    pt.add_argument("--nsid", type=lambda v: int(v, 0))
    for cdw in range(10, 16):
        pt.add_argument(f"--cdw{cdw}", type=lambda v: int(v, 0))
    pt.add_argument("--sqe")
    pt.add_argument("--data-in", type=lambda v: int(v, 0))
    pt.add_argument("--data-out")
    pt.add_argument("--no-data", action="store_true")
    pt.add_argument("--output-dir")
    pt.add_argument("--vid", type=lambda v: int(v, 0))
    pt.add_argument("--pid", type=lambda v: int(v, 0))
    pt.add_argument("--serial")
    pt.add_argument("--timeout-ms", type=lambda v: int(v, 0))
    pt.add_argument("--trace", action="store_true")
    pt.add_argument("--recover-bot", action="store_true")
    pt.add_argument("--dry-run", action="store_true")
    pt.add_argument("--identify")
    pt.set_defaults(func=_cmd_dev_passthru)

    read = sub.add_parser("read", help="只读查询")
    read_sub = read.add_subparsers(dest="read_command", required=True)
    for name in ("flash-id", "rom", "mode", "drive-info"):
        entry = read_sub.add_parser(name)
        if name == "flash-id":
            entry.add_argument("--decode", metavar="FILE")
        elif name == "rom":
            entry.add_argument("--decode", nargs=2, metavar=("ROM", "MODE"))
        entry.set_defaults(func=_cmd_read)
    for name in ("controller", "namespace", "smart", "summary"):
        entry = read_sub.add_parser(name)
        entry.add_argument("--format", choices=("table", "json"), default="table")
        entry.add_argument("--out")
        entry.add_argument("--decode", metavar="FILE")
        entry.add_argument("--table", metavar="INI")
        if name == "namespace":
            entry.add_argument("--nsid", type=lambda v: int(v, 0), default=1)
        entry.set_defaults(func=_cmd_read, nsid=1)

    misp = sub.add_parser("mpisp", help="MPISP 镜像")
    misp_sub = misp.add_subparsers(dest="mpisp_command", required=True)
    mi = misp_sub.add_parser("inspect")
    mi.add_argument("file")
    mi.set_defaults(func=_cmd_mpisp)
    mp_prep = misp_sub.add_parser("prepare")
    mp_prep.add_argument("file")
    mp_prep.add_argument("--out", required=True)
    mp_prep.set_defaults(func=_cmd_mpisp)
    mu = misp_sub.add_parser("upload")
    mu.add_argument("file")
    mu.set_defaults(func=_cmd_mpisp)

    pre = sub.add_parser("pretest", help="Pretest 阶段")
    pre_sub = pre.add_subparsers(dest="pretest_command", required=True)
    cm = pre_sub.add_parser("card-mode")
    cm.add_argument("--param", required=True)
    cm.add_argument("--tail")
    cm.add_argument("--drive")
    cm.add_argument("--family", type=lambda v: int(v, 0), default=0)
    cm.add_argument("--page-number", type=lambda v: int(v, 0), default=0)
    cm.add_argument("--tables-dir", default="assets/SM2263XT_YMTC_TAS_PKGV0217A_FWV0126A/Tables")
    cm.add_argument("--stage", choices=("drive-builder", "early"), default="drive-builder")
    cm.add_argument("--out")
    cm.add_argument("--dry-run", action="store_true")
    cm.set_defaults(func=_cmd_pretest_card_mode)
    rtc = pre_sub.add_parser("tran-rtc")
    rtc.add_argument("--param", required=True)
    rtc.add_argument("--out")
    rtc.set_defaults(func=_cmd_pretest_tran_rtc)

    sp = pre_sub.add_parser("scan-profile")
    sp.add_argument("--drive", required=True)
    sp.add_argument("--pretest-option", type=lambda v: int(v, 0), default=0)
    sp.add_argument("--scan-bad-count", type=lambda v: int(v, 0), default=1)
    sp.add_argument("--show-scan-bad-count", action="store_true")
    sp.set_defaults(func=_cmd_pretest_scan_profile)
    sc = pre_sub.add_parser("scan-org")
    sc.add_argument("--drive")
    sc.add_argument("--total", type=lambda v: int(v, 0))
    sc.add_argument("--batch", type=lambda v: int(v, 0))
    sc.add_argument("--mode", type=lambda v: int(v, 0), default=0)
    sc.add_argument("--byte5", type=lambda v: int(v, 0), default=0)
    sc.add_argument("--byte6", type=lambda v: int(v, 0), default=0)
    sc.add_argument("--byte7", type=lambda v: int(v, 0), default=0)
    sc.add_argument(
        "--pages", type=lambda v: [int(x, 0) for x in v.split(",")], default=[0xFFFF] * 5
    )
    sc.add_argument(
        "--offsets", type=lambda v: [int(x, 0) for x in v.split(",")], default=[0xFFFF] * 7
    )
    sc.add_argument("--pretest-option", type=lambda v: int(v, 0), default=0)
    sc.add_argument("--scan-bad-count", type=lambda v: int(v, 0), default=1)
    sc.add_argument("--show-scan-bad-count", action="store_true")
    sc.add_argument("--result-dir", required=True)
    sc.set_defaults(func=_cmd_pretest_scan_org)
    er = pre_sub.add_parser("erase-run")
    er.add_argument("--param", required=True)
    er.add_argument("--drive", required=True)
    er.add_argument("--bbt", required=True)
    er.add_argument("--out", required=True)
    er.add_argument("--pretest-option", type=lambda v: int(v, 0), default=0)
    er.add_argument("--do-not-erase-bad", type=lambda v: int(v, 0), default=0)
    er.add_argument("--max-batches", type=lambda v: int(v, 0), default=0)
    er.set_defaults(func=_cmd_pretest_erase_run)
    ef = pre_sub.add_parser("erase-frame")
    ef.add_argument("--drive", required=True)
    ef.add_argument("--bbt", required=True)
    ef.add_argument("--out", required=True)
    ef.add_argument("--pretest-option", type=lambda v: int(v, 0), default=0)
    ef.add_argument("--do-not-erase-bad", type=lambda v: int(v, 0), default=0)
    ef.set_defaults(func=_cmd_pretest_erase_frame)
    pf = pre_sub.add_parser("probe-frame")
    pf.add_argument("--param", required=True)
    pf.add_argument("--index", type=lambda v: int(v, 0), required=True)
    pf.add_argument("--sum-sectors", type=lambda v: int(v, 0))
    pf.add_argument("--out", required=True)
    pf.set_defaults(func=_cmd_pretest_probe_frame)
    pr = pre_sub.add_parser("probe-run")
    pr.add_argument("--param", required=True)
    pr.add_argument("--index", type=lambda v: int(v, 0), required=True)
    pr.add_argument("--sum-sectors", type=lambda v: int(v, 0))
    pr.add_argument("--out", required=True)
    pr.set_defaults(func=_cmd_pretest_probe_run)
    cn = pre_sub.add_parser("connectivity")
    cn.add_argument("--drive", required=True)
    cn.add_argument("--out", required=True)
    cn.set_defaults(func=_cmd_pretest_connectivity)

    st = sub.add_parser("self-test", help="运行内置检查")
    st.set_defaults(func=_cmd_self_test)

    op = sub.add_parser("open", help="一条命令完成开卡（原厂 Step0..Step7）")
    op.add_argument("--package", required=True)
    op.add_argument("--part", required=True, help="Flash.SET 行名（本盘是 A2 的全名）")
    op.add_argument("--work", required=True, help="工作目录")
    op.add_argument("--template")
    op.add_argument("--rdt", help="RDT 结果；没有则 InfoBlock 少 10 页")
    op.add_argument("--matrix")
    op.add_argument("--internal", type=int)
    op.add_argument("--ch-mask", type=lambda v: int(v, 0))
    op.add_argument("--ce-mask", type=lambda v: int(v, 0))
    op.add_argument("--pretest-option", type=lambda v: int(v, 0), help="覆盖包内 PretestOption")
    op.add_argument("--scans", type=int, default=3)
    op.add_argument(
        "--probe", action="store_true", help="系统块逐个 probe（默认按原厂做法直接取前 8 个）"
    )
    op.add_argument("--dry-run", action="store_true")
    op.add_argument("--no-wait", action="store_true")
    op.add_argument("--timeout", type=int, default=60)
    op.add_argument("--sn", default="AA000000000000000002")
    op.add_argument("--model", default="SMI 2263XT")
    op.add_argument("--version", default="V0126A")
    op.add_argument("--nqn", default="nqn.2026-10.com.smi:nvm-subsystem-sn-AA000000000000000002")
    op.set_defaults(func=_cmd_open)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
