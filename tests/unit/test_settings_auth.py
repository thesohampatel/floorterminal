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
from floorterminal.core.settings_auth import SettingsAuthError, SettingsCredentials


class SettingsCredentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.initial = hash_settings_password("admin@123")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "settings_auth.json"
        self.credentials = SettingsCredentials(self.initial, self.path)

    def change(self, password="LocalPassword@42"):
        self.credentials.replace(
            password, authorized_hash=self.credentials.current_hash()
        )

    def test_bootstrap_is_public_and_does_not_create_runtime_files(self):
        self.assertTrue(self.credentials.verify("admin@123"))
        self.assertFalse(self.path.exists())

    def test_replacement_survives_restart_and_a_different_build(self):
        self.change()
        restarted = SettingsCredentials(
            hash_settings_password("NewBuild@123"), self.path
        )
        self.assertTrue(restarted.verify("LocalPassword@42"))
        self.assertFalse(restarted.verify("admin@123"))
        self.assertFalse(restarted.verify("NewBuild@123"))
        self.assertNotIn("LocalPassword@42", self.path.read_text())
        if os.name != "nt":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_wrong_or_expired_authorization_does_not_replace_password(self):
        self.change()
        original = self.path.read_bytes()
        with self.assertRaisesRegex(SettingsAuthError, "authorize again"):
            self.credentials.replace(
                "DifferentPassword@42", authorized_hash=self.initial
            )
        self.assertEqual(self.path.read_bytes(), original)

    def test_invalid_or_reused_passwords_are_rejected(self):
        self.change()
        original = self.path.read_bytes()
        for password in (
            "short",
            "x" * 129,
            "spaces in password",
            "bad\x00password",
            "admin@123",
            "LocalPassword@42",
        ):
            with (
                self.subTest(password_length=len(password)),
                self.assertRaises(SettingsAuthError),
            ):
                self.change(password)
        self.assertEqual(self.path.read_bytes(), original)

    def test_bad_local_credentials_never_fall_back_to_public_password(self):
        for data in (
            b"",
            b"{",
            b"[]",
            b"null",
            b"x" * 4097,
            json.dumps(
                {"schema_version": True, "settings_password_hash": self.initial}
            ).encode(),
            json.dumps({"schema_version": 1, "settings_password_hash": "bad"}).encode(),
        ):
            self.path.write_bytes(data)
            with self.assertRaises(SettingsAuthError):
                self.credentials.verify("admin@123")

    @unittest.skipIf(os.name == "nt", "symlink permissions differ on Windows")
    def test_symlinks_and_nonregular_files_are_rejected(self):
        target = self.path.with_name("target.json")
        self.path.symlink_to(target)
        with self.assertRaises(SettingsAuthError):
            self.credentials.current_hash()
        self.path.unlink()
        self.path.mkdir()
        with self.assertRaises(SettingsAuthError):
            self.credentials.current_hash()
        self.path.rmdir()
        os.mkfifo(self.path)
        with self.assertRaises(SettingsAuthError):
            self.credentials.current_hash()

    def test_failed_atomic_write_keeps_old_credential_and_removes_temporary(self):
        self.change()
        original = self.path.read_bytes()
        with (
            mock.patch(
                "floorterminal.core.config.os.replace",
                side_effect=OSError("disk failure"),
            ),
            self.assertRaisesRegex(SettingsAuthError, "not saved"),
        ):
            self.change("AnotherPassword@42")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def app(self):
        app = FloorTerminalApp.__new__(FloorTerminalApp)
        app.settings_credentials = self.credentials
        app.auth_throttle = PersistentAuthThrottle(
            self.path.with_name("auth_throttle.json")
        )
        app.modal = None
        app.authorized_admin_identity = "Site administrator"
        app.logger = mock.Mock()
        app.notify = mock.Mock()
        return app

    def test_change_dialog_requires_current_password_and_matching_confirmation(self):
        app = self.app()
        resume = mock.Mock()
        app.request_password_change(resume)
        app.modal["value"] = "wrong"
        app.submit_admin_dialog()
        self.assertEqual(app.modal["stage"], "password")
        app.modal["value"] = "admin@123"
        app.submit_admin_dialog()
        self.assertEqual(app.modal["stage"], "new_password")
        app.modal["value"] = "LocalPassword@42"
        app.submit_admin_dialog()
        app.modal["value"] = "NotMatching@42"
        app.submit_admin_dialog()
        self.assertEqual(app.modal["stage"], "new_password")
        self.assertNotIn("new_password", app.modal)
        self.assertFalse(self.path.exists())
        for _ in range(2):
            app.modal["value"] = "LocalPassword@42"
            app.submit_admin_dialog()
        self.assertIsNone(app.modal)
        resume.assert_called_once_with(True)
        self.assertTrue(self.credentials.verify("LocalPassword@42"))
        self.assertNotIn("LocalPassword@42", str(app.logger.mock_calls))
        self.assertNotIn("admin@123", str(app.logger.mock_calls))

    def test_expired_password_change_requires_fresh_authorization(self):
        app = self.app()
        app.request_password_change(mock.Mock())
        app.modal["value"] = "admin@123"
        app.submit_admin_dialog()
        app.modal.update(authorization_expires=0, value="LocalPassword@42")
        app.submit_admin_dialog()
        self.assertEqual(app.modal["stage"], "password")
        self.assertNotIn("authorized_hash", app.modal)
        self.assertFalse(self.path.exists())

    def test_all_protected_actions_require_the_local_password(self):
        self.change()
        for purpose in (
            "settings",
            "exit",
            "windowed",
            "fullscreen",
            "software_update",
            "software_rollback",
        ):
            with self.subTest(purpose=purpose):
                app = self.app()
                app.root = SimpleNamespace(attributes=mock.Mock())
                app.load_settings_directory = mock.Mock()
                app._shutdown = mock.Mock()
                app.install_software_update = mock.Mock()
                app.restore_previous_version = mock.Mock()
                app.request_admin_access(purpose)
                app.modal.update(stage="password", value="admin@123")
                app.submit_admin_dialog()
                self.assertIsNotNone(app.modal)
                for callback in (
                    app.load_settings_directory,
                    app._shutdown,
                    app.root.attributes,
                    app.install_software_update,
                    app.restore_previous_version,
                ):
                    callback.assert_not_called()
                app.modal["value"] = "LocalPassword@42"
                app.submit_admin_dialog()
                self.assertIsNone(app.modal)

    def test_damaged_credential_blocks_admin_but_not_operator_loop(self):
        self.path.write_text("damaged")
        app = self.app()
        app.request_admin_access("settings")
        app.modal.update(stage="password", value="admin@123")
        app.submit_admin_dialog()
        self.assertIn("cannot be trusted", app.modal["error"])
        self.assertEqual(app.modal["value"], "")
