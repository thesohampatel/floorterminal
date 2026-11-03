"""Documentation examples follow the package version without network access."""

import socket
import unittest
from unittest.mock import patch

from floorterminal import __version__
from floorterminal.update.version import parse
from scripts.docs.capture_images import StaticUpdateService, _grab, _snapshots


class DocumentationSnapshotTests(unittest.TestCase):
    def test_view_fixture_accepts_gui_heartbeat_without_changing_status(self):
        snapshot = _snapshots()["current"]
        service = StaticUpdateService(snapshot)
        for _ in range(10):
            service.note_ui_heartbeat()
        self.assertIs(service.status(), snapshot)
        self.assertIs(service.start(), service)
        service.request_scan()
        service.stop()
        self.assertIs(service.status(), snapshot)

    def test_error_panel_cannot_be_published_as_a_successful_screen_capture(self):
        from unittest.mock import Mock

        for panel, blocked in (({"operation": "Rendering"}, False), (None, True)):
            app = Mock(error_panel=panel, render_blocked=blocked)
            with patch("scripts.docs.capture_images._settle"), self.assertRaisesRegex(RuntimeError, "UI reported"):
                _grab(app, Mock(), Mock(), Mock())

    def test_current_and_future_examples_are_consistent_and_offline(self):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")):
            snapshots = _snapshots()
        current = snapshots["current"]
        self.assertEqual(current.installed_version, __version__)
        self.assertEqual(current.latest_version, __version__)
        self.assertEqual(current.channel.version, __version__)
        ready = snapshots["ready"]
        self.assertGreater(parse(ready.latest_version), parse(__version__))
        self.assertEqual(ready.latest_version, ready.staged.version)
        self.assertEqual(ready.channel.version, ready.staged.version)
        self.assertEqual(snapshots["available"].latest_version, ready.latest_version)
        self.assertIn("Illustrative", ready.staged.release_title)
        for snapshot in snapshots.values():
            self.assertEqual(snapshot.installed_version, __version__)

    def test_future_package_bump_does_not_need_manual_image_version_edits(self):
        with patch("floorterminal.__version__", "2.4.9"):
            snapshots = _snapshots()
        self.assertEqual(snapshots["current"].installed_version, "2.4.9")
        self.assertEqual(snapshots["ready"].latest_version, "2.5.0")
        self.assertEqual(snapshots["ready"].rollback_version, "2.3.0")
        self.assertIn("v2.4.9", snapshots["current"].channel.archive_name)
        self.assertIn("v2.5.0", snapshots["ready"].channel.archive_name)


if __name__ == "__main__":
    unittest.main()
