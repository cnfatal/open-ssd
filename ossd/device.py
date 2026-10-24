"""Device-facing flows: identity, reads, MPISP upload, C1/90, block writes."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from .generator import card_mode as card_mode_gen
from .generator import infoblock as ib
from .generator import mpinfo as mpinfo_gen
from .generator import mpisp, physical
from .generator import pretest_layout as layout
from .transport import bot, codec, policy
from .transport.usb import Target


class DeviceError(RuntimeError):
    pass


def _text(data: bytes, width: int) -> str:
    return policy.printable(data, width)


def identify(target: Target) -> bytes:
    data, _ = target.read(6, 1, 0, 0, 4096)
    vid = int.from_bytes(data[0:2], "little")
    print(f"NVMe VID: {vid:04x}")
    print(f"NVMe serial: {_text(data[4:24], 20)}")
    print(f"NVMe model: {_text(data[24:64], 40)}")
    print(f"NVMe firmware: {_text(data[64:72], 8)}")
    print(
        f"NVMe version: {int.from_bytes(data[80:84], 'little'):08x}; "
        f"namespaces: {int.from_bytes(data[516:520], 'little')}"
    )
    model = data[24:64]
    smi = b"SM2263" in model or b"SM2260" in model or b"SMI 2263" in model
    if not smi:
        raise DeviceError("unexpected identity; refusing SMI-specific follow-up")
    return data


def read_flash_id(target: Target) -> None:
    data, status = target.read(0xC2, 0x200, 0x40, 0, 2048)
    if status == 2:
        print("Flash-ID bytes are diagnostic candidates")
    print(f"Flash-ID controller field: {_text(data[0x1F0:], 32)}")
    banks, unknown = policy.decode_flash_id(data)
    for slot in unknown:
        print(f"Slot{slot:02d}: unrecognized prefix {data[0x30 + slot * 8]:02x}, excluded")
    for slot, chunk in banks:
        print(f"Bank{slot:02d}: " + " ".join(f"{b:02x}" for b in chunk))
    print(f"Candidate NAND banks: {len(banks)} (not a physical chip or die count)")
    if not banks:
        raise DeviceError("no candidate NAND bank")


def read_rom(target: Target) -> None:
    rom, a1 = target.read(0xC2, 0x80, 0x52, 0x9FF0, 512)
    _, a2 = target.read(0xC2, 0x80, 0x88, 0, 512)
    mode, a3 = target.read(0xC2, 0x100, 0x87, 0, 1024)
    _, a4 = target.read(0xC2, 0x80, 0x88, 0, 512)
    branch = policy.rom_branch(rom)
    state = policy.run_mode(mode)
    print(f"ROM tag (first 16 bytes): {_text(rom, 16)}")
    print(
        f"Reviewed package branch: {branch or 'not recognized'}"
        f"{' (not a load instruction)' if branch else ''}"
    )
    print(f"DriveInfo raw mode byte: {mode[0x210]:02x}")
    print(f"DriveInfo mode label: {_text(mode[0x211:], 32)}")
    print(f"Run mode: {policy.MODE_NAMES[state]}")
    if branch is None:
        raise DeviceError(f"ROM tag unavailable in {policy.MODE_NAMES[state]} mode")
    if state == policy.MODE_UNKNOWN:
        raise DeviceError("unrecognized run mode")


def read_mode(target: Target) -> None:
    mode, a1 = target.read(0xC2, 0x100, 0x87, 0, 1024)
    _, a2 = target.read(0xC2, 0x80, 0x88, 0, 512)
    state = policy.run_mode(mode)
    print(f"DriveInfo raw mode byte: {mode[0x210]:02x}")
    print(f"DriveInfo mode label: {_text(mode[0x211:], 32)}")
    print(f"Run mode: {policy.MODE_NAMES[state]}")


def read_drive_info(target: Target) -> None:
    data, a1 = target.read(0xC2, 0x100, 0x87, 0, 1024)
    _, a2 = target.read(0xC2, 0x80, 0x88, 0, 512)
    state = policy.run_mode(data)
    print(
        f"type=0x{data[0x210]:02x} label={_text(data[0x211:], 32)} mode={policy.MODE_NAMES[state]}"
    )
    print("first 32 bytes:" + "".join(f" {b:02x}" for b in data[:32]))


# ---- MPISP upload ----


def upload(target: Target, image: bytes) -> None:
    prepared, info, code = mpisp.prepare(image)
    if code:
        raise DeviceError(f"prepare: {mpisp.error_text(code)}")
    count = mpisp.packet_count(len(prepared))
    preflight, _ = target.read(0xC2, 0x200, 0x40, 0, 2048)
    if preflight[4] in (1, 2):
        raise DeviceError(
            f"preflight byte4={preflight[4]:02x} needs a conditional C0 reset; not implemented"
        )
    for i in range(count):
        pkt, code = mpisp.packet(prepared, len(prepared), i)
        if code:
            raise DeviceError(f"packet {i}: {mpisp.error_text(code)}")
        result, accepted = target.transport.execute(
            pkt.sqe, codec.OUT, pkt.payload, pkt.transfer_bytes
        )
        if not accepted:
            raise DeviceError(f"packet {i}: rejected before submission")
        if result.outcome == codec.ACCEPTED_WITH_OUT_RESIDUE_QUIRK:
            print(f"packet {i + 1}/{count}: {pkt.transfer_bytes} bytes accepted with quirk")
        elif result.outcome != codec.CONFIRMED:
            data = result.phases[codec.DATA_PHASE]
            if (
                data.verdict.reason == codec.REASON_RESIDUE
                and data.observation.data_actual == pkt.transfer_bytes
            ):
                raise DeviceError(
                    f"packet {i}: full OUT with residue={data.verdict.residue}; write not confirmed"
                )
            raise DeviceError(
                f"packet {i}: {codec.OUTCOME_NAMES.get(result.outcome)} (fault={result.fault})"
            )
        else:
            print(f"packet {i + 1}/{count}: {pkt.transfer_bytes} bytes confirmed")

    mode, _ = target.read(0xC2, 0x100, 0x87, 0, 1024)
    target.read(0xC2, 0x80, 0x88, 0, 512)
    if mode[0x210:0x216] == b"\x01MPISP":
        print("mode: MPISP")
        return
    raise DeviceError("mode not confirmed after upload")


# ---- C1/90 SetCardMode ----


@dataclass
class CardModeResult:
    payload: bytes
    n512: int
    total: int
    ok: bool


def _save(out: Path | None, name: str, data: bytes) -> None:
    if out is None:
        return
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_bytes(data)


def _read_ok(result: bot.BotResult, size: int) -> bool:
    return bot.classify(result, size) in (bot.OK, bot.RESIDUE)


def _fetch(target: Target, sqe: bytes, size: int, label: str) -> bytes:
    result, accepted = target.transport.execute(sqe, codec.IN, bytearray(size), size)
    if not accepted:
        raise DeviceError(f"{label}: rejected before submission")
    if not _read_ok(result, size):
        data = result.phases[codec.DATA_PHASE]
        raise DeviceError(
            f"{label}: outcome={result.outcome} "
            f"fault={result.fault} actual="
            f"{data.observation.data_actual}"
        )
    return result.payload[:size]


def _status(target: Target) -> bytes:
    return _fetch(target, physical.debug_info_sqe(1), 512, "status")


def _status_ok(status: bytes, echo: int) -> bool:
    return (
        status[:13] == b"VNDRCMDBGINFO"
        and status[0x11] == 1
        and status[0x12] == 0
        and status[0x13] == echo
    )


def _submit_ok(result: bot.BotResult) -> bool:
    return result.outcome in (codec.CONFIRMED, codec.ACCEPTED_WITH_OUT_RESIDUE_QUIRK)


def card_mode(
    target: Target, param: bytes, tail: bytes | None, out: Path | None = None
) -> CardModeResult:
    payload, n512, total = card_mode_gen.build(param, tail)
    print(
        f"card-mode: param=1024 tail={len(tail or b'')} n512={n512} "
        f"total={total} cdw10=0x{n512 * 128:x}"
    )
    _save(out, "card-mode-payload.bin", payload)

    mode, _ = target.read(0xC2, 0x100, 0x87, 0, 1024)
    target.read(0xC2, 0x80, 0x88, 0, 512)
    if not (mode[0x210] == 1 and mode[0x211:0x216] == b"MPISP"):
        raise DeviceError("target is not in MPISP mode; load maintenance first")

    result, accepted = target.transport.execute(
        physical.card_mode_sqe(n512), codec.OUT, payload, total
    )
    if not accepted or not _submit_ok(result):
        raise DeviceError(f"C1/90 not confirmed (outcome={result.outcome} fault={result.fault})")

    status = _status(target)
    _save(out, "card-mode-status.bin", status)
    ack = _status_ok(status, 0x90) and int.from_bytes(status[0x20:0x24], "little") == 0x90
    print(
        f"card-mode ack: done={status[0x11]} error={status[0x12]} "
        f"cdw12=0x{status[0x13]:02x} "
        f"echo=0x{int.from_bytes(status[0x20:0x24], 'little'):08x}: "
        f"{'ok' if ack else 'unexpected'}"
    )
    verify_ok = _verify_card_mode(target, out, param, payload)
    return CardModeResult(payload, n512, total, ack and verify_ok)


def _first_set_bit(mask: int) -> int:
    for bit in range(8):
        if mask & (1 << bit):
            return bit
    return 0


def _verify_card_mode(target: Target, out: Path | None, param: bytes, payload: bytes) -> bool:
    bad = False
    info, _ = target.read(0xC2, 0x100, 0x87, 0, 1024)
    _save(out, "card-mode-drive-info.bin", info)
    _status(target)

    diff = next((i for i in range(256) if info[i] != param[i]), 256)
    print("readback P[0:256]: " + ("match" if diff == 256 else f"DIFF at 0x{diff:x}"))
    bad |= diff != 256

    tail = _fetch(target, physical.read_ram_sqe(9, 0x30100), 4608, "readback-tail")
    _save(out, "card-mode-tail-readback.bin", tail)
    diff = next((i for i in range(4608) if tail[i] != payload[1024 + i]), 4608)
    print("readback tail[0:4608]: " + ("match" if diff == 4608 else f"DIFF at 0x{diff:x}"))
    bad |= diff != 4608

    window = _fetch(target, physical.read_ram_sqe(1, 0x30000), 512, "readback-30000")
    _save(out, "card-mode-window-30000.bin", window)
    _status(target)
    window = _fetch(target, physical.read_ram_sqe(1, 0x30000), 512, "readback-30000b")
    diff = next((i for i in range(256) if window[i] != param[i]), 256)
    print(
        "readback 0x30000 P[0:256]: " + ("match" if diff == 256 else f"DIFF at 0x{diff:x}"), end=""
    )
    bad |= diff != 256
    diff = next((i for i in range(256) if window[256 + i] != payload[1024 + i]), 256)
    print(", tail[0:256]: " + ("match" if diff == 256 else f"DIFF at 0x{diff:x}"))
    bad |= diff != 256

    chmap = _fetch(target, physical.read_ram_sqe(1, 0x319D8), 512, "readback-map")
    _save(out, "card-mode-map.bin", chmap)
    _status(target)
    ch_count = sum(1 for i in range(4) if param[0x10] & (1 << i))
    ce_count = sum(1 for i in range(4) if param[0x11] & (1 << i))
    map_ok = ch_count <= 4 and ce_count <= 4
    for i in range(ch_count):
        if map_ok and chmap[i] != _first_set_bit(param[0x10] & ~((1 << i) - 1) & 0xFF):
            map_ok = False
    for i in range(ce_count):
        if map_ok and chmap[4 + i] != _first_set_bit(param[0x11] & ~((1 << i) - 1) & 0xFF):
            map_ok = False
    print(
        "readback CH map prefix:"
        + "".join(f" {chmap[i]}" for i in range(ch_count))
        + "; CE map prefix:"
        + "".join(f" {chmap[4 + i]}" for i in range(ce_count))
        + f": {'consistent' if map_ok else 'DIFF'}"
    )
    bad |= not map_ok

    ptr = _fetch(target, physical.read_ram_sqe(1, 0x31568), 512, "readback-ptr")
    _save(out, "card-mode-bank-ptr.bin", ptr)
    _status(target)
    expect = 0x51100000 | (_first_set_bit(param[0x10]) << 16)
    values = [int.from_bytes(ptr[i : i + 4], "little") for i in (0, 4, 8)]
    print(
        f"readback bank pointers: {values[0]:08x} {values[1]:08x} "
        f"{values[2]:08x} (expected {expect:08x}): "
        f"{'match' if all(v == expect for v in values) else 'DIFF'}"
    )
    bad |= any(v != expect for v in values)
    return not bad


def tran_rtc(target: Target, param: bytes, out: Path | None = None) -> bytes:
    """C2/8B is outside the reviewed read policy, so this uses a raw SQE."""
    sqe = bytearray(64)
    sqe[0] = 0xC2
    sqe[40:44] = (0x80).to_bytes(4, "little")
    sqe[48:52] = (0x8B).to_bytes(4, "little")
    data = _fetch(target, bytes(sqe), 512, "rtc")
    value = int.from_bytes(data[:2], "little")
    print(f"tran-rtc: LE16={value} (0x{value:03x})")
    if value > 0x1FF:
        print("tran-rtc: value above 0x1FF, P+6C left unchanged")
        return param
    updated = bytearray(param)
    updated[0x6C] = value & 0xFF
    updated[0x6D] = (value >> 8) & 0xFF
    print(f"tran-rtc: P[6C:6E] = {updated[0x6C]:02X} {updated[0x6D]:02X}")
    _save(out, "param-after-rtc.bin", bytes(updated))
    return bytes(updated)


# ---- InfoBlock save ----


def save_infoblock(
    target: Target,
    param: bytes,
    info: bytes,
    typemap: bytes,
    out: Path,
    fill_type: int = 0xFF,
    progress=print,
) -> tuple[int, int]:
    per_page = param[0x43]
    pages = int.from_bytes(param[0x48:0x4A], "little")
    if not per_page or len(info) % 512 or not pages:
        raise DeviceError("invalid P43/P48 or InfoBlock size")
    total_sectors = len(info) // 512
    k = (total_sectors + per_page - 1) // per_page
    if len(typemap) < k:
        raise DeviceError(f"typeMap needs at least {k} bytes")
    n512 = per_page + 1
    page_bytes = per_page * 512
    payload_bytes = n512 * 512
    host_sum = ib.sum32(info)
    progress(
        f"save-run: K={k} L={pages} n512={n512} host_sum=0x{host_sum:08x} fill=0x{fill_type:02x}"
    )

    mode, _ = target.read(0xC2, 0x100, 0x87, 0, 1024)
    target.read(0xC2, 0x80, 0x88, 0, 512)
    if not (mode[0x210] == 1 and mode[0x211:0x216] == b"MPISP"):
        raise DeviceError("target is not in MPISP mode")

    out.mkdir(parents=True, exist_ok=True)
    erases = writes = 0

    def erase(address) -> None:
        nonlocal erases
        result, accepted = target.transport.execute(ib.erase_sqe(address), codec.NONE, None, 0)
        if not accepted or not _submit_ok(result) or not _status_ok(_status(target), 0x03):
            raise DeviceError("erase failed")
        erases += 1

    def write_page(address, page: int, data: bytes) -> None:
        nonlocal writes
        sqe = ib.write_mode_sqe(address, page, n512, 0x95 if page < 4 else 0xC5)
        result, accepted = target.transport.execute(sqe, codec.OUT, data, payload_bytes)
        if not accepted or not _submit_ok(result) or not _status_ok(_status(target), 0x83):
            raise DeviceError(f"page {page} write failed")
        writes += 1

    for copy in range(2):
        address = layout.system_address(param, param[0x20 + copy])
        if address is None:
            raise DeviceError(f"copy {copy} decode failed")
        repeat = param[0x17] if param[0x0C] & 0x04 else 1
        repeat = repeat or 1
        for d in range(repeat):
            current = replace(address, die=address.die + d)
            erase(current)
            for page in range(pages):
                page_buf = bytearray(payload_bytes)
                if page < k:
                    page_buf[:page_bytes] = info[page * page_bytes : (page + 1) * page_bytes]
                type_byte = typemap[page] if page < k else fill_type
                page_buf[page_bytes : page_bytes + 512] = ib.spare_s1(
                    type_byte, page, current.plane
                )
                write_page(current, page, bytes(page_buf))
                if page % 64 == 0:
                    progress(f"copy{copy} die{d}: page {page}/{pages}")
        progress(f"copy{copy}: {pages} pages written")

    if param[0xD3] & 0x01:
        pos = (param[0x27] + 1) & 0xFF
        limit = int.from_bytes(param[0x30:0x32], "little") * (param[0x16] * param[0x13])
        guard = 0
        while pos < limit and guard < 256:
            guard += 1
            address = layout.system_address(param, pos)
            if address is None:
                raise DeviceError(f"extra block {pos} decode failed")
            erase(address)
            for page in range(pages):
                page_buf = bytearray(payload_bytes)
                page_buf[page_bytes : page_bytes + 512] = ib.spare_s2(page, address.plane)
                write_page(address, page, bytes(page_buf))
            pos = (pos + 1) & 0xFF

    address = layout.system_address(param, param[0x23])
    if address is None:
        raise DeviceError("idx decode failed")
    erase(address)
    idx = bytearray(payload_bytes)
    idx[page_bytes : page_bytes + 512] = ib.spare_idx(address.plane)
    write_page(address, 0, bytes(idx))

    return erases, writes


def infoblock_checksum(
    target: Target, param: bytes, info: bytes, out: Path | None = None, progress=print
) -> list[int]:
    per_page = param[0x43]
    n512 = per_page + 1
    k = (len(info) // 512 + per_page - 1) // per_page
    payload_bytes = n512 * 512
    host_sum = ib.sum32(info)
    device_sum = []
    for copy in range(2):
        # Valid ParamTable system entries decode to an address.
        address = cast(layout.SystemAddress, layout.system_address(param, param[0x20 + copy]))
        reply = _fetch(
            target, ib.checksum_sqe(address, k, n512, param[0x7B]), payload_bytes, "checksum"
        )
        if not _status_ok(_status(target), 0x82):
            raise DeviceError("checksum status not ok")
        if out:
            (out / f"copy{copy}-reply.bin").write_bytes(reply)
        device_sum.append(physical.checksum_reply_value(reply))
    progress(
        f"compare: host=0x{host_sum:08x} device0=0x{device_sum[0]:08x} "
        f"device1=0x{device_sum[1]:08x}: "
        f"{'match' if all(v == host_sum for v in device_sum) else 'MISMATCH'}"
    )
    return device_sum


# ---- MPInfo write / verify / dump ----


def mpinfo_write(
    target: Target, image: bytes, param: bytes, out: Path, max_pages: int = 0, progress=print
) -> None:
    if len(image) != mpinfo_gen.BYTES:
        raise DeviceError("mpinfo must be 8192 bytes")
    per_page = param[0x43]
    pages = int.from_bytes(param[0x48:0x4A], "little")
    if not per_page or not pages:
        raise DeviceError("invalid P43/P48")
    if max_pages and max_pages < pages:
        pages = max_pages
    n512 = per_page + 1
    payload_bytes = n512 * 512
    progress(f"mpinfo write: pages={pages} n512={n512}")
    out.mkdir(parents=True, exist_ok=True)

    mode, _ = target.read(0xC2, 0x100, 0x87, 0, 1024)
    target.read(0xC2, 0x80, 0x88, 0, 512)
    if not (mode[0x210] == 1 and mode[0x211:0x216] == b"MPISP"):
        raise DeviceError("target is not in MPISP mode")

    address = layout.system_address(param, param[0x22])
    if address is None:
        raise DeviceError("P22 decode failed")
    sqe = physical.erase_sqe(
        physical.PhysAddr(
            block=address.block,
            channel=address.ch,
            ce=address.ce,
            die=address.die,
            plane=address.plane | 0x80,
            mode=0x85,
        )
    )
    result, accepted = target.transport.execute(sqe, codec.NONE, None, 0)
    if not accepted or not _submit_ok(result) or not _status_ok(_status(target), 0x03):
        raise DeviceError("mpinfo erase failed")
    progress(
        f"mpinfo: block={address.block} plane={address.plane} "
        f"ch={address.ch} ce={address.ce} die={address.die}"
    )

    for page in range(pages):
        payload = mpinfo_gen.payload(image, n512, address.plane)
        sqe = physical.write_sqe(
            n512,
            physical.PhysAddr(
                block=address.block,
                page=page,
                channel=address.ch,
                ce=address.ce,
                die=address.die,
                plane=address.plane | 0x80,
                mode=0xC5,
            ),
        )
        result, accepted = target.transport.execute(sqe, codec.OUT, payload, payload_bytes)
        if not accepted or not _submit_ok(result) or not _status_ok(_status(target), 0x83):
            raise DeviceError(f"mpinfo page {page} failed")
        if page % 64 == 0:
            progress(f"mpinfo: page {page}/{pages}")
    progress(f"mpinfo: {pages} pages written")


def mpinfo_verify(target: Target, image: bytes, param: bytes, out: Path, max_pages: int = 0) -> int:
    if len(image) != mpinfo_gen.BYTES:
        raise DeviceError("mpinfo must be 8192 bytes")
    per_page = param[0x43]
    pages = int.from_bytes(param[0x48:0x4A], "little")
    if not per_page or not pages:
        raise DeviceError("invalid P43/P48")
    if max_pages and max_pages < pages:
        pages = max_pages
    expected = (sum(image) & 0xFFFFFFFF) * pages & 0xFFFFFFFF
    print(
        f"mpinfo verify: pages={pages} n512={per_page + 1} "
        f"page_bytes={per_page * 512} sum=0x{expected:08x}"
    )

    mode, _ = target.read(0xC2, 0x100, 0x87, 0, 1024)
    target.read(0xC2, 0x80, 0x88, 0, 512)
    if not (mode[0x210] == 1 and mode[0x211:0x216] == b"MPISP"):
        raise DeviceError("target is not in MPISP mode")
    address = layout.system_address(param, param[0x22])
    if address is None:
        raise DeviceError("P22 decode failed")
    sqe = ib.checksum_sqe(address, pages, per_page + 1, param[0x7B])
    reply = _fetch(target, sqe, 512, "mpinfo-checksum")
    if not _status_ok(_status(target), 0x82):
        raise DeviceError("mpinfo checksum status not ok")
    out.mkdir(parents=True, exist_ok=True)
    (out / "mpinfo-reply.bin").write_bytes(reply)
    device = physical.checksum_reply_value(reply)
    print(
        f"mpinfo verify: host=0x{expected:08x} device=0x{device:08x}: "
        f"{'match' if device == expected else 'MISMATCH'}"
    )
    return 0 if device == expected else 5


def mpinfo_dump(
    target: Target, param: bytes, out: Path, page: int = 0, index: int = 0xFFFF, mode: int = -1
) -> None:
    per_page = param[0x43]
    if not per_page:
        raise DeviceError("P43 is zero")
    payload_bytes = (per_page + 1) * 512
    if mode < 0:
        mode = 0x9D if page < param[0x7B] else 0xCD
    slot = index if index <= 0xFF else param[0x22]
    address = layout.system_address(param, slot)
    if address is None:
        raise DeviceError("address decode failed")
    sqe = physical.read_sqe(
        per_page + 1,
        physical.PhysAddr(
            block=address.block,
            page=page,
            channel=address.ch,
            ce=address.ce,
            die=address.die,
            plane=address.plane | 0x80,
            mode=mode,
        ),
    )
    buf = _fetch(target, sqe, payload_bytes, "mpinfo-dump")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"page-{page}.bin").write_bytes(buf)
    main = buf[: per_page * 512]
    print(
        f"mpinfo dump: block={address.block} plane={address.plane} "
        f"ch={address.ch} ce={address.ce} die={address.die}"
    )
    print(
        f"mpinfo dump: page={page} mode=0x{mode:02x} bytes={payload_bytes} "
        f"sum=0x{sum(main) & 0xFFFFFFFF:08x}"
    )
    print("mpinfo dump: head=" + "".join(f" {b:02x}" for b in buf[:16]))


def reset_controller(target: Target) -> None:
    result, accepted = target.transport.execute(physical.reset_sqe(), codec.NONE, None, 0)
    print(f"reset: outcome={result.outcome} fault={result.fault} (no CSW is expected)")
    time.sleep(0.2)


# ---- Org / erase scan ----


def _require_mpisp(target: Target) -> None:
    mode, _ = target.read(0xC2, 0x100, 0x87, 0, 1024)
    target.read(0xC2, 0x80, 0x88, 0, 512)
    if not (mode[0x210] == 1 and mode[0x211:0x216] == b"MPISP"):
        raise DeviceError("target is not in MPISP mode")


def scan_org(target: Target, derived, out: Path) -> int:
    from .generator import scan_profile

    if not derived.batch or not derived.nresult or derived.nresult > 0x7FFFFF:
        raise DeviceError("scan-org: R=0 or invalid result size")
    result_bytes = derived.nresult * 512
    if derived.nresult * 512 > 0xFFFF * 512:
        raise DeviceError("scan-org: result too large")
    print(
        f"scan-org: total={derived.total} batch={derived.batch} "
        f"batches={derived.batches} nresult={derived.nresult}"
    )
    _require_mpisp(target)
    out.mkdir(parents=True, exist_ok=True)

    fields = {
        "mode": derived.mode,
        "byte5": derived.byte5,
        "byte6": derived.byte6,
        "byte7": derived.byte7,
        "pages": derived.pages,
        "offsets": derived.offsets,
        "blocks_per_batch": derived.batch,
    }
    status = 0
    for i in range(derived.batches):
        first, last = scan_profile.batch_range(derived.total, derived.batch, i)
        if first >= derived.total:
            break
        descriptor = bytearray(512)
        _descriptor(descriptor, first, last, fields)
        (out / f"batch-{i:03d}-descriptor.bin").write_bytes(descriptor)

        result, accepted = target.transport.execute(
            physical.scan_org_submit_sqe(1), codec.OUT, bytes(descriptor), 512
        )
        if not accepted or not _submit_ok(result):
            raise DeviceError(f"batch {i}: org submit not confirmed")
        debug = _fetch(target, physical.debug_info_sqe(1), 512, f"batch {i} submit status")
        (out / f"batch-{i:03d}-submit-debug.bin").write_bytes(debug)
        data = _fetch(
            target, physical.scan_org_result_sqe(derived.nresult), result_bytes, f"batch {i} result"
        )
        debug = _fetch(target, physical.debug_info_sqe(1), 512, f"batch {i} result status")
        (out / f"batch-{i:03d}-result.bin").write_bytes(data)
        (out / f"batch-{i:03d}-result-debug.bin").write_bytes(debug)
        info = physical.scan_debug(debug)
        print(
            f"batch {i}: blocks {first}..{last} done={info['done']} "
            f"error=0x{info['error']:02x} fault={info['fault']}"
        )
        if info["done"] != 1 or info["error"]:
            raise DeviceError("scan stopped on device status")
        status = 0
    return status


def _descriptor(payload: bytearray, first: int, last: int, fields) -> None:
    payload[:] = bytes(512)
    payload[0:2] = first.to_bytes(2, "little")
    payload[2:4] = last.to_bytes(2, "little")
    payload[4] = fields["mode"] & 0xFF
    payload[5] = fields["byte5"] & 0xFF
    payload[6] = fields["byte6"] & 0xFF
    payload[7] = fields["byte7"] & 0xFF
    for i, value in enumerate(fields["pages"][:5]):
        payload[8 + i * 2 : 10 + i * 2] = (value & 0xFFFF).to_bytes(2, "little")
    for i, value in enumerate(fields["offsets"][:7]):
        payload[18 + i * 2 : 20 + i * 2] = (value & 0xFFFF).to_bytes(2, "little")
    payload[32:34] = (fields["blocks_per_batch"] & 0xFFFF).to_bytes(2, "little")


def erase_run(
    target: Target, drive: bytes, config, bbt: bytes, out: Path, max_batches: int = 0
) -> bytes:
    from .generator import scan_profile

    derived, rc = scan_profile.erase_derive(drive, config)
    if rc:
        raise DeviceError(f"erase-run: derivation failed ({rc})")
    if not derived.batch or not derived.nresult:
        raise DeviceError("erase-run: R=0 or R<8; nothing to erase")
    if len(bbt) < derived.total * 64:
        raise DeviceError("erase-run: bbt too small")
    result_bytes = derived.nresult * 512
    batches = derived.batches
    if max_batches and max_batches < batches:
        batches = max_batches
    print(
        f"erase-run: T={derived.total} R={derived.batch} mode={derived.mode} "
        f"batches={batches} nresult={derived.nresult}"
    )
    _require_mpisp(target)
    out.mkdir(parents=True, exist_ok=True)

    out_map = bytearray(derived.total * 64)
    for i in range(batches):
        first, last = scan_profile.batch_range(derived.total, derived.batch, i)
        chunk = bytearray(result_bytes)
        offset = first * 64
        take = min(result_bytes, max(0, len(bbt) - offset))
        chunk[:take] = bbt[offset : offset + take]
        (out / f"batch-{i:03d}-input.bin").write_bytes(chunk)

        result, accepted = target.transport.execute(
            physical.scan_erase_submit_sqe(derived.nresult), codec.OUT, bytes(chunk), result_bytes
        )
        if not accepted or not _submit_ok(result):
            raise DeviceError(f"batch {i}: C1/92 not confirmed")
        status = _status(target)
        (out / "status-92.bin").write_bytes(status)
        if not _status_ok(status, 0x92):
            raise DeviceError(f"batch {i}: erase status not ok")

        data = _fetch(
            target,
            physical.scan_erase_result_sqe(
                derived.nresult, first, last, derived.mode, derived.batch
            ),
            result_bytes,
            f"batch {i} result",
        )
        status = _status(target)
        (out / "status-83.bin").write_bytes(status)
        (out / f"batch-{i:03d}-result.bin").write_bytes(data)
        rows = last - first + 1
        if first * 64 + rows * 64 <= len(out_map):
            out_map[first * 64 : first * 64 + rows * 64] = data[: rows * 64]
        info = physical.scan_debug(status)
        print(f"batch {i}: blocks {first}..{last} done={info['done']} error=0x{info['error']:02x}")
        if info["done"] != 1 or info["error"]:
            raise DeviceError("erase stopped on device status")
    (out / "erase-result.bin").write_bytes(bytes(out_map))
    print(f"erase-run: {batches} batch(es) completed; result map {len(out_map)} bytes")
    return bytes(out_map)


# ---- probe ----


def probe_frame(param: bytes, index: int, out: Path, sum_sectors: int | None = None) -> None:
    from .generator import probe

    if sum_sectors is None:
        sum_sectors = param[0x43]
        if not sum_sectors:
            raise DeviceError("probe: P+43 is zero; pass --sum-sectors N")
    else:
        print(f"probe: provisional sum_sectors={sum_sectors} (override)")
    if sum_sectors == 0xFF:
        raise DeviceError("probe: P+43=FF makes n512 wrap")
    address = layout.system_address(param, index)
    if address is None:
        raise DeviceError("probe: candidate decode failed")
    built = probe.frames(
        address.block,
        address.plane,
        address.ch,
        address.ce,
        address.die,
        (sum_sectors + 1) & 0xFF,
        sum_sectors,
    )
    if built is None:
        raise DeviceError("probe: cannot build frames (zero geometry)")
    out.mkdir(parents=True, exist_ok=True)
    (out / "erase.bin").write_bytes(built.erase)
    (out / "checksum.bin").write_bytes(built.checksum)
    for page, sqe in enumerate(built.write):
        (out / f"write-{page:02d}.bin").write_bytes(sqe)
    print(
        f"probe: I={index} block={address.block} plane={address.plane} "
        f"ch={address.ch} ce={address.ce} die={address.die} "
        f"n512={(sum_sectors + 1) & 0xFF} sum_sectors={sum_sectors}"
    )
    print(
        f"erase:    op=c0 cdw12=0x{int.from_bytes(built.erase[48:52], 'little'):08x} "
        f"cdw13=0x{int.from_bytes(built.erase[52:56], 'little'):08x} "
        f"cdw14=0x{int.from_bytes(built.erase[56:60], 'little'):08x}"
    )
    print(
        f"write0:   op=c1 cdw10=0x{int.from_bytes(built.write[0][40:44], 'little'):08x} "
        f"cdw12=0x{int.from_bytes(built.write[0][48:52], 'little'):08x} "
        f"cdw13=0x{int.from_bytes(built.write[0][52:56], 'little'):08x}"
    )
    print(
        f"checksum: op=c2 cdw10=0x{int.from_bytes(built.checksum[40:44], 'little'):08x} "
        f"cdw12=0x{int.from_bytes(built.checksum[48:52], 'little'):08x} "
        f"cdw13=0x{int.from_bytes(built.checksum[52:56], 'little'):08x} "
        f"cdw14=0x{int.from_bytes(built.checksum[56:60], 'little'):08x}"
    )
    page_bytes = sum_sectors * 512
    host55 = (0x55 * page_bytes) & 0xFFFFFFFF
    print(
        f"host sum for one 0x55 page over {page_bytes} bytes = "
        f"0x{host55:08x}; 16 pages = 0x{(host55 * 16) & 0xFFFFFFFF:08x}"
    )
    (out / "geometry.txt").write_text(
        f"index={index}\nblock={address.block}\nplane={address.plane}\n"
        f"ch={address.ch}\nce={address.ce}\ndie={address.die}\n"
        f"n512={(sum_sectors + 1) & 0xFF}\nsum_sectors={sum_sectors}\n"
        f"host55_page=0x{host55:08x}\n"
        f"host55_16pages=0x{(host55 * 16) & 0xFFFFFFFF:08x}\n"
    )


def probe_run(
    target: Target, param: bytes, index: int, out: Path, sum_sectors: int | None = None
) -> None:
    if sum_sectors is None:
        sum_sectors = param[0x43]
        if not sum_sectors:
            raise DeviceError("probe: P+43 is zero; pass --sum-sectors N")
    if sum_sectors == 0xFF:
        raise DeviceError("probe: P+43=FF makes n512 wrap")
    address = layout.system_address(param, index)
    if address is None:
        raise DeviceError("probe: candidate decode failed")
    n512 = (sum_sectors + 1) & 0xFF
    _require_mpisp(target)
    out.mkdir(parents=True, exist_ok=True)
    geometry = physical.PhysAddr(
        block=address.block,
        plane=address.plane | 0x80,
        channel=address.ch,
        ce=address.ce,
        die=address.die,
        mode=0x84,
    )
    result, accepted = target.transport.execute(physical.erase_sqe(geometry), codec.NONE, None, 0)
    if not accepted or not _submit_ok(result) or not _status_ok(_status(target), 0x03):
        raise DeviceError("probe: erase not confirmed")

    page = bytearray(n512 * 512)
    page[: sum_sectors * 512] = b"\x55" * (sum_sectors * 512)
    for p in range(16):
        geometry.page = p
        geometry.mode = 0xC5
        result, accepted = target.transport.execute(
            physical.write_sqe(n512, geometry), codec.OUT, bytes(page), len(page)
        )
        if not accepted or not _submit_ok(result):
            raise DeviceError(f"probe: write {p} not confirmed")
    reply = _fetch(
        target,
        physical.checksum_query_sqe(
            n512, 16, address.block, address.plane, address.ch, address.ce, address.die, 0
        ),
        512,
        "probe-checksum",
    )
    (out / "checksum-reply.bin").write_bytes(reply)
    total = sum(b"\x55" * (sum_sectors * 512)) * 16 & 0xFFFFFFFF
    device = physical.checksum_reply_value(reply)
    print(
        f"probe: host=0x{total:08x} device=0x{device:08x}: "
        f"{'match' if device == total else 'MISMATCH'}"
    )
    if device != total:
        raise DeviceError("probe checksum MISMATCH")


# ---- connectivity ----


def connectivity(target: Target, drive: bytes, out: Path):
    from .generator import probe

    cdw13 = probe.connectivity_cdw13(drive)
    expected = bytes(drive[0x200 + 4 * i] for i in range(6))
    _require_mpisp(target)
    matrix = _fetch(target, physical.connectivity_sqe(2, cdw13), 1024, "connectivity")
    print(f"connectivity: C2/80 1024 bytes, cdw13=0x{cdw13:04x}")
    _status(target)
    ids, _ = target.read(0xC2, 0x200, 0x40, 0, 2048)
    status = _status(target)
    result = probe.connectivity_parse(matrix, ids, expected)
    nonzero = sum(1 for value in result.cell if value)
    matched = sum(1 for value in result.match if value)
    print(f"connectivity: {nonzero} nonempty cell(s), {matched} matching ID record(s)")
    print(" ch ce  cell  id                     match")
    for ch in range(4):
        for ce in range(4):
            record = ce * 4 + ch
            ident = result.id[record]
            print(
                f"  {ch}  {ce}  0x{result.cell[ch * 4 + ce]:02x}  "
                + " ".join(f"{b:02x}" for b in ident)
                + f"  {'yes' if result.match[record] else 'no'}"
            )
    out.mkdir(parents=True, exist_ok=True)
    (out / "connectivity-matrix.bin").write_bytes(matrix)
    (out / "connectivity-ids.bin").write_bytes(ids)
    (out / "connectivity-status.bin").write_bytes(status)
    return result
