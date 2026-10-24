"""EzTool USB bridge commands (GPIO protocol applicability is unverified).

Protocol from docs/06-analysis/eztool-usb-gpio.md: a 1024B prepare packet with
CDB 3B/FF, then CDB 3C/FF returns 1024B whose first four bytes are "GPIO" and
byte +4 is the value. The selector is caller-supplied; no default is invented.
"""

from __future__ import annotations

from .transport import codec

PREPARE_CDB = bytes.fromhex("3bff0000000000040000")
READ_CDB = bytes.fromhex("3cff0100000000040000")
SIGNATURE = b"GPIO"
DEFAULT_DEVICE_WORD = 0x10000  # Original EXE's device+19Ch initializer.


class BridgeError(RuntimeError):
    pass


def prepare_payload(selector: int, device_word: int = DEFAULT_DEVICE_WORD) -> bytes:
    payload = bytearray(1024)
    payload[0x40:0x44] = (device_word & 0xFFFFFFFF).to_bytes(4, "little")
    payload[0x44] = selector & 0xFF
    return bytes(payload)


def gpio_read(target, selector: int, device_word: int = DEFAULT_DEVICE_WORD) -> int:
    result, accepted = target.transport.execute_cdb(
        PREPARE_CDB, codec.OUT, prepare_payload(selector, device_word), 1024
    )
    if not accepted or result.outcome != codec.CONFIRMED:
        raise BridgeError(f"prepare not confirmed (outcome={result.outcome})")

    result, accepted = target.transport.execute_cdb(READ_CDB, codec.IN, bytearray(1024), 1024)
    if not accepted or result.outcome != codec.CONFIRMED:
        raise BridgeError(f"read not confirmed (outcome={result.outcome})")
    data = result.payload[:1024]
    if data[:4] != SIGNATURE:
        raise BridgeError(f"bad signature {data[:4]!r}, expected 'GPIO'")
    return data[4]


def render(selector: int, value: int) -> str:
    return f"gpio selector={selector} value={value} (0x{value:02x})"
