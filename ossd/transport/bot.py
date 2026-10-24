"""BOT executor for JMS583 NVMe plans and native SCSI commands.

No implicit retries, no device selection. Every I/O failure is reported, not
retried; results record exactly what was observed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from . import codec

IO_OK = 0
IO_STALL = -1
IO_TIMEOUT = -2
IO_CANCELLED = -3
IO_ERROR = -4
IO_NO_DEVICE = -5
IO_NOT_ATTEMPTED = -6

LOG_BEFORE_PHASE = 0
LOG_CBW_RESULT = 1
LOG_DATA_RESULT = 2
LOG_CSW_RESULT = 3
LOG_BEFORE_CLEAR_HALT = 4
LOG_CLEAR_HALT_RESULT = 5
LOG_BEFORE_CLASS_RESET = 6
LOG_CLASS_RESET_RESULT = 7

FAULT_NONE = 0
FAULT_ARGUMENT = 1
FAULT_CANCELLED = 2
FAULT_TIMEOUT = 3
FAULT_IO = 4
FAULT_CODEC = 5
FAULT_STATUS = 6

FAULT_NAMES = {
    FAULT_NONE: "none",
    FAULT_ARGUMENT: "argument",
    FAULT_CANCELLED: "cancelled",
    FAULT_TIMEOUT: "timeout",
    FAULT_IO: "io",
    FAULT_CODEC: "codec",
    FAULT_STATUS: "status",
}


@dataclass
class LogEvent:
    kind: int = 0
    phase_index: int = 0
    tag: int = 0
    endpoint: int = 0
    timeout_ms: int = 0
    io_status: int = 0
    actual: int = 0
    requested: int = 0
    cbw: bytes | None = None
    data: bytes | None = None
    data_length: int = 0


class Io:
    """Transport callbacks. Subclasses implement bulk/clear_halt/class_reset."""

    def bulk(self, endpoint: int, data, length: int, timeout_ms: int) -> tuple[int, int]:
        raise NotImplementedError

    def clear_halt(self, endpoint: int, timeout_ms: int) -> int:
        raise NotImplementedError

    def class_reset(self, timeout_ms: int) -> int:
        raise NotImplementedError

    def cancel_requested(self) -> bool:
        return False

    def log(self, event: LogEvent) -> None:
        pass


@dataclass
class PhaseResult:
    observation: codec.Observation = field(default_factory=codec.Observation)
    verdict: codec.Verdict = field(default_factory=codec.Verdict)
    csw_reads: int = 0
    data_clear_status: int = IO_NOT_ATTEMPTED
    csw_clear_status: int = IO_NOT_ATTEMPTED
    first_csw_status: int = IO_NOT_ATTEMPTED
    first_csw_actual: int = 0
    first_csw: bytes = bytes(codec.CSW_BYTES)


@dataclass
class BotResult:
    plan: codec.Plan = field(default_factory=codec.Plan)
    phases: list[PhaseResult] = field(
        default_factory=lambda: [PhaseResult() for _ in range(codec.PHASE_COUNT)]
    )
    reply: bytes = bytes(codec.CONTAINER_BYTES)
    reply_actual: int = 0
    payload: bytes = b""
    active_phase: int = codec.PHASE_COUNT
    phases_started: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    bulk_calls: int = 0
    clear_halt_calls: int = 0
    outcome: int = codec.NOT_SUBMITTED
    fault: int = FAULT_NONE
    codec_result: int = 0
    cancelled: int = 0
    timed_out: int = 0

    @property
    def ok(self) -> bool:
        return self.outcome in (codec.CONFIRMED, codec.ACCEPTED_WITH_OUT_RESIDUE_QUIRK)


class _Run:
    def __init__(self, transport: BotTransport, result: BotResult):
        self.transport = transport
        self.result = result
        self.phase = 0
        self.tag = 0
        self.fault = FAULT_NONE
        self.cancelled = 0
        self.timed_out = 0


class BotTransport:
    def __init__(
        self,
        io: Io,
        ep_in: int,
        ep_out: int,
        timeout_ms: int,
        first_tag: int = 1,
        out_residue_quirk: bool = True,
    ):
        if not (ep_in & 0x80) or (ep_in & 0x70) or not (ep_in & 15):
            raise ValueError("invalid IN endpoint")
        if (ep_out & 0xF0) or not (ep_out & 15):
            raise ValueError("invalid OUT endpoint")
        if not timeout_ms:
            raise ValueError("timeout must be nonzero")
        self.io = io
        self.ep_in = ep_in
        self.ep_out = ep_out
        self.timeout_ms = timeout_ms
        self.next_tag = first_tag
        self.out_residue_quirk = bool(out_residue_quirk)

    # ---- helpers ----
    def _failure(self, run: _Run, status: int) -> None:
        run.fault = (
            FAULT_TIMEOUT
            if status == IO_TIMEOUT
            else FAULT_CANCELLED
            if status == IO_CANCELLED
            else FAULT_IO
        )
        run.timed_out = 1 if status == IO_TIMEOUT else 0
        run.cancelled = 1 if status == IO_CANCELLED else 0

    def _cancelled(self, run: _Run) -> bool:
        if self.io.cancel_requested():
            self._failure(run, IO_CANCELLED)
            return True
        return False

    def _record(
        self,
        run: _Run,
        kind: int,
        endpoint: int,
        status: int,
        actual: int,
        requested: int,
        cbw: bytes | None = None,
        data: bytes | None = None,
        data_length: int = 0,
    ) -> None:
        try:
            self.io.log(
                LogEvent(
                    kind=kind,
                    phase_index=run.phase,
                    tag=run.tag,
                    endpoint=endpoint,
                    timeout_ms=self.timeout_ms,
                    io_status=status,
                    actual=actual,
                    requested=requested,
                    cbw=cbw,
                    data=data,
                    data_length=data_length,
                )
            )
        except Exception:  # logging is best effort
            pass

    def _bulk(self, run: _Run, kind: int, endpoint: int, buffer, length: int) -> tuple[int, int]:
        status, actual = self.io.bulk(endpoint, buffer, length, self.timeout_ms)
        r = run.result
        r.bulk_calls += 1
        if endpoint & 0x80:
            r.bytes_in += actual
        else:
            r.bytes_out += actual
        visible = min(actual, length)
        self._record(
            run,
            kind,
            endpoint,
            status,
            actual,
            length,
            data=(bytes(buffer[:visible]) if endpoint & 0x80 and visible else None),
            data_length=(visible if endpoint & 0x80 else 0),
        )
        return status, actual

    def _control(self, run: _Run, reset: bool, endpoint: int) -> int:
        self._record(
            run,
            LOG_BEFORE_CLASS_RESET if reset else LOG_BEFORE_CLEAR_HALT,
            endpoint,
            IO_NOT_ATTEMPTED,
            0,
            0,
        )
        if reset:
            status = self.io.class_reset(self.timeout_ms)
        else:
            run.result.clear_halt_calls += 1
            status = self.io.clear_halt(endpoint, self.timeout_ms)
        self._record(
            run, LOG_CLASS_RESET_RESULT if reset else LOG_CLEAR_HALT_RESULT, endpoint, status, 0, 0
        )
        return status

    # ---- phases ----
    def _execute_phase(self, run: _Run, data) -> None:
        r = run.result
        phase = r.plan.phases[run.phase]
        pr = r.phases[run.phase]
        obs = pr.observation
        if self._cancelled(run):
            return
        self._record(
            run,
            LOG_BEFORE_PHASE,
            self.ep_out,
            IO_NOT_ATTEMPTED,
            0,
            phase.length_bytes,
            cbw=phase.cbw,
            data=(
                bytes(data)
                if phase.direction == codec.OUT and isinstance(data, (bytes, bytearray))
                else None
            ),
            data_length=(phase.length_bytes if phase.direction == codec.OUT else 0),
        )
        obs.submitted = 1
        r.phases_started += 1
        obs.data_status = IO_NOT_ATTEMPTED if phase.length_bytes else IO_OK
        obs.csw_status = IO_NOT_ATTEMPTED
        status, actual = self._bulk(run, LOG_CBW_RESULT, self.ep_out, phase.cbw, codec.CBW_BYTES)
        obs.cbw_status = status
        obs.cbw_actual = actual
        if status or actual != codec.CBW_BYTES:
            self._failure(run, status)
            return
        if phase.length_bytes:
            ep = self.ep_in if phase.direction == codec.IN else self.ep_out
            status, actual = self._bulk(run, LOG_DATA_RESULT, ep, data, phase.length_bytes)
            obs.data_status = status
            obs.data_actual = actual
            if run.phase == codec.COMPLETION_PHASE:
                r.reply_actual = actual
            if status == IO_STALL:
                pr.data_clear_status = self._control(run, False, ep)
                if pr.data_clear_status:
                    self._failure(run, pr.data_clear_status)
                    return
            elif status:
                self._failure(run, status)
                return
        for read in range(2):
            csw = bytearray(codec.CSW_BYTES)
            status, actual = self._bulk(run, LOG_CSW_RESULT, self.ep_in, csw, codec.CSW_BYTES)
            obs.csw = bytes(csw)
            obs.csw_status = status
            obs.csw_actual = actual
            pr.csw_reads += 1
            if not read:
                pr.first_csw_status = status
                pr.first_csw_actual = actual
                pr.first_csw = bytes(csw)
            if status == IO_STALL and not read:
                pr.csw_clear_status = self._control(run, False, self.ep_in)
                if pr.csw_clear_status:
                    self._failure(run, pr.csw_clear_status)
                    return
            else:
                if status:
                    self._failure(run, status)
                return

    def _check_phase(self, r: BotResult, index: int) -> int:
        pr = r.phases[index]
        pr.verdict = codec.check_stage(r.plan.phases[index], pr.observation)
        if index != codec.COMPLETION_PHASE:
            return codec.OK
        reply_obs = codec.Observation(**vars(pr.observation))
        residue_only = pr.verdict.reason == codec.REASON_RESIDUE
        residue = pr.verdict.residue
        if residue_only:
            reply_obs.csw = reply_obs.csw[:8] + b"\0\0\0\0" + reply_obs.csw[12:]
        verdict, code = codec.check_completion(
            r.plan.phases[index], reply_obs, r.reply, r.reply_actual
        )
        pr.verdict = verdict
        if residue_only:
            pr.verdict.residue = residue
            if pr.verdict.outcome == codec.CONFIRMED:
                pr.verdict.outcome = codec.UNKNOWN
                pr.verdict.reason = codec.REASON_RESIDUE
        return code

    def _quirk_matches(self, r: BotResult) -> bool:
        plan = r.plan.phases
        cmd, data, done = r.phases
        return (
            plan[codec.DATA_PHASE].direction == codec.OUT
            and cmd.verdict.outcome == codec.CONFIRMED
            and data.verdict.reason == codec.REASON_RESIDUE
            and data.observation.data_actual == plan[codec.DATA_PHASE].length_bytes
            and data.verdict.residue == plan[codec.DATA_PHASE].length_bytes
            and done.verdict.outcome == codec.CONFIRMED
            and done.verdict.nvme_status == 0
        )

    def execute(
        self,
        sqe: bytes,
        direction: int,
        payload: bytes | bytearray | None = None,
        payload_bytes: int = 0,
    ) -> tuple[BotResult, bool]:
        """Returns (result, accepted). ``payload`` is a bytearray for IN."""
        r = BotResult()
        for pr in r.phases:
            pr.data_clear_status = IO_NOT_ATTEMPTED
            pr.csw_clear_status = IO_NOT_ATTEMPTED
            pr.first_csw_status = IO_NOT_ATTEMPTED
        if direction == codec.NONE:
            if payload is not None:
                r.fault = FAULT_ARGUMENT
                return r, False
        elif payload is None:
            r.fault = FAULT_ARGUMENT
            return r, False

        plan, code = codec.build_plan(sqe, direction, payload_bytes, self.next_tag)
        if code:
            r.codec_result = code
            r.fault = FAULT_CODEC
            return r, False
        r.plan = plan
        self.next_tag = (self.next_tag + codec.PHASE_COUNT) & 0xFFFFFFFF

        run = _Run(self, r)
        residue_seen = False
        reply = bytearray(codec.CONTAINER_BYTES)
        for i in range(codec.PHASE_COUNT):
            run.phase = r.active_phase = i
            run.tag = r.plan.phases[i].tag
            if i == codec.COMMAND_PHASE:
                data = r.plan.command
            elif i == codec.COMPLETION_PHASE:
                data = reply
            else:
                data = payload if payload is not None else b""
            self._execute_phase(run, data)
            if i == codec.COMPLETION_PHASE:
                r.reply = bytes(reply)
            pr = r.phases[i]
            code = self._check_phase(r, i)
            if code:
                r.codec_result = code
                run.fault = FAULT_CODEC
            if run.fault:
                break
            residue_only = (
                i == codec.DATA_PHASE
                and pr.verdict.reason == codec.REASON_RESIDUE
                and pr.observation.data_actual == r.plan.phases[i].length_bytes
            )
            if residue_only:
                residue_seen = True
            elif pr.verdict.outcome != codec.CONFIRMED:
                run.fault = FAULT_STATUS
                break
            if i + 1 == codec.PHASE_COUNT:
                if not residue_seen:
                    r.outcome = codec.CONFIRMED
                elif self.out_residue_quirk and self._quirk_matches(r):
                    r.outcome = codec.ACCEPTED_WITH_OUT_RESIDUE_QUIRK
                else:
                    r.outcome = codec.UNKNOWN
                    run.fault = FAULT_STATUS
        r.fault = run.fault
        r.cancelled = run.cancelled
        r.timed_out = run.timed_out
        if (
            r.outcome not in (codec.CONFIRMED, codec.ACCEPTED_WITH_OUT_RESIDUE_QUIRK)
            and r.phases_started
        ):
            v = r.phases[r.active_phase].verdict
            r.outcome = (
                codec.FAILED
                if run.fault == FAULT_STATUS and v.outcome == codec.FAILED
                else codec.UNKNOWN
            )
        if direction == codec.IN:
            r.payload = bytes(cast(bytes | bytearray, payload))
        return r, True

    def execute_cdb(
        self,
        cdb: bytes,
        direction: int,
        payload: bytes | bytearray | None = None,
        payload_bytes: int = 0,
    ) -> tuple[BotResult, bool]:
        """Execute one native SCSI CBW/data/CSW, without NVMe framing."""
        r = BotResult()
        plan, code = codec.build_cdb_plan(cdb, direction, payload_bytes, self.next_tag)
        if code:
            r.codec_result, r.fault = code, FAULT_CODEC
            return r, False
        if (direction == codec.NONE and payload is not None) or (
            direction != codec.NONE and payload is None
        ):
            r.fault = FAULT_ARGUMENT
            return r, False
        r.plan = plan
        self.next_tag = (self.next_tag + 1) & 0xFFFFFFFF
        run = _Run(self, r)
        run.phase = r.active_phase = 0
        run.tag = plan.phases[0].tag
        self._execute_phase(run, payload)
        pr = r.phases[0]
        pr.verdict = codec.check_stage(plan.phases[0], pr.observation)
        r.outcome = pr.verdict.outcome
        r.fault = run.fault or (FAULT_NONE if r.outcome == codec.CONFIRMED else FAULT_STATUS)
        r.cancelled, r.timed_out = run.cancelled, run.timed_out
        if direction == codec.IN:
            r.payload = bytes(cast(bytes | bytearray, payload)[: pr.observation.data_actual])
        return r, True

    def recover(self) -> dict:
        result = {
            "steps_attempted": 0,
            "class_reset_status": IO_NOT_ATTEMPTED,
            "clear_in_status": IO_NOT_ATTEMPTED,
            "clear_out_status": IO_NOT_ATTEMPTED,
            "fault": FAULT_NONE,
            "cancelled": 0,
            "timed_out": 0,
            "outcome": codec.NOT_SUBMITTED,
        }
        run = _Run(self, BotResult())
        run.phase = codec.PHASE_COUNT
        for step in range(3):
            if self._cancelled(run):
                break
            endpoint = self.ep_in if step == 1 else self.ep_out if step == 2 else 0
            status = self._control(run, step == 0, endpoint)
            result["steps_attempted"] += 1
            key = (
                "class_reset_status"
                if step == 0
                else "clear_in_status"
                if step == 1
                else "clear_out_status"
            )
            result[key] = status
            if status:
                self._failure(run, status)
                break
        result["fault"] = run.fault
        result["cancelled"] = run.cancelled
        result["timed_out"] = run.timed_out
        result["outcome"] = (
            codec.CONFIRMED
            if result["steps_attempted"] == 3 and not run.fault
            else codec.UNKNOWN
            if result["steps_attempted"]
            else codec.NOT_SUBMITTED
        )
        return result


OK, RESIDUE, FAILED_RESULT = "ok", "residue", "failed"


def classify(result: BotResult, size: int) -> str:
    """Classify an NVMe transaction, preserving a completed payload's residue.

    Native SCSI commands use their single BOT verdict instead. Payload content
    does not establish whether a transfer completed.
    """
    if result.ok:
        return OK
    phase = result.phases[codec.DATA_PHASE]
    command = result.phases[codec.COMMAND_PHASE].verdict
    completion = result.phases[codec.COMPLETION_PHASE].verdict
    if (
        result.outcome == codec.UNKNOWN
        and phase.verdict.reason == codec.REASON_RESIDUE
        and phase.observation.data_actual == size
        and command.outcome == codec.CONFIRMED
        and completion.outcome == codec.CONFIRMED
        and completion.nvme_status == 0
    ):
        return RESIDUE
    return FAILED_RESULT
