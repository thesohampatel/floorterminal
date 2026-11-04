"""Pi kiosk resource and file-boundary regressions; no live services."""

import io
import json
import os
import stat
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from floorterminal.audio import SoundManager
from floorterminal.core.auth_throttle import PersistentAuthThrottle
from floorterminal.core.project_profile import hash_settings_password
from floorterminal.core.settings_auth import SettingsAuthError, SettingsCredentials
from floorterminal.integration.runtime import (
    IntegrationError,
    TransportHTTPError,
    UrllibTransport,
)
from floorterminal.storage.audit import ActivityLogger
from floorterminal.storage.housekeeping import inventory, prune_logs
from floorterminal.update import remote, trust

from .test_error_reporting import app


class KioskFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def throttle(self, path):
        return PersistentAuthThrottle(
            path, wall_clock=lambda: 1000, monotonic=lambda: 50
        )

    def test_invalid_throttle_shapes_numbers_duplicates_and_size_fail_closed(self):
        path = self.root / "throttle.json"
        for raw in (
            "null",
            "[]",
            "{}",
            '"text"',
            " " * 4097,
            '{"schema_version":1,"failed_attempts":0,"blocked_until_epoch":NaN}',
            '{"schema_version":1,"failed_attempts":0,"blocked_until_epoch":1e999}',
            '{"schema_version":true,"failed_attempts":0,"blocked_until_epoch":0}',
            '{"schema_version":1,"failed_attempts":0,"failed_attempts":1,"blocked_until_epoch":0}',
            "[" * 1500 + "]" * 1500,
        ):
            with self.subTest(raw=raw[:60]):
                path.write_text(raw)
                throttle = self.throttle(path)
                self.assertEqual(throttle.remaining(), 60)
                self.assertEqual(path.read_text(), raw)

    @unittest.skipIf(os.name == "nt", "POSIX file semantics")
    def test_unsafe_throttle_paths_never_modify_their_targets(self):
        path, target = self.root / "throttle.json", self.root / "unrelated"
        target.write_text('{"private":"keep"}')
        target.chmod(0o644)
        for kind in ("symlink", "hardlink", "fifo", "directory"):
            with self.subTest(kind=kind):
                if kind == "symlink":
                    path.symlink_to(target)
                elif kind == "hardlink":
                    os.link(target, path)
                elif kind == "fifo":
                    os.mkfifo(path)
                else:
                    path.mkdir()
                started = time.monotonic()
                throttle = self.throttle(path)
                self.assertLess(time.monotonic() - started, 1)
                self.assertEqual(throttle.remaining(), 60)
                with self.assertRaises(OSError):
                    throttle.clear()
                self.assertEqual(throttle.remaining(), 60)
                self.assertEqual(target.read_text(), '{"private":"keep"}')
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
                path.rmdir() if kind == "directory" else path.unlink()

    def test_failed_throttle_clear_preserves_in_memory_protection(self):
        throttle = self.throttle(self.root / "throttle.json")
        throttle.failed_attempts = 1_000_000
        throttle.register_failure()
        self.assertEqual(throttle.failed_attempts, 1_000_000)
        with (
            patch(
                "floorterminal.core.auth_throttle.write_json",
                side_effect=OSError("full"),
            ),
            self.assertRaises(OSError),
        ):
            throttle.clear()
        self.assertEqual(throttle.remaining(), 60)
        self.assertEqual(throttle.failed_attempts, 1_000_000)

    def test_credentials_reject_duplicate_keys_without_bootstrap_fallback(self):
        initial = hash_settings_password("offline-fixture-password")
        path = self.root / "auth.json"
        path.write_text(
            '{"schema_version":1,"schema_version":1,"settings_password_hash":'
            + json.dumps(initial)
            + "}"
        )
        with self.assertRaises(SettingsAuthError):
            SettingsCredentials(initial, path).current_hash()

    def log_path(self, age=0):
        day = (datetime.now().astimezone() - timedelta(days=age)).strftime("%Y/%m/%d")
        path = self.root / "logs" / day / "activity.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @unittest.skipIf(os.name == "nt", "POSIX file semantics")
    def test_audit_hardlinks_are_never_written_chmodded_or_pruned(self):
        target = self.root / "unrelated"
        target.write_text("keep")
        target.chmod(0o644)
        current, old = self.log_path(), self.log_path(200)
        os.link(target, current)
        os.link(target, old)
        logger = ActivityLogger({"log_directory": str(self.root / "logs")})
        logger.log("test")
        self.assertEqual(logger.write_failures, 1)
        self.assertEqual(inventory(logger.root), [])
        self.assertEqual(prune_logs(logger.root), 0)
        self.assertTrue(old.exists())
        self.assertEqual(target.read_text(), "keep")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)

    def test_private_audit_segments_are_not_reopened_for_permission_checks(self):
        logger = ActivityLogger({"log_directory": str(self.root / "logs")})
        logger.log("private")
        with patch(
            "floorterminal.storage.audit.os.open",
            side_effect=AssertionError("unneeded file open"),
        ):
            logger.prune()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO semantics")
    def test_audit_fifo_is_rejected_without_blocking_then_recovers(self):
        path = self.log_path()
        os.mkfifo(path)
        logger = ActivityLogger({"log_directory": str(self.root / "logs")})
        started = time.monotonic()
        logger.log("rejected")
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(logger.write_failures, 1)
        path.unlink()
        logger.log("recovered")
        self.assertIn("recovered", path.read_text())
        self.assertEqual(logger.last_error, "")

    @unittest.skipIf(os.name == "nt", "POSIX hard-link semantics")
    def test_unsafe_rotation_destination_does_not_move_any_segment(self):
        current = self.log_path()
        current.write_text("original")
        outside = self.root / "outside"
        outside.write_text("keep")
        backup = current.with_name("activity.2.jsonl")
        os.link(outside, backup)
        logger = ActivityLogger({"log_directory": str(self.root / "logs")})
        logger.SEGMENT_BYTES = 4
        logger.log("would rotate")
        self.assertEqual(logger.write_failures, 1)
        self.assertEqual(current.read_text(), "original")
        self.assertEqual(outside.read_text(), "keep")
        self.assertFalse(current.with_name("activity.1.jsonl").exists())


class TransportCleanupTests(unittest.TestCase):
    def test_failed_connector_responses_close_on_normal_oversized_and_failed_read(self):
        prepared = SimpleNamespace(
            url="https://example.test/resource", body=None, headers={}, method="GET"
        )
        for mode in ("normal", "oversized", "read_failure"):
            with self.subTest(mode=mode):
                stream = io.BytesIO(b'{"message":"offline fixture"}')
                headers = (
                    {"Content-Length": str(5 * 1024 * 1024)}
                    if mode == "oversized"
                    else {}
                )
                error = HTTPError(prepared.url, 429, "Too many", headers, stream)
                if mode == "read_failure":
                    error.read = Mock(side_effect=OSError("interrupted"))
                with (
                    patch.dict(os.environ, {"FLOORTERMINAL_DISABLE_NETWORK": "0"}),
                    patch("floorterminal.integration.runtime.build_opener") as opener,
                ):
                    opener.return_value.open.side_effect = error
                    with self.assertRaises(
                        (TransportHTTPError, IntegrationError, OSError)
                    ):
                        UrllibTransport().send(prepared, 1)
                self.assertTrue(stream.closed)

    def test_update_http_error_closes_without_reading_untrusted_body(self):
        stream = io.BytesIO(b"unused")
        error = HTTPError(trust.UPDATE_CHANNEL_URL, 503, "Unavailable", {}, stream)
        with (
            patch.dict(
                os.environ,
                {
                    "FLOORTERMINAL_DISABLE_NETWORK": "0",
                    "FLOORTERMINAL_DISABLE_UPDATE_NETWORK": "0",
                },
            ),
            patch.object(remote, "build_opener") as opener,
        ):
            opener.return_value.open.side_effect = error
            with self.assertRaises(remote.ChannelError):
                remote._fetch(trust.UPDATE_CHANNEL_URL, 100)
        self.assertTrue(stream.closed)


class AudioCapacityTests(unittest.TestCase):
    def manager(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        Path(temp.name, "support.wav").write_bytes(b"offline-only")
        return SoundManager({"sound_enabled": True}, asset_directory=temp.name)

    def test_force_preview_burst_is_bounded_and_slots_recover(self):
        manager = self.manager()
        release = threading.Event()
        entered = threading.Event()
        calls = []

        def slow(*_args):
            calls.append(1)
            if len(calls) == manager.MAX_ACTIVE_PLAYERS:
                entered.set()
            release.wait(3)

        with patch.object(manager, "_play_worker", side_effect=slow):
            try:
                self.assertTrue(manager.preview())
                self.assertTrue(manager.preview())
                self.assertTrue(entered.wait(1))
                self.assertFalse(any(manager.preview() for _ in range(500)))
                self.assertEqual(manager._active_players, 2)
            finally:
                release.set()
            deadline = time.monotonic() + 2
            while manager._active_players and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(manager._active_players, 0)
        manager.close()
        self.assertFalse(manager.preview())

    def test_worker_start_failure_is_nonfatal_and_releases_slot(self):
        manager = self.manager()
        with patch(
            "floorterminal.audio.threading.Thread.start",
            side_effect=RuntimeError("capacity"),
        ):
            self.assertFalse(manager.preview())
        self.assertEqual(manager._active_players, 0)
        self.assertEqual(manager._last_played, {})

    def test_close_during_player_spawn_terminates_and_reaps_it(self):
        manager = self.manager()
        process = Mock(returncode=0)

        def spawn(*_args, **_kwargs):
            manager.close()
            return process

        with (
            patch("floorterminal.audio.platform.system", return_value="Linux"),
            patch.object(manager, "_command", return_value=["offline-player"]),
            patch("floorterminal.audio.subprocess.Popen", side_effect=spawn),
        ):
            manager._play_worker("support", Path("unused"), 70)
        process.terminate.assert_called_once()
        process.wait.assert_called_once()
        self.assertEqual(manager._processes, set())


class KioskSchedulingTests(unittest.TestCase):
    def test_keyboard_page_change_wakes_transition_without_touch(self):
        instance = app()
        instance._animation_after = "slow-fallback"
        instance.touch_feedback = None
        instance._page_transition_until = time.monotonic() + 1
        instance.root.after_cancel = Mock()
        instance.root.after_idle = Mock(return_value="paint")
        instance.root.after = Mock(return_value="fast-frame")
        instance.request_render()
        instance.root.after_idle.call_args.args[0]()
        instance.root.after_cancel.assert_called_once_with("slow-fallback")
        self.assertEqual(instance._animation_after, "fast-frame")

    def test_touch_wakes_existing_static_timer_without_parallel_animation_loops(self):
        instance = app()
        instance._animation_after = "slow-fallback"
        instance.touch_feedback = (1, 1, time.monotonic())
        instance.root.after_cancel = Mock()
        instance.root.after_idle = Mock(return_value="paint")
        instance.root.after = Mock(return_value="fast-frame")
        for _ in range(50):
            instance.request_render()
        instance.root.after_idle.assert_called_once()
        instance.root.after_idle.call_args.args[0]()
        instance.root.after_cancel.assert_called_once_with("slow-fallback")
        self.assertEqual(instance._animation_after, "fast-frame")
        self.assertEqual(instance.root.after.call_args.args[0], 80)

    def test_static_modal_keeps_slow_fallback_and_touch_keeps_normal_refresh(self):
        instance = app()
        instance.modal = {"kind": "about"}
        instance.animate()
        self.assertEqual(instance.root.scheduled[-1][0], 1000)
        instance.touch_feedback = (1, 1, 100)
        with patch("floorterminal.ui.view.time.monotonic", return_value=100.1):
            instance.animate()
        self.assertEqual(instance.root.scheduled[-1][0], 80)

    def test_opaque_pages_never_render_hidden_production_layers(self):
        for error in (False, True):
            instance = app()
            instance.animation_start = time.monotonic()
            instance.viewport = lambda: SimpleNamespace(usable=True)
            instance.modal = {"kind": "about"}
            instance.error_panel = {"title": "Fault"} if error else None
            instance.draw_adaptive_dialog = Mock()
            instance.draw_adaptive_error = Mock()
            instance.draw_touch_feedback = Mock()
            instance.kiosk_header = Mock(side_effect=AssertionError("hidden layer"))
            instance.draw_kiosk_frame()
            (
                instance.draw_adaptive_error if error else instance.draw_adaptive_dialog
            ).assert_called_once()
            instance.draw_touch_feedback.assert_called_once()

    def test_health_worker_start_failure_releases_guard_and_schedules_retry(self):
        instance = app()
        with patch(
            "floorterminal.app.threading.Thread.start",
            side_effect=RuntimeError("capacity"),
        ):
            instance.check_storage_capacity()
        self.assertFalse(instance._storage_check_running)
        self.assertIn("could not start", instance.health_snapshot["check_error"])
        self.assertEqual(instance.root.scheduled[-1][0], 60000)

    def test_unexpected_health_failure_still_delivers_recovery_result(self):
        instance = app()
        instance.logger.prune = Mock(side_effect=ValueError("damaged metadata"))
        with patch("floorterminal.app.threading.Thread") as thread:
            instance.check_storage_capacity()
            thread.call_args.kwargs["target"]()
        instance.poll_events()
        self.assertFalse(instance._storage_check_running)
        self.assertIn("unavailable", instance.health_snapshot["check_error"])

    def test_closing_never_starts_a_new_health_worker(self):
        instance = app()
        instance._closing = True
        with patch("floorterminal.app.threading.Thread") as thread:
            instance.check_storage_capacity()
        thread.assert_not_called()
        self.assertEqual(instance.root.scheduled, [])
