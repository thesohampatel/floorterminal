import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from floorterminal.app import FloorTerminalApp
from floorterminal.core.auth_throttle import PersistentAuthThrottle
from floorterminal.core.project_profile import hash_settings_password
from floorterminal.core.settings_auth import SettingsCredentials
from floorterminal.integration.runtime import (
    IntegrationClient,
    IntegrationError,
    UrllibTransport,
)
from floorterminal.storage.audit import ActivityLogger


class Response:
    def __init__(self, body, declared=None):
        self.body = body
        self.headers = {} if declared is None else {"Content-Length": str(declared)}

    def read(self, limit):
        return self.body.read(limit)


class SecurityRegressionTests(unittest.TestCase):
    def test_remote_error_detail_is_bounded_and_control_safe(self):
        detail = IntegrationClient._safe_remote_detail("line one\n\x1b[31m" + "x" * 600)
        self.assertNotIn("\n", detail)
        self.assertNotIn("\x1b", detail)
        self.assertLessEqual(len(detail), 501)

    def test_offline_process_flag_prevents_connector_transport_calls(self):
        with (
            mock.patch.dict(os.environ, {"FLOORTERMINAL_DISABLE_NETWORK": "1"}),
            mock.patch("floorterminal.integration.runtime.build_opener") as opener,
            self.assertRaisesRegex(IntegrationError, "Network disabled"),
        ):
            UrllibTransport().send(None, 1)
        opener.assert_not_called()

    def test_offline_flags_prevent_even_a_manual_channel_network_fetch(self):
        from floorterminal.update import remote, trust

        for flag in (
            "FLOORTERMINAL_DISABLE_NETWORK",
            "FLOORTERMINAL_DISABLE_UPDATE_NETWORK",
        ):
            with (
                self.subTest(flag=flag),
                mock.patch.dict(os.environ, {flag: "1"}),
                mock.patch.object(remote, "build_opener") as opener,
                self.assertRaisesRegex(remote.ChannelError, "Network disabled"),
            ):
                remote._fetch(trust.UPDATE_CHANNEL_URL, 100)
            opener.assert_not_called()

    def test_update_transport_refuses_other_paths_on_the_same_host(self):
        from floorterminal.update import remote, trust

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(remote, "build_opener") as opener,
            self.assertRaises(remote.ChannelError) as raised,
        ):
            remote._fetch(trust.UPDATE_CHANNEL_URL + "?alternate=1", 100)
        self.assertEqual(raised.exception.outcome, remote.OUTCOME_UNTRUSTED)
        opener.assert_not_called()

    def test_window_close_requires_attributed_administrator_authorization(self):
        app = FloorTerminalApp.__new__(FloorTerminalApp)
        app.modal = None
        app.auth_throttle = SimpleNamespace(remaining=lambda: 0)
        app.logger = SimpleNamespace(log=lambda *args, **kwargs: None)
        app.close_application()
        self.assertEqual(app.modal["purpose"], "exit")
        self.assertEqual(app.modal["stage"], "identity")
        app.modal["value"] = "Plant Administrator"
        app.submit_admin_dialog()
        self.assertEqual(app.modal["stage"], "password")
        self.assertEqual(app.modal["administrator"], "Plant Administrator")

    def test_settings_password_attempts_are_progressively_throttled(self):
        with tempfile.TemporaryDirectory() as directory:
            clocks = {"wall": 1_000.0, "mono": 100.0}
            throttle = PersistentAuthThrottle(
                Path(directory) / "auth_throttle.json",
                wall_clock=lambda: clocks["wall"],
                monotonic=lambda: clocks["mono"],
            )
            throttle.failed_attempts = 2
            app = FloorTerminalApp.__new__(FloorTerminalApp)
            app.modal = {"kind": "password", "value": "wrong"}
            app.project_profile = SimpleNamespace(
                settings_password_hash=hash_settings_password(
                    "CorrectPassword@1", bytes.fromhex("33" * 16)
                )
            )
            app.auth_throttle = throttle
            app.settings_credentials = SettingsCredentials(
                app.project_profile.settings_password_hash,
                Path(directory) / "settings_auth.json",
            )
            events = []
            app.logger = SimpleNamespace(
                log=lambda *args, **kwargs: events.append((args, kwargs))
            )
            app.load_settings_directory = lambda: events.append(("opened", {}))
            app.verify_settings_password()
            self.assertEqual(throttle.failed_attempts, 3)
            self.assertEqual(throttle.blocked_until_monotonic, 102.0)
            self.assertIn("wait 2 seconds", app.modal["error"])

            app.modal["value"] = "CorrectPassword@1"
            clocks["mono"] = 101.0
            app.verify_settings_password()
            self.assertEqual(throttle.failed_attempts, 3)
            self.assertIn("Temporarily locked", app.modal["error"])

            app.modal["value"] = "CorrectPassword@1"
            clocks["mono"] = 103.0
            app.verify_settings_password()
            self.assertIsNone(app.modal)
            self.assertEqual(throttle.failed_attempts, 0)
            self.assertEqual(throttle.blocked_until_monotonic, 0.0)

    def test_authentication_throttle_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth_throttle.json"
            first = PersistentAuthThrottle(
                path, wall_clock=lambda: 1_000.0, monotonic=lambda: 50.0
            )
            first.failed_attempts = 5
            self.assertEqual(first.register_failure(), 60)
            restored = PersistentAuthThrottle(
                path, wall_clock=lambda: 1_010.0, monotonic=lambda: 5.0
            )
            self.assertEqual(restored.failed_attempts, 6)
            self.assertEqual(restored.remaining(), 50)

    def test_response_body_is_bounded_with_or_without_content_length(self):
        limit = UrllibTransport.MAX_RESPONSE_BYTES
        for response in (
            Response(io.BytesIO(b"x"), limit + 1),
            Response(io.BytesIO(b"x" * (limit + 1))),
        ):
            with self.assertRaisesRegex(IntegrationError, "4 MiB"):
                UrllibTransport._read_response(response)

    def test_audit_directories_and_files_are_private_and_repaired(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "logs"
            legacy = root / "2026/01/02/activity.jsonl"
            legacy.parent.mkdir(parents=True)
            legacy.write_text(json.dumps({"legacy": True}) + "\n")
            root.chmod(0o755)
            legacy.parent.chmod(0o755)
            legacy.chmod(0o644)
            logger = ActivityLogger(
                {
                    "log_directory": str(root),
                    "log_retention_days": 730,
                    "log_level": "INFO",
                    "log_storage_reserve_mb": 128,
                    "log_daily_growth_floor_mb": 1,
                    "line_name": "Test Line",
                }
            )
            logger.log("security_test")
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(legacy.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(legacy.stat().st_mode & 0o777, 0o600)
            current = next(root.glob("2026/*/*/activity.jsonl"))
            self.assertEqual(current.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
