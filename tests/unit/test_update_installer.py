import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from floorterminal.update import installer, journal, media, trust
from floorterminal.update.layout import InstallLayout

from .update_fixtures import (
    build_installation,
    executable_bytes,
    make_key,
    package_document,
    write_update_drive,
)


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.seed, self.key_id, anchor = make_key()
        patcher = mock.patch.object(trust, "TRUSTED_KEYS", (anchor,))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.work = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.work, ignore_errors=True))
        self.layout = InstallLayout(build_installation(self.work / "opt"))
        installer.initialise(self.layout, "1.0.0")

    def stage(self, version="1.1.0"):
        mount = self.work / "media" / version
        artifact = executable_bytes(version)
        write_update_drive(mount, self.seed, self.key_id, version, artifact=artifact)
        package = media.read_package(mount)
        media.stage(self.layout, package, expect_executable=True)
        return artifact

    def test_a_fresh_managed_installation_starts_confirmed(self):
        record = journal.read_journal(self.layout.journal)
        self.assertEqual(record.state, journal.STATE_CONFIRMED)
        self.assertEqual(record.active_version, "1.0.0")
        self.assertTrue(self.layout.managed)
        self.assertEqual(self.layout.installed_versions(), ("1.0.0",))

    def test_activation_switches_one_symbolic_link_and_keeps_the_old_slot(self):
        artifact = self.stage()
        result = installer.activate(
            self.layout, "1.1.0", authorized_by="A. Supervisor", source="usb"
        )
        self.assertEqual((result.from_version, result.to_version), ("1.0.0", "1.1.0"))
        self.assertEqual(self.layout.active_version(), "1.1.0")
        self.assertEqual(
            os.readlink(self.layout.active_link), "versions/1.1.0/floorterminal"
        )
        self.assertEqual(self.layout.slot_executable("1.1.0").read_bytes(), artifact)
        self.assertTrue(self.layout.slot_executable("1.0.0").is_file())
        self.assertEqual(self.layout.installed_versions(), ("1.0.0", "1.1.0"))

    def test_activation_never_touches_deployment_owned_files(self):
        before = {
            path.name: path.read_bytes()
            for path in self.layout.root.iterdir()
            if path.is_file() and not path.is_symlink()
        }
        self.stage()
        installer.activate(self.layout, "1.1.0", authorized_by="A. Supervisor")
        for name, content in before.items():
            with self.subTest(file=name):
                self.assertEqual((self.layout.root / name).read_bytes(), content)

    def test_activation_enters_probation_and_publishes_launcher_state(self):
        self.stage()
        installer.activate(self.layout, "1.1.0", authorized_by="A. Supervisor")
        record = journal.read_journal(self.layout.journal)
        self.assertEqual(record.state, journal.STATE_PROBATION)
        self.assertEqual(record.previous_version, "1.0.0")
        boot = journal.read_boot_state(self.layout.boot_state)
        self.assertEqual(boot["STATUS"], "probation")
        self.assertEqual(boot["ACTIVE"], "1.1.0")
        self.assertEqual(boot["PREVIOUS"], "1.0.0")
        self.assertEqual(boot["LIMIT"], str(trust.PROBATION_START_LIMIT))

    def test_activation_rechecks_payload_and_signature_without_changing_active_state(
        self,
    ):
        for name, content in (
            (trust.EXECUTABLE_NAME, executable_bytes("changed")),
            (trust.SIGNATURE_NAME, b"{}"),
            (trust.MANIFEST_NAME, b"{}"),
        ):
            with self.subTest(file=name):
                self.stage()
                before = self.layout.boot_state.read_bytes()
                (self.layout.staging_dir / "1.1.0" / name).write_bytes(content)
                with self.assertRaises(installer.ActivationError):
                    installer.activate(self.layout, "1.1.0")
                self.assertEqual(self.layout.active_version(), "1.0.0")
                self.assertEqual(self.layout.boot_state.read_bytes(), before)

    def test_activation_refuses_signed_metadata_for_a_different_slot(self):
        self.stage("1.2.0")
        (self.layout.staging_dir / "1.2.0").rename(self.layout.staging_dir / "1.1.0")
        with self.assertRaisesRegex(installer.ActivationError, "does not match"):
            installer.activate(self.layout, "1.1.0")
        self.assertEqual(self.layout.active_version(), "1.0.0")

    def test_activation_does_not_reuse_a_corrupt_retained_slot(self):
        self.stage()
        slot = self.layout.slot("1.1.0")
        slot.mkdir()
        self.layout.slot_executable("1.1.0").write_bytes(executable_bytes("corrupt"))
        with self.assertRaisesRegex(installer.ActivationError, "checksum"):
            installer.activate(self.layout, "1.1.0")
        self.assertEqual(self.layout.active_version(), "1.0.0")

    def test_promotion_keeps_authenticated_metadata_with_the_executable(self):
        self.stage()
        installer.activate(self.layout, "1.1.0")
        package = media.verify_local_package(self.layout.slot("1.1.0"), "1.1.0")
        self.assertEqual(package.package.signing_key_id, self.key_id)
        self.assertFalse((self.layout.staging_dir / "1.1.0").exists())

    def test_confirmation_clears_probation_and_records_the_event(self):
        self.stage()
        installer.activate(self.layout, "1.1.0", authorized_by="A. Supervisor")
        record = installer.confirm(self.layout)
        self.assertEqual(record.state, journal.STATE_CONFIRMED)
        self.assertTrue(record.confirmed_at_utc)
        events = [row["event"] for row in journal.read_log(self.layout.update_log)]
        self.assertIn("update_confirmed", events)
        self.assertIn("update_activated", events)

    def test_rollback_restores_the_previous_slot(self):
        self.stage()
        installer.activate(self.layout, "1.1.0", authorized_by="A. Supervisor")
        installer.confirm(self.layout)
        self.assertEqual(installer.rollback_target(self.layout), "1.0.0")
        result = installer.rollback(self.layout, authorized_by="A. Supervisor")
        self.assertEqual(result.to_version, "1.0.0")
        self.assertEqual(self.layout.active_version(), "1.0.0")
        record = journal.read_journal(self.layout.journal)
        self.assertEqual(record.state, journal.STATE_CONFIRMED)
        self.assertEqual(record.previous_version, "1.1.0")
        self.assertEqual(installer.rollback_target(self.layout), "1.1.0")

    def test_rollback_refuses_a_version_that_is_not_installed(self):
        with self.assertRaisesRegex(installer.ActivationError, "No previous version"):
            installer.rollback(self.layout)
        with self.assertRaisesRegex(installer.ActivationError, "no longer installed"):
            installer.rollback(self.layout, "9.9.9")

    def test_activation_refuses_an_unmanaged_installation(self):
        flat = self.work / "flat"
        flat.mkdir()
        (flat / trust.EXECUTABLE_NAME).write_bytes(executable_bytes("flat"))
        layout = InstallLayout(flat)
        self.assertFalse(layout.managed)
        with self.assertRaisesRegex(installer.ActivationError, "managed version slots"):
            installer.activate(layout, "1.1.0")

    def test_activation_refuses_a_version_that_was_never_staged(self):
        with self.assertRaisesRegex(installer.ActivationError, "No verified staged"):
            installer.activate(self.layout, "1.4.0")
        with self.assertRaisesRegex(installer.ActivationError, "already active"):
            installer.activate(self.layout, "1.0.0")

    def test_startup_detects_a_launcher_rollback_and_reports_it(self):
        """The watchdog switches the link without the application's help."""
        self.stage()
        installer.activate(self.layout, "1.1.0", authorized_by="A. Supervisor")
        self.layout.active_link.unlink()
        os.symlink("versions/1.0.0/floorterminal", self.layout.active_link)
        record = installer.initialise(self.layout, "1.0.0")
        self.assertEqual(record.state, journal.STATE_ROLLED_BACK)
        self.assertEqual(record.active_version, "1.0.0")
        self.assertEqual(record.last_action, "watchdog_rollback")
        events = [row["event"] for row in journal.read_log(self.layout.update_log)]
        self.assertIn("update_auto_rolled_back", events)

    def test_startup_survives_a_destroyed_journal_without_changing_the_active_version(
        self,
    ):
        self.layout.journal.write_text("{ not json", encoding="utf-8")
        record = installer.initialise(self.layout, "1.0.0")
        self.assertEqual(record.state, journal.STATE_CONFIRMED)
        self.assertEqual(self.layout.active_version(), "1.0.0")
        self.layout.journal.write_text(
            json.dumps({"schema_version": 99}), encoding="utf-8"
        )
        self.assertEqual(
            installer.initialise(self.layout, "1.0.0").active_version, "1.0.0"
        )

    def test_interruption_between_journal_and_link_swap_is_recoverable(self):
        """A crash after the journal write leaves the old version bootable."""
        self.stage()
        with (
            mock.patch.object(
                installer, "_swap_link", side_effect=OSError("power loss")
            ),
            self.assertRaises(OSError),
        ):
            installer.activate(self.layout, "1.1.0", authorized_by="A. Supervisor")
        self.assertEqual(self.layout.active_version(), "1.0.0")
        boot = journal.read_boot_state(self.layout.boot_state)
        # The watchdog's rollback target is the version that is still running, so
        # the recorded intent resolves to no change at all.
        self.assertEqual(boot["STATUS"], "probation")
        self.assertEqual(boot["PREVIOUS"], "1.0.0")
        record = installer.initialise(self.layout, "1.0.0")
        self.assertEqual(self.layout.active_version(), "1.0.0")
        self.assertEqual(record.active_version, "1.0.0")

    def test_pruning_keeps_the_active_and_rollback_versions(self):
        for release in ("1.1.0", "1.2.0", "1.3.0"):
            document = package_document(release, artifact=executable_bytes(release))
            mount = self.work / "media" / release
            write_update_drive(
                mount,
                self.seed,
                self.key_id,
                release,
                artifact=executable_bytes(release),
                document=document,
            )
            media.stage(self.layout, media.read_package(mount), expect_executable=True)
            installer.activate(self.layout, release, authorized_by="A. Supervisor")
            installer.confirm(self.layout)
        self.assertEqual(self.layout.active_version(), "1.3.0")
        installed = set(self.layout.installed_versions())
        self.assertIn("1.3.0", installed)
        self.assertIn("1.2.0", installed)
        self.assertLessEqual(len(installed), trust.RETAINED_VERSION_SLOTS)

    def test_slot_names_cannot_escape_the_versions_directory(self):
        for name in ("../evil", "..", ".", "a/b", "a\\b", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.layout.slot(name)

    def test_staged_candidates_can_be_listed_and_discarded(self):
        self.stage()
        self.assertEqual(installer.staged_versions(self.layout), ("1.1.0",))
        installer.discard_staging(self.layout)
        self.assertEqual(installer.staged_versions(self.layout), ())
        self.assertTrue(self.layout.staging_dir.is_dir())


class BootStateTests(unittest.TestCase):
    def test_boot_state_only_contains_launcher_safe_characters(self):
        record = journal.Journal(
            state=journal.STATE_PROBATION,
            active_version="1.1.0; rm -rf /",
            previous_version="1.0.0",
            start_attempts=2,
        )
        rendered = journal.render_boot_state(record).decode("ascii")
        self.assertIn("STATUS=probation", rendered)
        # A hostile version string is emitted as an empty value rather than
        # anything the launcher could act on.
        self.assertIn("ACTIVE=\n", rendered)
        self.assertIn("PREVIOUS=1.0.0", rendered)
        self.assertIn("ATTEMPTS=2", rendered)

    def test_damaged_boot_state_lines_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "boot_state"
            path.write_text(
                "STATUS=probation\nrm -rf /\nACTIVE=1.1.0\nEVIL=`whoami`\n= \n",
                encoding="ascii",
            )
            values = journal.read_boot_state(path)
            self.assertEqual(values, {"STATUS": "probation", "ACTIVE": "1.1.0"})

    def test_update_log_rotates_and_survives_damaged_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "update-log.jsonl"
            journal.append_log(path, "update_activated", to_version="1.1.0")
            with path.open("a", encoding="utf-8") as stream:
                stream.write("this row is not json\n")
            journal.append_log(path, "update_confirmed", to_version="1.1.0")
            events = [row["event"] for row in journal.read_log(path)]
            self.assertEqual(events, ["update_confirmed", "update_activated"])
            self.assertEqual(oct(path.stat().st_mode)[-3:], "600")


if __name__ == "__main__":
    unittest.main()
