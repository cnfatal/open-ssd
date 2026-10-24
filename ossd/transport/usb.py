"""pyusb adapter for the JMS583 bridge (152d:0583).

Thin layer: enumerate, claim the interface, and map pyusb results to the BOT
status codes. No retries and no device policy.
"""

from __future__ import annotations

import errno
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import usb.core
    import usb.util

    # PyUSB adds descriptor fields dynamically; its source types omit them.
    class Device(usb.core.Device):
        idVendor: int
        idProduct: int

    class Interface(usb.core.Interface):
        bInterfaceNumber: int

    class Endpoint(usb.core.Endpoint):
        bEndpointAddress: int


from . import bot, codec

VID = 0x152D
PID = 0x0583

try:  # pragma: no cover - exercised only with hardware present
    import usb.core
    import usb.util

    HAVE_PYUSB = True
except Exception:  # pragma: no cover
    HAVE_PYUSB = False


class UsbError(RuntimeError):
    pass


def _require() -> None:
    if not HAVE_PYUSB:
        raise UsbError("需要 PyUSB（uv sync --extra usb）")


@dataclass
class Identity:
    vid: int
    pid: int
    bus: int | None
    address: int | None
    endpoint_in: int
    endpoint_out: int
    interface: int
    serial: str | None


def _identity(dev: Device) -> Identity:
    try:
        cfg = cast("usb.core.Configuration", dev.get_active_configuration())
    except usb.core.USBError:
        cfg = cast("usb.core.Configuration", dev[0])
    intf = cast("Interface", cfg[(0, 0)])
    endpoints = [cast("Endpoint", ep) for ep in intf]
    ep_in = next(
        ep
        for ep in endpoints
        if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN
    )
    ep_out = next(
        ep
        for ep in endpoints
        if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_OUT
    )
    serial = None
    try:
        serial = dev.serial_number
    except (usb.core.USBError, ValueError):
        pass
    return Identity(
        vid=dev.idVendor,
        pid=dev.idProduct,
        bus=dev.bus,
        address=dev.address,
        endpoint_in=ep_in.bEndpointAddress,
        endpoint_out=ep_out.bEndpointAddress,
        interface=intf.bInterfaceNumber,
        serial=serial,
    )


def _devices(vid: int, pid: int) -> Iterator[Device]:
    _require()
    # PyUSB's unannotated find() returns an iterator when find_all=True.
    return cast("Iterator[Device]", usb.core.find(find_all=True, idVendor=vid, idProduct=pid))


def scan(vid: int = VID, pid: int = PID) -> list[Identity]:
    return [_identity(dev) for dev in _devices(vid, pid)]


def reset_bridge() -> int:
    """USB reset of the bridge; may re-enumerate without a replug."""
    for dev in _devices(VID, PID):
        try:
            dev.reset()
            return 0
        except usb.core.USBError as exc:
            raise UsbError(f"reset failed: {exc}") from exc
    raise UsbError(f"{VID:04x}:{PID:04x} not found")


class UsbIo(bot.Io):
    def __init__(
        self,
        dev: Device,
        interface: int,
        identity: Identity,
        log: Callable[[bot.LogEvent], None] | None = None,
    ):
        self.dev = dev
        self.interface = interface
        self.identity = identity
        self._log = log or (lambda event: None)

    def log(self, event: bot.LogEvent) -> None:
        self._log(event)

    def bulk(self, endpoint: int, data, length: int, timeout_ms: int) -> tuple[int, int]:
        try:
            if endpoint & 0x80:
                received = self.dev.read(endpoint, length, timeout=timeout_ms)
                data[: len(received)] = bytes(received)
                return bot.IO_OK, len(received)
            sent = self.dev.write(endpoint, data[:length], timeout=timeout_ms)
            return bot.IO_OK, sent
        except usb.core.USBTimeoutError:
            return bot.IO_TIMEOUT, 0
        except usb.core.USBError as exc:
            if exc.errno == errno.EPIPE:
                return bot.IO_STALL, 0
            if exc.errno in (errno.ENODEV, errno.ESHUTDOWN):
                return bot.IO_NO_DEVICE, 0
            return bot.IO_ERROR, 0
        except Exception:
            return bot.IO_ERROR, 0

    def clear_halt(self, endpoint: int, timeout_ms: int) -> int:
        try:
            self.dev.clear_halt(endpoint)
            return bot.IO_OK
        except usb.core.USBError as exc:
            return bot.IO_CANCELLED if exc.errno == errno.EINTR else bot.IO_ERROR

    def class_reset(self, timeout_ms: int) -> int:
        try:
            self.dev.ctrl_transfer(0x21, 0xFF, 0, self.interface, None, timeout_ms)
            return bot.IO_OK
        except usb.core.USBError as exc:
            return bot.IO_TIMEOUT if exc.errno == errno.ETIMEDOUT else bot.IO_ERROR


class Target:
    """Owns the claimed device and the BOT transport."""

    def __init__(
        self,
        dev: Device,
        identity: Identity,
        timeout_ms: int = 5000,
        log: Callable[[bot.LogEvent], None] | None = None,
        detached: bool = False,
    ):
        self.dev = dev
        self.identity = identity
        self.detached = detached
        self.release_result = 0
        self.attach_result = 0
        self.io = UsbIo(dev, identity.interface, identity, log)
        self.transport = bot.BotTransport(
            self.io,
            identity.endpoint_in,
            identity.endpoint_out,
            timeout_ms,
            first_tag=1,
            out_residue_quirk=True,
        )

    @classmethod
    def open(
        cls,
        timeout_ms: int = 5000,
        log: Callable[[bot.LogEvent], None] | None = None,
        vid: int = VID,
        pid: int = PID,
        serial: str | None = None,
    ) -> Target:
        candidates = list(_devices(vid, pid))
        if serial:

            def matches(dev: Device) -> bool:
                try:
                    return dev.serial_number == serial
                except (usb.core.USBError, ValueError):
                    return False

            candidates = [dev for dev in candidates if matches(dev)]
        if not candidates:
            raise UsbError(
                f"{vid:04x}:{pid:04x} " + (f"serial {serial!r} " if serial else "") + "not found"
            )
        dev = candidates[0]
        identity = _identity(dev)
        detached = False
        try:
            dev.set_configuration()
        except usb.core.USBError:
            pass
        try:
            if dev.is_kernel_driver_active(identity.interface):
                dev.detach_kernel_driver(identity.interface)
                detached = True
        except (NotImplementedError, usb.core.USBError):
            pass
        try:
            usb.util.claim_interface(dev, identity.interface)
        except usb.core.USBError as exc:
            if detached:
                dev.attach_kernel_driver(identity.interface)
            usb.util.dispose_resources(dev)
            raise UsbError(f"claim interface failed: {exc}") from exc
        return cls(dev, identity, timeout_ms, log, detached=detached)

    def close(self) -> None:
        """Attempt all cleanup; record release/attach results and raise on error."""
        self.release_result = 0
        self.attach_result = 0
        errors = []
        try:
            usb.util.release_interface(self.dev, self.identity.interface)
        except Exception as exc:
            self.release_result = -1
            errors.append(f"release interface: {exc}")
        if self.detached:
            try:
                self.dev.attach_kernel_driver(self.identity.interface)
                self.detached = False
            except Exception as exc:
                self.attach_result = -1
                errors.append(f"attach driver: {exc}")
        try:
            usb.util.dispose_resources(self.dev)
        except Exception as exc:
            errors.append(f"dispose resources: {exc}")
        if errors:
            raise UsbError("; ".join(errors))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    # ---- command helpers ----
    def read(self, opcode: int, cdw10: int, cdw12: int, cdw13: int, size: int) -> tuple[bytes, int]:
        from .policy import read_allowed

        if not read_allowed(opcode, cdw10, cdw12, cdw13, size):
            raise UsbError("request is outside the reviewed read policy")
        sqe = bytearray(64)
        sqe[0] = opcode
        sqe[40:44] = cdw10.to_bytes(4, "little")
        sqe[48:52] = cdw12.to_bytes(4, "little")
        sqe[52:56] = cdw13.to_bytes(4, "little")
        return self.execute(bytes(sqe), 1, bytearray(size), size)

    def execute(
        self, sqe: bytes, direction: int, payload=None, payload_bytes: int = 0
    ) -> tuple[bytes, int]:
        result, accepted = self.transport.execute(sqe, direction, payload, payload_bytes)
        if not accepted:
            raise UsbError("rejected before submission")
        kind = bot.classify(result, payload_bytes)
        if kind == bot.OK:
            return result.payload, result.outcome
        if kind == bot.RESIDUE:
            return result.payload, 2  # Historical diagnostic-read status.
        data_phase = result.phases[codec.DATA_PHASE]
        raise UsbError(
            f"{_outcome(result)} (reason={data_phase.verdict.reason}, fault={result.fault})"
        )


def _outcome(result) -> str:
    from . import codec

    return codec.OUTCOME_NAMES.get(result.outcome, "unknown")


def reset_device(target: Target) -> None:
    """Control-transfer reset of the controller, no CSW expected."""
    from ..generator import physical

    target.transport.execute(physical.reset_sqe(), 0, None, 0)
    time.sleep(0.2)
