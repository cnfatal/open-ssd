"""USB ownership regression: return the driver detached by this Target."""

import unittest
from unittest.mock import Mock, patch

from ossd.transport import usb


@unittest.skipUnless(usb.HAVE_PYUSB, "pyusb not installed")
class OwnershipTest(unittest.TestCase):
    def make_target(self, detached):
        dev = Mock()
        identity = usb.Identity(usb.VID, usb.PID, 1, 2, 0x81, 2, 0, None)
        return usb.Target(dev, identity, detached=detached), dev

    def test_return_driver_after_release(self):
        target, dev = self.make_target(True)
        calls = []
        dev.attach_kernel_driver = Mock(side_effect=lambda _: calls.append("attach"))
        with (
            patch.object(
                usb.usb.util, "release_interface", side_effect=lambda *_: calls.append("release")
            ),
            patch.object(
                usb.usb.util, "dispose_resources", side_effect=lambda *_: calls.append("dispose")
            ),
        ):
            target.close()
        self.assertEqual(calls, ["release", "attach", "dispose"])
        self.assertFalse(target.detached)

    def test_leave_unowned_driver_alone(self):
        target, dev = self.make_target(False)
        with (
            patch.object(usb.usb.util, "release_interface"),
            patch.object(usb.usb.util, "dispose_resources"),
        ):
            target.close()
        dev.attach_kernel_driver.assert_not_called()

    def test_dispose_even_if_reattach_fails(self):
        target, dev = self.make_target(True)
        dev.attach_kernel_driver = Mock(side_effect=RuntimeError("attach failed"))
        with (
            patch.object(usb.usb.util, "release_interface"),
            patch.object(usb.usb.util, "dispose_resources") as dispose,
        ):
            with self.assertRaisesRegex(usb.UsbError, "attach failed"):
                target.close()
            dispose.assert_called_once_with(target.dev)

    def test_release_error_is_reported_after_remaining_cleanup(self):
        target, dev = self.make_target(True)
        with (
            patch.object(
                usb.usb.util, "release_interface", side_effect=RuntimeError("release failed")
            ),
            patch.object(usb.usb.util, "dispose_resources") as dispose,
        ):
            with self.assertRaisesRegex(usb.UsbError, "release failed"):
                target.close()
        dev.attach_kernel_driver.assert_called_once_with(0)
        dispose.assert_called_once_with(target.dev)
        self.assertEqual(target.release_result, -1)
        self.assertEqual(target.attach_result, 0)

    def test_failed_attach_retains_ownership_state(self):
        target, dev = self.make_target(True)
        dev.attach_kernel_driver = Mock(side_effect=RuntimeError("attach failed"))
        with (
            patch.object(usb.usb.util, "release_interface"),
            patch.object(usb.usb.util, "dispose_resources"),
        ):
            with self.assertRaises(usb.UsbError):
                target.close()
        self.assertTrue(target.detached)
        self.assertEqual(target.attach_result, -1)
