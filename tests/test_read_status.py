"""Complete data with a residue quirk must not turn mode reads into failures."""

import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ossd import device, info, passthru
from ossd.transport import bot, codec, usb


class ReadStatusTest(unittest.TestCase):
    def mode_target(self):
        mode = bytearray(1024)
        mode[0x210:0x214] = b"\x02ISP"
        target = Mock(spec=usb.Target)
        target.read.side_effect = [(bytes(mode), 2), (bytes(512), 2)]
        return target

    def test_mode_accepts_complete_diagnostic_data(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            device.read_mode(self.mode_target())
        self.assertIn("Run mode: ISP", output.getvalue())

    def test_drive_info_accepts_complete_diagnostic_data(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            device.read_drive_info(self.mode_target())
        self.assertIn("mode=ISP", output.getvalue())

    def result(self, completion):
        r = bot.BotResult(outcome=codec.UNKNOWN, payload=bytes(1024))
        r.phases[codec.COMMAND_PHASE].verdict.outcome = codec.CONFIRMED
        data = r.phases[codec.DATA_PHASE]
        data.verdict.reason = codec.REASON_RESIDUE
        data.observation.data_actual = 1024
        r.phases[codec.COMPLETION_PHASE].verdict.outcome = completion
        return r

    def test_residue_acceptance_requires_successful_completion(self):
        target = object.__new__(usb.Target)
        execute = Mock(return_value=(self.result(codec.NOT_SUBMITTED), True))
        target.transport = Mock(spec=bot.BotTransport, execute=execute)
        with self.assertRaises(usb.UsbError):
            target.execute(bytes(64), codec.IN, bytearray(1024), 1024)
        execute.return_value = (self.result(codec.CONFIRMED), True)
        data, status = target.execute(bytes(64), codec.IN, bytearray(1024), 1024)
        self.assertEqual(len(data), 1024)
        self.assertEqual(status, 2)


class TransactionAcceptanceTest(unittest.TestCase):
    def residue_result(self, completion=codec.CONFIRMED):
        r = bot.BotResult(outcome=codec.UNKNOWN, fault=bot.FAULT_STATUS, payload=bytes(512))
        r.phases[0].verdict.outcome = codec.CONFIRMED
        r.phases[1].verdict.reason = codec.REASON_RESIDUE
        r.phases[1].verdict.residue = 512
        r.phases[1].observation.data_actual = 512
        r.phases[2].verdict.outcome = completion
        return r

    def test_zero_data_is_valid_with_full_transaction_and_residue(self):
        r = self.residue_result()
        self.assertEqual(bot.classify(r, 512), bot.RESIDUE)
        target = SimpleNamespace(transport=SimpleNamespace(execute=Mock(return_value=(r, True))))
        self.assertEqual(info.read(target, "smart").data, bytes(512))

    def test_missing_or_failed_completion_is_not_accepted(self):
        for outcome in (codec.NOT_SUBMITTED, codec.UNKNOWN, codec.FAILED):
            with self.subTest(outcome=outcome):
                r = self.residue_result(outcome)
                target = SimpleNamespace(
                    transport=SimpleNamespace(execute=Mock(return_value=(r, True)))
                )
                self.assertEqual(bot.classify(r, 512), bot.FAILED_RESULT)
                with self.assertRaisesRegex(RuntimeError, "transaction incomplete"):
                    info.read(target, "smart")
        r = self.residue_result()
        r.phases[0].verdict.outcome = codec.UNKNOWN
        self.assertEqual(bot.classify(r, 512), bot.FAILED_RESULT)
        r.phases[0].verdict.outcome = codec.CONFIRMED
        r.phases[2].verdict.nvme_status = 2
        self.assertEqual(bot.classify(r, 512), bot.FAILED_RESULT)

    def test_accepted_out_does_not_exit_failure_or_recover(self):
        import tempfile
        from pathlib import Path

        result = bot.BotResult(outcome=codec.ACCEPTED_WITH_OUT_RESIDUE_QUIRK)
        transport = SimpleNamespace(execute=Mock(return_value=(result, True)), recover=Mock())
        target = SimpleNamespace(
            identity=None, transport=transport, close=Mock(), release_result=0, attach_result=0
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(usb.Target, "open", return_value=target),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            request = passthru.Request(
                direction=codec.OUT, payload=b"a", length=1, output=Path(tmp), recover=True
            )
            self.assertEqual(passthru.run(request), 0)
        transport.recover.assert_not_called()

    def test_cleanup_error_does_not_lose_completed_result(self):
        import json
        import tempfile
        from pathlib import Path

        result = bot.BotResult(outcome=codec.CONFIRMED)
        target = SimpleNamespace(
            identity=None,
            transport=SimpleNamespace(execute=Mock(return_value=(result, True))),
            close=Mock(side_effect=usb.UsbError("release failed")),
            release_result=-1,
            attach_result=0,
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(usb.Target, "open", return_value=target),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            request = passthru.Request(direction=codec.NONE, output=Path(tmp))
            self.assertEqual(passthru.run(request), 3)
            report = json.loads((Path(tmp) / "result.json").read_text())
            self.assertEqual(report["outcome"], codec.CONFIRMED)
            self.assertEqual(report["release_result"], -1)
            self.assertEqual(report["cleanup_error"], "release failed")
