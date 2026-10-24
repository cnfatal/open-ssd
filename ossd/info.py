"""Standard NVMe / SMI information queries (M1).

Only decodes the fields the design report lists; the vendor INI tables are M2.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .transport import bot, codec

KINDS = {
    "controller": (0x06, 0, 0x01, 4096),
    "namespace": (0x06, 1, 0x00, 4096),
    "smart": (0x02, 0xFFFFFFFF, 0x007F0002, 512),
}


@dataclass
class ReadResult:
    kind: str
    nsid: int
    sqe: bytes
    data: bytes
    fields: list = field(default_factory=list)
    outcome: int = 0
    residue: int = 0
    nvme_status: int = 0


def _sqe(opcode: int, nsid: int, cdw10: int, size: int) -> bytes:
    sqe = bytearray(64)
    sqe[0] = opcode
    sqe[4:8] = (nsid & 0xFFFFFFFF).to_bytes(4, "little")
    # NVMe admin: CDW10 carries CNS / log id. The payload length lives in the
    # BOT data phase, not in the SQE (unlike the SMI vendor opcodes).
    sqe[40:44] = (cdw10 & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(sqe)


def _text(data: bytes | bytearray, off: int, width: int) -> str:
    return data[off : off + width].split(b"\0")[0].decode("latin-1").strip()


def _u(data: bytes | bytearray, off: int, width: int) -> int:
    return int.from_bytes(data[off : off + width], "little")


def decode(kind: str, data: bytes | bytearray, nsid: int = 1) -> list[dict]:
    out: list[dict] = []
    if kind == "controller":
        out = [
            {"name": "VID", "value": f"{_u(data, 0, 2):04x}", "offset": 0},
            {"name": "SSVID", "value": f"{_u(data, 2, 2):04x}", "offset": 2},
            {"name": "Serial", "value": _text(data, 4, 20), "offset": 4},
            {"name": "Model", "value": _text(data, 24, 40), "offset": 24},
            {"name": "Firmware", "value": _text(data, 64, 8), "offset": 64},
            {"name": "Namespaces", "value": _u(data, 516, 4), "offset": 516},
        ]
    elif kind == "namespace":
        flbas = data[26] & 0x0F
        lbads = data[128 + 4 * flbas + 2]
        lba = 1 << lbads
        nsze = _u(data, 0, 8)
        out = [
            {"name": "NSID", "value": nsid, "offset": None},
            {"name": "NSZE", "value": nsze, "offset": 0},
            {"name": "NCAP", "value": _u(data, 8, 8), "offset": 8},
            {"name": "NUSE", "value": _u(data, 16, 8), "offset": 16},
            {"name": "LBA size", "value": lba, "offset": None},
            {"name": "Capacity (B)", "value": nsze * lba, "offset": None},
        ]
    elif kind == "smart":
        out = [
            {"name": "Critical Warning", "value": data[0], "offset": 0},
            {"name": "Temperature (K)", "value": _u(data, 1, 2), "offset": 1},
            {"name": "Temperature (C)", "value": _u(data, 1, 2) - 273, "offset": 1},
            {"name": "Available Spare", "value": f"{data[3]}%", "offset": 3},
            {"name": "Percentage Used", "value": f"{data[5]}%", "offset": 5},
            {"name": "Data Units Read", "value": _u(data, 32, 16) * 512000, "offset": 32},
            {"name": "Data Units Written", "value": _u(data, 48, 16) * 512000, "offset": 48},
            {"name": "Power Cycles", "value": _u(data, 112, 16), "offset": 112},
            {"name": "Power On Hours", "value": _u(data, 128, 16), "offset": 128},
            {"name": "Unsafe Shutdowns", "value": _u(data, 144, 16), "offset": 144},
            {"name": "Media Errors", "value": _u(data, 160, 16), "offset": 160},
            {"name": "Error Log Entries", "value": _u(data, 176, 16), "offset": 176},
        ]
    else:
        raise ValueError(f"unknown kind: {kind}")
    return out


def read(target, kind: str, nsid: int = 1) -> ReadResult:
    opcode, fixed_nsid, cdw10, size = KINDS[kind]
    if kind == "namespace":
        fixed_nsid = nsid
    sqe = _sqe(opcode, fixed_nsid, cdw10, size)
    result, accepted = target.transport.execute(sqe, codec.IN, bytearray(size), size)
    if not accepted:
        raise RuntimeError(f"{kind}: rejected before submission")
    data = result.payload[:size]
    residue = result.phases[codec.DATA_PHASE].verdict.residue
    verdict_kind = bot.classify(result, size)
    if verdict_kind == bot.FAILED_RESULT:
        raise RuntimeError(
            f"{kind}: transaction incomplete or failed "
            f"(outcome={result.outcome}, fault={result.fault}, "
            f"residue={residue})"
        )
    verdict = result.phases[codec.COMPLETION_PHASE].verdict
    return ReadResult(
        kind=kind,
        nsid=nsid,
        sqe=sqe,
        data=data,
        fields=decode(kind, data, nsid) if len(data) == size else [],
        outcome=result.outcome,
        residue=residue,
        nvme_status=verdict.nvme_status,
    )


def as_dict(result: ReadResult) -> dict:
    return {
        "kind": result.kind,
        "nsid": result.nsid,
        "outcome": result.outcome,
        "residue": result.residue,
        "nvme_status": result.nvme_status,
        "fields": [
            {"name": f["name"], "value": f["value"], "offset": f["offset"]} for f in result.fields
        ],
    }


def render(result: ReadResult, fmt: str = "table") -> str:
    if fmt == "json":
        return json.dumps(as_dict(result), ensure_ascii=False, indent=2)
    width = max((len(f["name"]) for f in result.fields), default=0)
    lines = [f"{f['name']:<{width}}  {f['value']}" for f in result.fields]
    if result.residue:
        lines.append(f"note: data residue={result.residue}")
    return "\n".join(lines)


def save(result: ReadResult, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "request.sqe.bin").write_bytes(result.sqe)
    (out / "data.bin").write_bytes(result.data)
    (out / "fields.json").write_text(json.dumps(result.fields, indent=2))
    (out / "result.json").write_text(
        json.dumps(
            {
                "kind": result.kind,
                "nsid": result.nsid,
                "outcome": result.outcome,
                "residue": result.residue,
                "nvme_status": result.nvme_status,
            },
            indent=2,
        )
        + "\n"
    )
