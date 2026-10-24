"""CLI regressions at shared stage and rendering interfaces; no hardware I/O."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ossd import cli, device, info, stages


class CliTest(unittest.TestCase):
    def run_cli(self, args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            rc = cli.main(args)
        return rc, output.getvalue(), error.getvalue()

    def test_save_run_uses_shared_verification_and_fails_on_mismatch(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name)
            for file, data in [("param", bytes(1024)), ("info", b"\x01"), ("typemap", b"\x09")]:
                (p / file).write_bytes(data)
            context = contextlib.nullcontext(object())
            with (
                patch.object(cli, "_open_target", return_value=context),
                patch.object(stages, "save_infoblock_run", return_value=(3, 1537)) as save,
                patch.object(device, "infoblock_checksum", return_value=[2, 2]) as verify,
            ):
                rc, out, error = self.run_cli(
                    [
                        "infoblock",
                        "save-run",
                        "--param",
                        str(p / "param"),
                        "--info",
                        str(p / "info"),
                        "--typemap",
                        str(p / "typemap"),
                        "--out",
                        str(p / "out"),
                    ]
                )
            self.assertNotEqual(rc, 0)
            self.assertIn("checksum", error)
            self.assertEqual(save.call_count, 1)
            self.assertEqual(verify.call_count, 1)
            self.assertNotIn("save-run: erases=", out)

    def test_live_and_offline_single_read_share_json_shape(self):
        data = bytearray(4096)
        data[24:34] = b"SMI 2263XT"
        result = info.ReadResult(
            "controller", 1, b"", bytes(data), info.decode("controller", bytes(data))
        )
        with tempfile.TemporaryDirectory() as name:
            p = Path(name) / "controller.bin"
            p.write_bytes(data)
            offline_rc, offline, _ = self.run_cli(
                ["read", "controller", "--decode", str(p), "--format", "json"]
            )
            with (
                patch.object(cli, "_open_target", return_value=contextlib.nullcontext(object())),
                patch.object(info, "read", return_value=result),
            ):
                live_rc, live, _ = self.run_cli(["read", "controller", "--format", "json"])
            self.assertEqual((offline_rc, live_rc), (0, 0))
            self.assertIsInstance(json.loads(live), dict)
            self.assertEqual(json.loads(live), json.loads(offline))

    def test_summary_json_is_a_single_array(self):
        def read(_target, kind, _nsid):
            return info.ReadResult(kind, 1, b"", b"", [])

        with (
            patch.object(cli, "_open_target", return_value=contextlib.nullcontext(object())),
            patch.object(info, "read", side_effect=read),
        ):
            rc, out, error = self.run_cli(["read", "summary", "--format", "json"])
        self.assertEqual(rc, 0, error)
        self.assertEqual([r["kind"] for r in json.loads(out)], ["controller", "namespace", "smart"])

    def test_bbt_policy_is_forwarded(self):
        result = SimpleNamespace(
            summary={}, policy="intersect", total=1, bad_rows=0, bad_bits=0, counters=bytes(528)
        )
        with tempfile.TemporaryDirectory() as name:
            p = Path(name)
            (p / "param").write_bytes(bytes(1024))
            with (
                patch.object(stages, "build_bbt", return_value=result) as build,
                patch.object(stages, "save_bbt"),
            ):
                rc, _, error = self.run_cli(
                    [
                        "bbt",
                        "build",
                        "--param",
                        str(p / "param"),
                        "--scan",
                        str(p / "scan"),
                        "--policy",
                        "intersect",
                        "--out",
                        str(p / "out"),
                    ]
                )
            self.assertEqual(rc, 0, error)
            self.assertEqual(build.call_args.kwargs.get("policy"), "intersect")

    def test_open_defaults_leave_topology_and_pretest_to_runtime(self):
        args = cli.build_parser().parse_args(
            ["open", "--package", "p", "--part", "A2", "--work", "w"]
        )
        for name in ["matrix", "internal", "ch_mask", "ce_mask", "pretest_option"]:
            self.assertIsNone(getattr(args, name))
