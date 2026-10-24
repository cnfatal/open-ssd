"""Vendor EzTool field tables (M2): byte fields, strings, integers.

Only the syntax that the shipped tables actually use is implemented. Bit
groups (BitItem*) are reported as raw values, never guessed.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Table:
    unit_size: int
    total_units: int
    items: list


def load_table(path: str | Path) -> Table:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = lambda optionstr: optionstr
    parser.read(path, encoding="latin-1")
    setting = parser["Setting"] if parser.has_section("Setting") else {}
    unit = int(setting.get("UnitSize", "1"), 0)
    total = int(setting.get("TotalUnitNum", "0"), 0)
    items = []
    for name in parser.sections():
        if not name.startswith("Item_"):
            continue
        sec = parser[name]
        items.append(
            {
                "offset": int(sec.get("ItemUnitOffset", "0"), 0) * unit,
                "units": int(sec.get("ItemUnitNum", "1"), 0) * unit,
                "string": sec.get("ItemStringMode", "0").strip() == "1",
                "bits": int(sec.get("ItemBitEnable", "0"), 0),
                "desc": sec.get("ItemDesc", name).strip(),
            }
        )
    return Table(unit_size=unit, total_units=total, items=items)


def decode(data: bytes, table: Table) -> list[dict]:
    fields = []
    for item in table.items:
        start = item["offset"]
        end = start + item["units"]
        raw = data[start:end]
        if len(raw) != item["units"]:
            continue
        if item["string"]:
            value = raw.split(b"\0")[0].decode("latin-1").strip()
        elif item["bits"]:
            value = raw.hex()
        else:
            value = int.from_bytes(raw, "little")
        fields.append(
            {"name": item["desc"], "offset": start, "value": value, "string": item["string"]}
        )
    return fields


def render(fields: list[dict]) -> str:
    width = max((len(f["name"]) for f in fields), default=0)
    return "\n".join(f"{f['name']:<{width}}  {f['value']}" for f in fields)
