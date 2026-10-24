"""`dev passthru`: one raw JMS583/NVMe admin request with a JSON journal."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .transport import bot, codec

MAX_PAYLOAD = codec.MAX_PAYLOAD_BYTES


class PassthruError(ValueError):
    pass


@dataclass
class Request:
    sqe: bytes = bytes(64)
    direction: int = codec.NONE
    payload: bytes = b""
    length: int = 0
    output: Path | None = None
    serial: str | None = None
    vid: int = 0x152D
    pid: int = 0x0583
    timeout_ms: int = 5000
    identify: bool = False
    recover: bool = False
    dry_run: bool = False
    trace: bool = False
    data_file: str | None = None


def from_namespace(a) -> Request:
    r = Request(
        vid=a.vid or 0x152D,
        pid=a.pid or 0x0583,
        timeout_ms=a.timeout_ms or 5000,
        serial=a.serial,
        output=Path(a.output_dir) if a.output_dir else None,
        identify=bool(a.identify),
        recover=a.recover_bot,
        dry_run=a.dry_run,
        trace=a.trace,
    )
    if sum(1 for v in (a.data_in, a.data_out, a.no_data) if v) != 1:
        raise PassthruError("需要且只能有一个数据方向")
    if a.identify:
        if a.opcode is not None or a.sqe or a.data_out:
            raise PassthruError("--identify 不能和 opcode/sqe/data-out 同用")
        sqe = bytearray(64)
        sqe[0], sqe[40] = 6, 1
        r.sqe, r.direction, r.length = bytes(sqe), codec.IN, 4096
    else:
        if a.sqe:
            if (
                any(getattr(a, f"cdw{i}", None) is not None for i in range(10, 16))
                or a.opcode is not None
                or a.nsid
            ):
                raise PassthruError("--sqe 不能和 opcode/NSID/CDW 同用")
            data = Path(a.sqe).read_bytes()
            if len(data) != 64:
                raise PassthruError("--sqe must be exactly 64 bytes")
            r.sqe = data
        else:
            if a.opcode is None:
                raise PassthruError("需要 --opcode 或 --sqe")
            if not 0 <= a.opcode <= 255:
                raise PassthruError("opcode 超出范围")
            sqe = bytearray(64)
            sqe[0] = a.opcode
            sqe[4:8] = ((a.nsid or 0) & 0xFFFFFFFF).to_bytes(4, "little")
            for i in range(10, 16):
                value = getattr(a, f"cdw{i}", None)
                if value is not None:
                    sqe[40 + (i - 10) * 4 : 44 + (i - 10) * 4] = (value & 0xFFFFFFFF).to_bytes(
                        4, "little"
                    )
            r.sqe = bytes(sqe)

        if a.data_in:
            if a.data_in <= 0 or a.data_in > MAX_PAYLOAD:
                raise PassthruError("--data-in 超出范围")
            r.direction, r.length = codec.IN, a.data_in
        elif a.data_out:
            data = Path(a.data_out).read_bytes()
            if not data or len(data) > MAX_PAYLOAD:
                raise PassthruError("--data-out 需要 1..0xffffff 字节")
            r.direction, r.payload, r.length = codec.OUT, data, len(data)
        else:
            r.direction, r.length = codec.NONE, 0

    if not r.dry_run and r.output is None:
        raise PassthruError("--output-dir is required")
    if r.serial is not None and not (0 < len(r.serial) < 32):
        raise PassthruError("serial must be 1..31 characters")
    _, code = codec.build_plan(r.sqe, r.direction, r.length, 1)
    if code:
        raise PassthruError(f"unsupported command fields/direction/length: codec={code}")
    return r


def dry_run(r: Request) -> str:
    plan, _ = codec.build_plan(r.sqe, r.direction, r.length, 1)
    return json.dumps(
        {
            "dry_run": True,
            "usb_opened": False,
            "direction": r.direction,
            "payload_bytes": r.length,
            "sqe_hex": r.sqe.hex(),
            "phases": [
                {
                    "cdb_hex": phase.cdb.hex(),
                    "bytes": phase.length_bytes,
                    "direction": phase.direction,
                }
                for phase in plan.phases
            ],
        },
        separators=(",", ":"),
    )


def _outcome_name(outcome: int) -> str:
    return {
        codec.NOT_SUBMITTED: "not_submitted",
        codec.CONFIRMED: "confirmed",
        codec.FAILED: "failed",
        codec.ACCEPTED_WITH_OUT_RESIDUE_QUIRK: "accepted_with_out_residue_quirk",
    }.get(outcome, "unknown")


def _report(
    request: Request,
    identity,
    execute_rc: int,
    result: bot.BotResult,
    recovery: dict,
    recovery_attempted: bool,
    open_result: int,
    release_result: int = 0,
    attach_result: int = 0,
    cleanup_error: str | None = None,
) -> dict:
    reply = len(result.reply) >= 512 and result.reply_actual == 512 and result.reply[:4] == b"NVME"
    return {
        "operation": "nvme-admin",
        "direction": request.direction,
        "requested": request.length,
        "open_result": open_result,
        "execute_rc": execute_rc,
        "outcome": result.outcome,
        "outcome_name": _outcome_name(result.outcome),
        "fault": result.fault,
        "actual": result.phases[codec.DATA_PHASE].observation.data_actual,
        "reply_actual": result.reply_actual,
        "serial": identity.serial if identity else None,
        "nvme_status": (int.from_bytes(result.reply[20:24], "little") >> 17 if reply else None),
        "nvme_result": (int.from_bytes(result.reply[8:12], "little") if reply else None),
        "phases": [
            {
                "index": i,
                "cbw_status": phase.observation.cbw_status,
                "cbw_actual": phase.observation.cbw_actual,
                "data_status": phase.observation.data_status,
                "data_actual": phase.observation.data_actual,
                "csw_status": phase.observation.csw_status,
                "csw_actual": phase.observation.csw_actual,
                "outcome": phase.verdict.outcome,
                "residue": phase.verdict.residue,
                "csw_hex": phase.observation.csw[:13].hex(),
            }
            for i, phase in enumerate(result.phases[: result.phases_started])
        ],
        "recovery_attempted": recovery_attempted,
        "recovery_outcome": recovery.get("outcome", codec.NOT_SUBMITTED),
        "release_result": release_result,
        "attach_result": attach_result,
        "cleanup_error": cleanup_error,
    }


def run(r: Request) -> int:
    from .transport.usb import Target, UsbError

    out = cast(Path, r.output)
    out.mkdir(parents=True, exist_ok=True)
    events = None
    if r.trace:
        events = (out / "events.jsonl").open("w")

    def log(event: bot.LogEvent) -> None:
        if events is None:
            return
        events.write(
            json.dumps(
                {
                    "kind": event.kind,
                    "phase": event.phase_index,
                    "tag": event.tag,
                    "endpoint": event.endpoint,
                    "status": event.io_status,
                    "actual": event.actual,
                    "requested": event.requested,
                    "cbw_hex": event.cbw.hex() if event.cbw else "",
                    "data_hex": event.data.hex() if event.data else "",
                }
            )
            + "\n"
        )

    execute_rc = -1
    exit_code = 2
    result = bot.BotResult()
    recovery = {"outcome": codec.NOT_SUBMITTED}
    recovery_attempted = False
    identity = None
    open_result = 0
    release_result = attach_result = 0
    cleanup_error = None
    try:
        target = Target.open(r.timeout_ms, log, r.vid, r.pid, r.serial)
    except Exception as exc:  # noqa: BLE001 - reported in result.json
        open_result = 1
        result.fault = bot.FAULT_IO
        print(f"open adapter: {exc}")
        target = None
    if target is not None:
        try:
            identity = target.identity
            payload = (
                bytearray(r.length)
                if r.direction == codec.IN
                else r.payload
                if r.direction == codec.OUT
                else None
            )
            result, accepted = target.transport.execute(r.sqe, r.direction, payload, r.length)
            execute_rc = 0 if accepted else -1
            exit_code = 0 if result.ok else 5
            if r.recover and not result.ok:
                recovery_attempted = True
                recovery = target.transport.recover()
            r.payload = bytes(payload) if payload is not None else b""
        finally:
            try:
                target.close()
            except UsbError as exc:
                cleanup_error = str(exc)
                exit_code = 3
            release_result = target.release_result
            attach_result = target.attach_result

    (out / "request.sqe.bin").write_bytes(r.sqe)
    if r.direction == codec.IN:
        n = min(result.phases[codec.DATA_PHASE].observation.data_actual, r.length)
        (out / "data-in.bin").write_bytes(r.payload[:n])
    (out / "completion.bin").write_bytes(result.reply[: min(result.reply_actual, 512)])
    if events is not None:
        events.close()
    report = _report(
        r,
        identity,
        execute_rc,
        result,
        recovery,
        recovery_attempted,
        open_result,
        release_result,
        attach_result,
        cleanup_error,
    )
    text = json.dumps(report, separators=(",", ":"))
    (out / "result.json").write_text(text + "\n")
    print(text)
    if r.direction == codec.OUT and result.outcome == codec.UNKNOWN:
        data = result.phases[codec.DATA_PHASE]
        if data.verdict.reason == codec.REASON_RESIDUE and data.observation.data_actual == r.length:
            print(
                f"note: OUT data arrived in full but "
                f"residue={data.verdict.residue}; the bridge reports no "
                "processed bytes, so this is not a confirmed write"
            )
    return exit_code
