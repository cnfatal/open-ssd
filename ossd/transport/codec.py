"""JMS583 vendor passthrough framing: three BOT phases per NVMe command.

Pure host codec. ``build_plan`` turns a 64-byte SQE into a CBW/data/CSW plan;
``check_stage`` and ``check_completion`` judge one observed phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CONTAINER_BYTES = 512
SQE_BYTES = 64
CDB_BYTES = 12
CBW_BYTES = 31
CSW_BYTES = 13
PHASE_COUNT = 3
MAX_PAYLOAD_BYTES = 0x00FFFFFF

NONE, IN, OUT = 0, 1, 2

COMMAND_PHASE, DATA_PHASE, COMPLETION_PHASE = 0, 1, 2

OK = 0
ARGUMENT = -1
UNSUPPORTED_SQE = -2
DIRECTION = -3
LENGTH = -4
TAG = -5
PHASE = -6

NOT_SUBMITTED = 0
CONFIRMED = 1
FAILED = 2
UNKNOWN = 3
ACCEPTED_WITH_OUT_RESIDUE_QUIRK = 4

REASON_NOT_SUBMITTED = 0
REASON_CONFIRMED = 1
REASON_CBW_IO = 2
REASON_CBW_LENGTH = 3
REASON_DATA_IO = 4
REASON_DATA_LENGTH = 5
REASON_CSW_IO = 6
REASON_CSW_LENGTH = 7
REASON_CSW_SIGNATURE = 8
REASON_CSW_TAG = 9
REASON_CSW_STATUS = 10
REASON_PHASE_ERROR = 11
REASON_COMMAND_FAILED = 12
REASON_RESIDUE_RANGE = 13
REASON_RESIDUE = 14
REASON_REPLY_LENGTH = 15
REASON_REPLY_SIGNATURE = 16
REASON_NVME_STATUS = 17

OUTCOME_NAMES = {
    NOT_SUBMITTED: "not-submitted",
    CONFIRMED: "confirmed",
    FAILED: "failed",
    UNKNOWN: "unknown",
    ACCEPTED_WITH_OUT_RESIDUE_QUIRK: "accepted-with-residue-quirk",
}

REASON_NAMES = {
    REASON_NOT_SUBMITTED: "not-submitted",
    REASON_CONFIRMED: "confirmed",
    REASON_CBW_IO: "cbw-io",
    REASON_CBW_LENGTH: "cbw-length",
    REASON_DATA_IO: "data-io",
    REASON_DATA_LENGTH: "data-length",
    REASON_CSW_IO: "csw-io",
    REASON_CSW_LENGTH: "csw-length",
    REASON_CSW_SIGNATURE: "csw-signature",
    REASON_CSW_TAG: "csw-tag",
    REASON_CSW_STATUS: "csw-status",
    REASON_PHASE_ERROR: "phase-error",
    REASON_COMMAND_FAILED: "command-failed",
    REASON_RESIDUE_RANGE: "residue-range",
    REASON_RESIDUE: "residue",
    REASON_REPLY_LENGTH: "reply-length",
    REASON_REPLY_SIGNATURE: "reply-signature",
    REASON_NVME_STATUS: "nvme-status",
}


@dataclass
class Phase:
    kind: int = COMMAND_PHASE
    direction: int = NONE
    length_bytes: int = 0
    tag: int = 0
    cdb: bytes = bytes(CDB_BYTES)
    cbw: bytes = bytes(CBW_BYTES)


@dataclass
class Plan:
    command: bytes = bytes(CONTAINER_BYTES)
    phases: list = field(default_factory=list)


@dataclass
class Observation:
    submitted: int = 0
    cbw_status: int = 0
    cbw_actual: int = 0
    data_status: int = 0
    data_actual: int = 0
    csw_status: int = 0
    csw_actual: int = 0
    csw: bytes = bytes(CSW_BYTES)


@dataclass
class Verdict:
    outcome: int = NOT_SUBMITTED
    reason: int = REASON_NOT_SUBMITTED
    residue: int = 0
    nvme_status: int = 0
    nvme_result: int = 0


def _le32(data: bytes, off: int = 0) -> int:
    return int.from_bytes(data[off : off + 4], "little")


def _make_phase(kind: int, direction: int, length: int, tag: int, protocol: int) -> Phase:
    cdb = bytearray(CDB_BYTES)
    cdb[0] = 0xA1
    cdb[1] = 0x80 | protocol
    cdb[3] = (length >> 16) & 0xFF
    cdb[4] = (length >> 8) & 0xFF
    cdb[5] = length & 0xFF
    cbw = bytearray(CBW_BYTES)
    cbw[0:4] = (0x43425355).to_bytes(4, "little")
    cbw[4:8] = (tag & 0xFFFFFFFF).to_bytes(4, "little")
    cbw[8:12] = (length & 0xFFFFFFFF).to_bytes(4, "little")
    cbw[12] = 0x80 if direction == IN else 0
    cbw[14] = CDB_BYTES
    cbw[15 : 15 + CDB_BYTES] = cdb
    return Phase(
        kind=kind, direction=direction, length_bytes=length, tag=tag, cdb=bytes(cdb), cbw=bytes(cbw)
    )


def build_plan(sqe: bytes, direction: int, payload_bytes: int, first_tag: int) -> tuple[Plan, int]:
    if direction not in (NONE, IN, OUT):
        return Plan(), DIRECTION
    if any(sqe[1:4]) or any(sqe[8:40]):
        return Plan(), UNSUPPORTED_SQE
    if payload_bytes > MAX_PAYLOAD_BYTES:
        return Plan(), LENGTH
    if direction == NONE and payload_bytes != 0:
        return Plan(), LENGTH
    if direction != NONE and payload_bytes == 0:
        return Plan(), LENGTH

    command = bytearray(CONTAINER_BYTES)
    command[0:4] = b"NVME"
    command[8 : 8 + SQE_BYTES] = sqe
    protocol = 1 if direction == NONE else 2 if direction == IN else 3
    plan = Plan(
        command=bytes(command),
        phases=[
            _make_phase(COMMAND_PHASE, OUT, CONTAINER_BYTES, first_tag, 0),
            _make_phase(DATA_PHASE, direction, payload_bytes, first_tag + 1, protocol),
            _make_phase(COMPLETION_PHASE, IN, CONTAINER_BYTES, first_tag + 2, 15),
        ],
    )
    return plan, OK


def check_stage(phase: Phase, obs: Observation) -> Verdict:
    v = Verdict(outcome=UNKNOWN, reason=REASON_CBW_IO)
    if not obs.submitted:
        v.outcome, v.reason = NOT_SUBMITTED, REASON_NOT_SUBMITTED
    elif obs.cbw_status:
        v.outcome, v.reason = UNKNOWN, REASON_CBW_IO
    elif obs.cbw_actual != CBW_BYTES:
        v.outcome, v.reason = UNKNOWN, REASON_CBW_LENGTH
    elif obs.csw_status:
        v.outcome, v.reason = UNKNOWN, REASON_CSW_IO
    elif obs.csw_actual != CSW_BYTES:
        v.outcome, v.reason = UNKNOWN, REASON_CSW_LENGTH
    elif _le32(obs.csw) != 0x53425355:
        v.outcome, v.reason = UNKNOWN, REASON_CSW_SIGNATURE
    elif _le32(obs.csw, 4) != (phase.tag & 0xFFFFFFFF):
        v.outcome, v.reason = UNKNOWN, REASON_CSW_TAG
    else:
        v.residue = _le32(obs.csw, 8)
        status = obs.csw[12]
        if status == 2:
            v.outcome, v.reason = UNKNOWN, REASON_PHASE_ERROR
        elif status > 2:
            v.outcome, v.reason = UNKNOWN, REASON_CSW_STATUS
        elif v.residue > phase.length_bytes:
            v.outcome, v.reason = UNKNOWN, REASON_RESIDUE_RANGE
        elif status == 1:
            v.outcome, v.reason = FAILED, REASON_COMMAND_FAILED
        elif obs.data_status:
            v.outcome, v.reason = UNKNOWN, REASON_DATA_IO
        elif obs.data_actual != phase.length_bytes:
            v.outcome, v.reason = UNKNOWN, REASON_DATA_LENGTH
        elif v.residue:
            v.outcome, v.reason = UNKNOWN, REASON_RESIDUE
        else:
            v.outcome, v.reason = CONFIRMED, REASON_CONFIRMED
    return v


def check_completion(
    phase: Phase, obs: Observation, reply: bytes | None, reply_bytes: int
) -> tuple[Verdict, int]:
    if phase.kind != COMPLETION_PHASE:
        return Verdict(), PHASE
    v = check_stage(phase, obs)
    if v.outcome == CONFIRMED:
        if reply is None:
            return v, ARGUMENT
        if reply_bytes != CONTAINER_BYTES or len(reply) < CONTAINER_BYTES:
            v.outcome, v.reason = UNKNOWN, REASON_REPLY_LENGTH
        elif reply[:4] != b"NVME":
            v.outcome, v.reason = UNKNOWN, REASON_REPLY_SIGNATURE
        else:
            v.nvme_result = _le32(reply, 8)
            v.nvme_status = _le32(reply, 20) >> 17
            if v.nvme_status:
                v.outcome, v.reason = FAILED, REASON_NVME_STATUS
    return v, OK


def build_cdb_plan(
    cdb: bytes, direction: int, payload_bytes: int, first_tag: int
) -> tuple[Plan, int]:
    """One native SCSI BOT transaction; CDB goes directly in the CBW."""
    if direction not in (NONE, IN, OUT):
        return Plan(), DIRECTION
    if not 1 <= len(cdb) <= 16:
        return Plan(), ARGUMENT
    if payload_bytes > MAX_PAYLOAD_BYTES:
        return Plan(), LENGTH
    if direction == NONE and payload_bytes != 0:
        return Plan(), LENGTH
    if direction != NONE and payload_bytes == 0:
        return Plan(), LENGTH
    cbw = bytearray(CBW_BYTES)
    cbw[:4] = b"USBC"
    cbw[4:8] = (first_tag & 0xFFFFFFFF).to_bytes(4, "little")
    cbw[8:12] = payload_bytes.to_bytes(4, "little")
    cbw[12] = 0x80 if direction == IN else 0
    cbw[14] = len(cdb)
    cbw[15 : 15 + len(cdb)] = cdb
    phase = Phase(
        direction=direction,
        length_bytes=payload_bytes,
        tag=first_tag,
        cdb=bytes(cdb),
        cbw=bytes(cbw),
    )
    return Plan(command=b"", phases=[phase]), OK
