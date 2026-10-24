"""Flash.SET parser.

Mirrors the vendor table: a header such as ``[SM2263XT-DataBase-V0209]``, short
aliases (``A0=...``) and 69-column rows. Column 0..5 are the NAND ID; 15 is the
number of dies per CE and 16 the CE count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

COLUMNS = 69


def _is_hex_column(index: int) -> bool:
    return (
        index <= 5
        or index == 13
        or index == 18
        or index == 20
        or 22 <= index <= 27
        or 35 <= index <= 38
        or 42 <= index <= 45
        or 49 <= index <= 68
    )


def _parse_number(token: str, base: int) -> int:
    text = token
    if text[:2].lower() == "0x":
        base, text = 16, text[2:]
    elif text.startswith("$"):
        base, text = 16, text[1:]
    if not text:
        raise ValueError(f"empty number: {token!r}")
    return int(text, base)


@dataclass
class SetRow:
    name: str
    raw: str
    columns: list[int] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.columns)

    @property
    def flash_id(self) -> bytes:
        return bytes(self.columns[:6])

    @property
    def flash_id_text(self) -> str:
        return " ".join(f"{b:02x}" for b in self.flash_id)

    @property
    def die_per_ce(self) -> int:
        return self.columns[15]

    @property
    def ce_count(self) -> int:
        return self.columns[16]

    @property
    def channel_count(self) -> int:
        return self.columns[17]

    @property
    def page_size(self) -> int:
        return self.columns[7]

    @property
    def spare_bytes(self) -> int:
        return self.columns[8]

    @property
    def pages_per_block(self) -> int:
        return self.columns[10]

    @property
    def blocks_per_die(self) -> int:
        return self.columns[11]

    @property
    def flash_type(self) -> int:
        return self.columns[6]


@dataclass
class FlashSet:
    path: str
    header: str
    rows: dict[str, SetRow] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)

    def resolve(self, name: str) -> SetRow | None:
        if name in self.rows:
            return self.rows[name]
        target = self.aliases.get(name)
        return self.rows.get(target) if target else None

    def by_flash_id(self, flash_id: bytes) -> list[SetRow]:
        return [row for row in self.rows.values() if row.flash_id == flash_id]


_ALIAS = re.compile(r"^[A-Za-z]\d+$")


def parse_row(name: str, text: str) -> SetRow:
    row = SetRow(name=name, raw=text)
    for index, token in enumerate(t for t in re.split(r"[,\s]+", text.strip()) if t):
        if index >= COLUMNS:
            break
        row.columns.append(_parse_number(token, 16 if _is_hex_column(index) else 10))
    return row


def parse_flash_set(text: str, path: str = "<memory>") -> FlashSet:
    header = ""
    result = FlashSet(path=path, header=header)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            header = line[1:-1].strip()
            result.header = header
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if _ALIAS.match(key) and "," in value:
            result.aliases[key] = value
        elif "," in key:
            try:
                result.rows[key] = parse_row(key, value)
            except ValueError:
                # 模板行（ID0(H),...=H,H,...）不是真实数据，跳过
                continue
    return result


def load_flash_set(path: str) -> FlashSet:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return parse_flash_set(handle.read(), path)
