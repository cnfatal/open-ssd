"""Minimal INI reader.

Vendor files are ANSI/CRLF with sections and ``key=value`` lines. We keep the
original key spelling (case sensitive) because the vendor tool matches keys
literally.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ini:
    path: str
    sections: dict[str, dict[str, str]] = field(default_factory=dict)

    def section(self, name: str) -> dict[str, str]:
        return self.sections.get(name, {})

    def get(self, section: str, key: str, default: str | None = None) -> str | None:
        return self.sections.get(section, {}).get(key, default)


def parse_ini(text: str, path: str = "<memory>") -> Ini:
    ini = Ini(path=path)
    current = ""
    ini.sections[""] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in ";#":
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            ini.sections.setdefault(current, {})
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        ini.sections.setdefault(current, {})[key.strip()] = value.strip()
    return ini


def load_ini(path: str) -> Ini:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return parse_ini(handle.read(), path)
