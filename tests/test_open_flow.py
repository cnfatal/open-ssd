"""Run the opening pipeline with real generators and recorded scan input."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ossd import device, open_flow
from ossd.generator import infoblock

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "assets/SM2263XT_YMTC_TAS_PKGV0217A_FWV0126A"
SCAN = ROOT / "tmp/scan-org-a2"


@unittest.skipUnless(PKG.is_dir() and SCAN.is_dir(), "vendor/scan fixtures absent")
class OpeningTest(unittest.TestCase):
    def exercise(self, mismatch=False):
        target = MagicMock()
        target.__enter__.return_value = target
        uploaded = False

        def uploaded_now(*args):
            nonlocal uploaded
            uploaded = True

        def read(*args):
            if args[2] == 0x52:
                self.assertTrue(uploaded, "ROM memory is read through MPISP")
                return b"2263ROM:SVN02777".ljust(512, b"\0"), 0
            return bytes(1024), 0

        target.read.side_effect = read
        conn = SimpleNamespace(
            cell=list(bytes.fromhex("03000300030003000300030003000300")),
            id=[bytes.fromhex("9bc529492000")] * 16,
        )

        def scan(_target, _drive, out, **kw):
            for source in SCAN.glob("batch-*"):
                (out / source.name).write_bytes(source.read_bytes())

        def compare(_target, _param, info, _out):
            value = infoblock.sum32(info) + int(mismatch)
            return [value, value]

        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(open_flow.Target, "open", return_value=target))
            mocks = {}
            for name, kwargs in {
                "identify": {},
                "upload": {"side_effect": uploaded_now},
                "connectivity": {"return_value": conn},
                "card_mode": {"return_value": SimpleNamespace(ok=True)},
                "tran_rtc": {"side_effect": lambda t, p, out: p},
                "scan_org": {"side_effect": scan},
                "erase_run": {"return_value": bytes(0x8000)},
                "save_infoblock": {"return_value": (3, 1537)},
                "infoblock_checksum": {"side_effect": compare},
                "mpinfo_write": {},
                "mpinfo_verify": {"return_value": 0},
                "reset_controller": {},
            }.items():
                mocks[name] = stack.enter_context(patch.object(device, name, **kwargs))
            options = open_flow.OpenOptions(
                PKG, "A2", Path(tmp), scans=1, pretest_option=3, no_wait=True
            )
            if mismatch:
                with self.assertRaisesRegex(device.DeviceError, "MISMATCH"):
                    open_flow.run(options)
                mocks["mpinfo_write"].assert_not_called()
                mocks["reset_controller"].assert_not_called()
            else:
                self.assertEqual(open_flow.run(options), 0)
                self.assertTrue((Path(tmp) / "ib/infoblock.bin").is_file())
                image = (Path(tmp) / "mpinfo/mpinfo.bin").read_bytes()
                drive = (Path(tmp) / "p1/drive.bin").read_bytes()
                self.assertEqual(len(image), 8192)
                self.assertEqual(image[0x1400:0x1800], drive[:1024])
                self.assertEqual(image[0x1280:0x1284], bytes.fromhex("6f126322"))
                mocks["reset_controller"].assert_called_once()

    def test_real_generators_reach_persistence_and_reset(self):
        self.exercise()

    def test_failed_compare_stops_before_mpinfo_and_reset(self):
        self.exercise(mismatch=True)
