"""Regression: GPIO uses native 10-byte SCSI CDBs, not A1 containers."""

import struct
import unittest
from types import SimpleNamespace

from ossd import bridge
from ossd.transport import bot, codec


class NativeIo(bot.Io):
    def __init__(self, fail=False):
        self.cbws = []
        self.writes = []
        self.fail = fail
        self.cdb = b""
        self.tag = 0

    def bulk(self, endpoint, data, length, timeout_ms):
        if not endpoint & 0x80:
            if length == 31 and data[:4] == b"USBC":
                self.cbws.append(bytes(data))
                self.tag = int.from_bytes(data[4:8], "little")
                self.cdb = bytes(data[15 : 15 + data[14]])
            else:
                self.writes.append(bytes(data[:length]))
            return bot.IO_OK, length
        if length == 13:
            data[:13] = b"USBS" + struct.pack("<II", self.tag, 0) + bytes([int(self.fail)])
        else:
            reply = bytearray(length)
            reply[:6] = b"GPIO\x80\xfe"
            data[:length] = reply
        return bot.IO_OK, length


class BridgeTest(unittest.TestCase):
    def test_native_gpio_read(self):
        io = NativeIo()
        target = SimpleNamespace(transport=bot.BotTransport(io, 0x81, 2, 1000))
        self.assertEqual(bridge.gpio_read(target, 2), 128)
        self.assertEqual(len(io.cbws), 2)
        self.assertEqual([b[14] for b in io.cbws], [10, 10])
        self.assertEqual(
            [b[15:25].hex() for b in io.cbws], ["3bff0000000000040000", "3cff0100000000040000"]
        )
        self.assertEqual([int.from_bytes(b[8:12], "little") for b in io.cbws], [1024, 1024])
        self.assertEqual([b[12] for b in io.cbws], [0, 0x80])
        self.assertEqual([int.from_bytes(b[4:8], "little") for b in io.cbws], [1, 2])
        expected = bytearray(1024)
        expected[0x40:0x44] = bytes.fromhex("00000100")
        expected[0x44] = 2
        self.assertEqual(io.writes, [bytes(expected)])

    def test_prepare_failure_does_not_read(self):
        io = NativeIo(fail=True)
        target = SimpleNamespace(transport=bot.BotTransport(io, 0x81, 2, 1000))
        with self.assertRaises(bridge.BridgeError):
            bridge.gpio_read(target, 2)
        self.assertEqual(len(io.cbws), 1)

    def test_override_device_word(self):
        self.assertEqual(
            bridge.prepare_payload(5, 0x12345678)[0x40:0x45], bytes.fromhex("7856341205")
        )

    def test_native_inquiry_has_no_nvme_completion(self):
        io = NativeIo()
        transport = bot.BotTransport(io, 0x81, 2, 1000)
        result, accepted = transport.execute_cdb(
            bytes.fromhex("120000002400"), codec.IN, bytearray(36), 36
        )
        self.assertTrue(accepted)
        self.assertEqual(result.outcome, codec.CONFIRMED)
        self.assertEqual(result.phases_started, 1)
        self.assertEqual(result.reply_actual, 0)
        self.assertEqual(len(result.payload), 36)
        self.assertEqual(io.cbws[0][14], 6)
        self.assertEqual(io.cbws[0][15], 0x12)


if __name__ == "__main__":
    unittest.main()
