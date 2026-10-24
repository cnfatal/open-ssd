"""Org-scan BBT assembly: reassemble batches, combine runs, count bad bits."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import pretest_layout as layout

POLICIES = ("union", "intersect", "majority")


class BbtError(RuntimeError):
    pass


@dataclass
class Run:
    directory: str
    map: bytearray
    bad_rows: int = 0
    bad_bits: int = 0
    batches: int = 0


def _le16(data: bytes | bytearray, off: int = 0) -> int:
    return data[off] | data[off + 1] << 8


def load_run(directory: str | Path, total: int) -> Run:
    directory = Path(directory)
    run = Run(directory=str(directory), map=bytearray(total * 64))
    index = 0
    while True:
        desc_path = directory / f"batch-{index:03d}-descriptor.bin"
        if not desc_path.exists():
            if index == 0:
                raise BbtError(f"{directory}: no batch descriptors")
            break
        desc = desc_path.read_bytes()
        if len(desc) < 34:
            raise BbtError(f"{directory} batch {index}: invalid descriptor")
        first = _le16(desc, 0)
        last = _le16(desc, 2)
        batch = _le16(desc, 32)
        if (
            not batch
            or batch % 8
            or first >= total
            or last >= total
            or last < first
            or last - first + 1 > batch
        ):
            raise BbtError(f"{directory} batch {index}: invalid descriptor")
        result_path = directory / f"batch-{index:03d}-result.bin"
        if not result_path.exists():
            raise BbtError(f"{directory} batch {index}: missing result")
        result = result_path.read_bytes()
        expect = (batch // 8) * 512
        if len(result) != expect or expect != batch * 64:
            raise BbtError(
                f"{directory} batch {index}: result {len(result)} bytes, expected {expect}"
            )
        rows = last - first + 1
        run.map[first * 64 : (first + rows) * 64] = result[: rows * 64]
        run.batches += 1
        index += 1
    run.bad_rows, run.bad_bits = tally(run.map, total)
    return run


def combine(maps, bytes_count: int, policy: str) -> bytes | None:
    if policy not in POLICIES or not maps or not bytes_count:
        return None
    out = bytearray(bytes_count)
    n = len(maps)
    for i in range(bytes_count):
        result = 0
        for bit in range(8):
            hits = sum((m[i] >> bit) & 1 for m in maps)
            if policy == "union":
                bad = hits != 0
            elif policy == "intersect":
                bad = hits == n
            else:
                bad = hits * 2 > n
            if bad:
                result |= 1 << bit
        out[i] = result
    return bytes(out)


def tally(bitmap: bytes | bytearray, rows: int) -> tuple[int, int]:
    row_count = bit_count = 0
    for row in range(rows):
        chunk = bitmap[row * 64 : (row + 1) * 64]
        if any(chunk):
            row_count += 1
        bit_count += sum(bin(b).count("1") for b in chunk)
    return row_count, bit_count


@dataclass
class BbtResult:
    org_combined: bytes = b""
    bbt: bytes = b""
    compact: bytes = b""
    counters: bytes = b""
    param_after: bytes = b""
    policy: str = "union"
    total: int = 0
    bad_rows: int = 0
    bad_bits: int = 0
    report: str = ""
    summary: dict = field(default_factory=dict)


def build(
    param: bytes | bytearray, scan_dirs, policy: str = "union", erase: bytes | None = None
) -> BbtResult:
    if policy not in POLICIES:
        raise BbtError(f"unknown policy {policy}")
    total = _le16(param, 0x32)
    if not total or total > layout.BAD_ROWS:
        raise BbtError(f"param: invalid row count {total}")

    runs = [load_run(d, total) for d in scan_dirs]
    merged = combine([r.map for r in runs], total * 64, policy)
    if merged is None:
        raise BbtError("combine failed")

    full = bytearray(layout.BAD_TABLE_BYTES)
    full[: total * 64] = merged
    zeros = bytes(layout.BAD_TABLE_BYTES)
    total_map = bytearray(layout.BAD_TABLE_BYTES)
    compact = bytearray(layout.SUMMARY_BYTES)
    counters = bytearray(layout.SUMMARY_BYTES)

    erase_table = (
        zeros
        if erase is None
        else erase.ljust(layout.BAD_TABLE_BYTES, b"\0")[: layout.BAD_TABLE_BYTES]
    )
    param_after = bytearray(param)
    if layout.merge_bad(
        param_after, full, erase_table, zeros, total_map, layout.BAD_TABLE_BYTES, compact
    ):
        raise BbtError("merge_bad failed")
    # Vendor snapshot: the table is org|erase (134 rows) while P+3E stays 18,
    # i.e. only the original scan's rows are counted for capacity.
    later_bad = layout.count_rows(full, total)
    param_after[0x3E] = later_bad & 0xFF
    param_after[0x3F] = (later_bad >> 8) & 0xFF
    if layout.count_bad(total_map, layout.BAD_TABLE_BYTES, counters):
        raise BbtError("count_bad failed")

    bad_rows, bad_bits = tally(bytes(total_map), total)
    result = BbtResult(
        org_combined=merged,
        bbt=bytes(total_map),
        compact=bytes(compact),
        counters=bytes(counters),
        param_after=bytes(param_after),
        policy=policy,
        total=total,
        bad_rows=bad_rows,
        bad_bits=bad_bits,
    )
    result.report, result.summary = _reports(runs, total, policy, counters)
    if erase is not None:
        result.report = (
            result.report.rstrip("\n") + f"\nlater_bad_rows={later_bad} (P+3E; org only)\n"
        )
        result.summary["later_bad_rows"] = later_bad
    return result


def _tally_for(runs, total: int, policy: str) -> tuple[int, int]:
    merged = combine([r.map for r in runs], total * 64, policy)
    if merged is None:
        return 0, 0
    return tally(merged, total)


def _reports(runs, total: int, policy: str, counters: bytes | bytearray):
    lines = ["Org scan BBT", f"policy: {policy}", f"runs: {len(runs)}", f"T: {total}"]
    for i, run in enumerate(runs):
        lines.append(
            f"run {i}: {run.directory} batches={run.batches} "
            f"bad_rows={run.bad_rows} bad_bits={run.bad_bits}"
        )
    for name in POLICIES:
        r, b = _tally_for(runs, total, name)
        lines.append(f"{name + ':':<10} bad_rows={r} bad_bits={b}")
    lines.append(f"counter totals: bits={_le16(counters, 0x200)} rows={_le16(counters, 0x202)}")
    lines.append("marginal rows (1..runs-1 hits):")
    marginal = []
    for row in range(total):
        hits = 0
        for run in runs:
            if any(run.map[row * 64 : (row + 1) * 64]):
                hits += 1
        if 0 < hits < len(runs):
            marginal.append({"row": row, "hits": hits})
            lines.append(f"  row {row}: {hits}/{len(runs)}")

    positions = []
    for ch in range(4):
        for ce in range(4):
            for die in range(8):
                for plane in range(4):
                    index = ch * 128 + ce * 32 + die * 4 + plane
                    if counters[index]:
                        positions.append(
                            {
                                "ch": ch,
                                "ce": ce,
                                "die": die,
                                "plane": plane,
                                "rows": counters[index],
                            }
                        )

    summary = {
        "policy": policy,
        "runs": len(runs),
        "total_fblocks": total,
        "per_run": [
            {
                "dir": r.directory,
                "batches": r.batches,
                "bad_rows": r.bad_rows,
                "bad_bits": r.bad_bits,
            }
            for r in runs
        ],
        "policies": {
            name: dict(zip(("bad_rows", "bad_bits"), _tally_for(runs, total, name)))
            for name in POLICIES
        },
        "counters": {"total_bits": _le16(counters, 0x200), "bad_rows": _le16(counters, 0x202)},
        "marginal": marginal,
        "positions": positions,
    }
    return "\n".join(lines) + "\n", summary


def summary_json(summary: dict) -> str:
    return json.dumps(summary, indent=2) + "\n"
