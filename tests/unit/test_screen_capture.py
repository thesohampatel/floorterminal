"""Offline coverage of native capture boundaries; no Pillow/display required."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.docs.screen_capture import capture_widget


class ScreenCaptureTests(unittest.TestCase):
    def setUp(self):
        self.widget = mock.Mock()
        for name, value in {
            "rootx": 10,
            "rooty": 20,
            "width": 800,
            "height": 480,
            "screenwidth": 1920,
            "screenheight": 1200,
        }.items():
            getattr(self.widget, "winfo_" + name).return_value = value
        self.image = mock.Mock(size=(800, 480), width=800, height=480)
        self.image.convert.return_value = self.image
        self.image.getextrema.return_value = [(0, 255)] * 3
        self.grab = mock.Mock()
        self.grab.grab.return_value = self.image
        self.module = mock.MagicMock()
        self.module.open.return_value.__enter__.return_value.copy.return_value = (
            self.image
        )

    def capture(self):
        return capture_widget(self.widget, self.grab, self.module)

    def test_x11_captures_only_the_widget(self):
        with mock.patch("scripts.docs.screen_capture.subprocess.run") as run:
            self.assertIs(self.capture(), self.image)
        self.grab.grab.assert_called_once_with(bbox=(10, 20, 810, 500))
        run.assert_not_called()

    def test_offscreen_widgets_never_capture_the_desktop(self):
        for name, value in (
            ("rootx", -1),
            ("rooty", -1),
            ("width", 2000),
            ("height", 0),
        ):
            with self.subTest(name=name):
                method = getattr(self.widget, "winfo_" + name)
                original = method.return_value
                method.return_value = value
                with self.assertRaisesRegex(RuntimeError, "outside"):
                    self.capture()
                method.return_value = original
        self.grab.grab.assert_not_called()

    def test_no_upscaling_of_an_incomplete_capture(self):
        self.image.size, self.image.width = (400, 240), 400
        with self.assertRaisesRegex(RuntimeError, "fewer pixels"):
            self.capture()

    def test_blank_capture_fails_instead_of_claiming_visual_success(self):
        self.image.getextrema.return_value = [(255, 255)] * 3
        with self.assertRaisesRegex(RuntimeError, "blank"):
            self.capture()

    def test_unavailable_wayland_is_explicit(self):
        self.grab.grab.side_effect = OSError("X get_image failed")
        with (
            mock.patch("scripts.docs.screen_capture.shutil.which", return_value=None),
            self.assertRaisesRegex(RuntimeError, "unavailable"),
        ):
            self.capture()

    def wayland(self, run):
        self.grab.grab.side_effect = OSError("X get_image failed")
        with (
            tempfile.TemporaryDirectory() as runtime,
            mock.patch.dict(
                os.environ,
                {"XDG_RUNTIME_DIR": runtime, "WAYLAND_DISPLAY": "wayland-test"},
            ),
            mock.patch(
                "scripts.docs.screen_capture.shutil.which",
                return_value="/usr/bin/grim",
            ),
            mock.patch("scripts.docs.screen_capture.subprocess.run", side_effect=run),
        ):
            return self.capture()

    def test_wayland_exact_region_bounded_wait_and_private_cleanup(self):
        paths = []

        def run(command, **kwargs):
            self.assertEqual(command[:3], ["/usr/bin/grim", "-g", "10,20 800x480"])
            self.assertEqual(kwargs["timeout"], 10)
            self.assertNotIn("shell", kwargs)
            self.assertEqual(kwargs["env"]["WAYLAND_DISPLAY"], "wayland-test")
            target = Path(command[-1])
            self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
            paths.append(target)
            target.touch()
            return mock.Mock(returncode=0)

        self.assertIs(self.wayland(run), self.image)
        self.assertFalse(paths[0].parent.exists())

    def test_wayland_timeout_is_actionable(self):
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            self.wayland(mock.Mock(side_effect=subprocess.TimeoutExpired("grim", 10)))

    def test_failed_wayland_does_not_dump_environment_or_stderr(self):
        with self.assertRaisesRegex(RuntimeError, "^Wayland screen capture failed$"):
            self.wayland(
                mock.Mock(return_value=mock.Mock(returncode=1, stderr="private detail"))
            )


if __name__ == "__main__":
    unittest.main()
