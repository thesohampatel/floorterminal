import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from floorterminal.update import journal, manifest, media, remote, trust
from floorterminal.update.layout import InstallLayout
from floorterminal.update.service import (
    LEVEL_ATTENTION,
    LEVEL_OK,
    LEVEL_UNKNOWN,
    RESTART_SUPERVISOR,
    RESTART_UNSUPPORTED,
    UpdateService,
)

from .update_fixtures import (
    build_installation,
    channel_document,
    encode,
    executable_bytes,
    make_key,
    sign_document,
    write_update_drive,
)


class Logger:
    def __init__(self):
        self.events = []

    def log(self, event, level="INFO", **details):
        self.events.append((event, level, details))

    @property
    def names(self):
        return [event for event, _, _ in self.events]


class UpdateServiceTests(unittest.TestCase):
    def setUp(self):
        self.seed, self.key_id, anchor = make_key()
        patcher = mock.patch.object(trust, "TRUSTED_KEYS", (anchor,))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.work = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.work, ignore_errors=True))
        self.layout = InstallLayout(build_installation(self.work / "opt"))
        self.media_root = self.work / "media"
        self.logger = Logger()

    def service(self, **config):
        settings = {"software_update_check_enabled": False, **config}
        service = UpdateService(
            settings, self.logger, self.layout, media_roots=[str(self.media_root)]
        )
        service.prepare()
        return service

    def insert_drive(self, version="1.1.0"):
        mount = self.media_root / "kiosk" / trust.UPDATE_VOLUME_LABELS[0]
        mount.mkdir(parents=True, exist_ok=True)
        write_update_drive(
            mount, self.seed, self.key_id, version, artifact=executable_bytes(version)
        )
        return mount

    def ok_channel(self, version, age=0.0):
        return remote.ChannelResult(
            outcome=remote.OUTCOME_OK,
            checked_at_epoch=time.time() - age,
            checked_at_utc="2026-11-14T09:00:00Z",
            version=version,
            released_utc="2026-11-14T09:00:00Z",
            release_title="Published release",
            release_summary="Summary",
            minimum_upgradable_version="1.0.0",
            artifact_sha256="a" * 64,
            artifact_size_bytes=trust.MIN_ARTIFACT_BYTES,
        )

    # ------------------------------------------------------------- classification

    def test_reports_green_when_the_running_version_is_the_published_one(self):
        service = self.service(software_update_check_enabled=True)
        service._channel = self.ok_channel("1.0.0")
        status = service.refresh()
        self.assertEqual(status.level, LEVEL_OK)
        self.assertIn("up to date", status.headline)
        self.assertFalse(status.update_available)

    def test_reports_amber_when_a_newer_version_is_published(self):
        service = self.service(software_update_check_enabled=True)
        service._channel = self.ok_channel("2.0.0")
        status = service.refresh()
        self.assertEqual(status.level, LEVEL_ATTENTION)
        self.assertTrue(status.update_available)
        self.assertEqual(status.latest_version, "2.0.0")

    def test_reports_amber_when_cached_information_has_gone_stale(self):
        service = self.service(software_update_check_enabled=True)
        service._channel = self.ok_channel(
            "1.0.0", age=trust.CHECK_FRESHNESS_SECONDS + 60
        )
        status = service.refresh()
        self.assertEqual(status.level, LEVEL_ATTENTION)
        self.assertTrue(status.channel_stale)

    def test_reports_red_when_the_channel_cannot_be_reached(self):
        service = self.service(software_update_check_enabled=True)
        service._channel = remote.failure_result(
            remote.OUTCOME_UNAVAILABLE, "Update channel is unreachable", time.time()
        )
        status = service.refresh()
        self.assertEqual(status.level, LEVEL_UNKNOWN)
        self.assertIn("could not be checked", status.headline)
        self.assertIn("unreachable", status.detail)

    def test_reports_amber_when_an_administrator_turned_the_check_off(self):
        status = self.service().refresh()
        self.assertEqual(status.level, LEVEL_ATTENTION)
        self.assertIn("turned off", status.headline)

    def test_reports_red_after_an_automatic_recovery(self):
        service = self.service()
        record = journal.read_journal(self.layout.journal)
        record.state = journal.STATE_ROLLED_BACK
        record.last_action = "watchdog_rollback"
        record.active_version = "1.0.0"
        service._journal = record
        status = service.refresh()
        self.assertEqual(status.level, LEVEL_UNKNOWN)
        self.assertIn("restored automatically", status.headline)

    # -------------------------------------------------------------- media flow

    def test_a_verified_drive_is_staged_automatically_and_reported(self):
        service = self.service()
        self.insert_drive()
        status = service.refresh(scan_media=True)
        self.assertEqual(status.level, LEVEL_ATTENTION)
        self.assertIsNotNone(status.staged)
        self.assertEqual(status.staged.version, "1.1.0")
        self.assertEqual(status.staged.signing_key_id, self.key_id)
        self.assertTrue(status.can_install)
        self.assertIn("update_package_staged", self.logger.names)

    def test_a_tampered_drive_is_rejected_and_never_staged(self):
        service = self.service()
        mount = self.insert_drive()
        artifact = mount / trust.UPDATE_PACKAGE_DIRNAME / trust.EXECUTABLE_NAME
        artifact.write_bytes(executable_bytes("tampered"))
        status = service.refresh(scan_media=True)
        self.assertEqual(status.level, LEVEL_UNKNOWN)
        self.assertIn("rejected", status.headline)
        self.assertIsNone(status.staged)
        self.assertFalse(status.can_install)
        self.assertIn("update_media_rejected", self.logger.names)

    def test_repeated_scans_of_a_staged_drive_do_not_restage_it(self):
        service = self.service()
        self.insert_drive()
        service.refresh(scan_media=True)
        staged_path = self.layout.staging_dir / "1.1.0" / trust.EXECUTABLE_NAME
        stamp = staged_path.stat().st_mtime_ns
        verify = media.verify_artifact

        def verify_local_only(package):
            self.assertNotEqual(
                package.mount, self.media_root / "kiosk" / trust.UPDATE_VOLUME_LABELS[0]
            )
            return verify(package)

        with mock.patch.object(media, "verify_artifact", side_effect=verify_local_only):
            for _ in range(3):
                status = service.refresh(scan_media=True)
        self.assertEqual(status.staged.version, "1.1.0")
        self.assertTrue(status.staged.source_mount)
        self.assertEqual(staged_path.stat().st_mtime_ns, stamp)

    def test_a_drive_altered_after_staging_cannot_disturb_the_verified_copy(self):
        service = self.service()
        mount = self.insert_drive()
        service.refresh(scan_media=True)
        original = (
            self.layout.staging_dir / "1.1.0" / trust.EXECUTABLE_NAME
        ).read_bytes()
        (mount / trust.UPDATE_PACKAGE_DIRNAME / trust.EXECUTABLE_NAME).write_bytes(
            executable_bytes("tampered")
        )
        status = service.refresh(scan_media=True)
        self.assertEqual(status.staged.version, "1.1.0")
        self.assertEqual(
            (self.layout.staging_dir / "1.1.0" / trust.EXECUTABLE_NAME).read_bytes(),
            original,
        )
        result = service.install_staged(authorized_by="A. Supervisor")
        self.assertEqual(
            self.layout.slot_executable(result.to_version).read_bytes(), original
        )

    def test_corrupt_staged_payload_is_not_presented_as_verified_after_restart(self):
        service = self.service()
        mount = self.insert_drive()
        service.refresh(scan_media=True)
        shutil.rmtree(mount)
        staged = self.layout.staging_dir / "1.1.0" / trust.EXECUTABLE_NAME
        staged.write_bytes(executable_bytes("corrupt"))
        status = self.service().refresh()
        self.assertIsNone(status.staged)
        self.assertFalse(status.can_install)
        self.assertEqual(status.level, LEVEL_UNKNOWN)
        self.assertIn("Staged update rejected", status.detail)

    def test_unsigned_staging_summary_cannot_authorize_installation(self):
        service = self.service()
        mount = self.insert_drive()
        service.refresh(scan_media=True)
        shutil.rmtree(mount)
        (self.layout.staging_dir / "1.1.0" / trust.SIGNATURE_NAME).unlink()
        status = self.service().refresh()
        self.assertIsNone(status.staged)
        self.assertFalse(status.can_install)
        self.assertEqual(self.layout.active_version(), "1.0.0")

    def test_a_drive_signed_by_an_unknown_key_is_rejected(self):
        service = self.service()
        other_seed, other_id, _ = make_key()
        mount = self.media_root / "kiosk" / trust.UPDATE_VOLUME_LABELS[0]
        mount.mkdir(parents=True, exist_ok=True)
        write_update_drive(
            mount, other_seed, other_id, artifact=executable_bytes("1.1.0")
        )
        status = service.refresh(scan_media=True)
        self.assertEqual(status.level, LEVEL_UNKNOWN)
        self.assertIsNone(status.staged)

    # ------------------------------------------------------------- installation

    def test_installation_activates_and_records_the_authorizing_administrator(self):
        service = self.service()
        self.insert_drive()
        service.refresh(scan_media=True)
        result = service.install_staged(authorized_by="A. Supervisor")
        self.assertEqual(result.to_version, "1.1.0")
        self.assertEqual(self.layout.active_version(), "1.1.0")
        status = service.status()
        self.assertEqual(status.level, LEVEL_ATTENTION)
        self.assertIn("Restart required", status.headline)
        self.assertFalse(status.can_install)
        rows = journal.read_log(self.layout.update_log)
        activated = next(row for row in rows if row["event"] == "update_activated")
        self.assertEqual(activated["authorized_by"], "A. Supervisor")

    def test_installation_result_is_mirrored_onto_the_update_drive(self):
        service = self.service()
        mount = self.insert_drive()
        service.refresh(scan_media=True)
        service.install_staged(authorized_by="A. Supervisor")
        logs = list((mount / trust.MEDIA_LOG_DIRNAME).glob("*.jsonl"))
        self.assertEqual(len(logs), 1)
        text = logs[0].read_text(encoding="utf-8")
        self.assertIn("update_staged", text)
        self.assertIn("update_activated", text)

    def test_installation_without_a_staged_package_is_refused(self):
        service = self.service()
        with self.assertRaises(Exception) as caught:
            service.install_staged(authorized_by="A. Supervisor")
        self.assertIn("No verified update", str(caught.exception))

    def test_rollback_returns_to_the_previous_version(self):
        service = self.service()
        self.insert_drive()
        service.refresh(scan_media=True)
        service.install_staged(authorized_by="A. Supervisor")
        self.assertEqual(service.status().rollback_version, "1.0.0")
        result = service.rollback(authorized_by="A. Supervisor")
        self.assertEqual(result.to_version, "1.0.0")
        self.assertEqual(self.layout.active_version(), "1.0.0")

    def test_probation_is_confirmed_only_after_the_dwell_period(self):
        service = self.service()
        self.insert_drive()
        service.refresh(scan_media=True)
        service.install_staged(authorized_by="A. Supervisor")
        follower = self.service()
        follower.installed_version = "1.1.0"
        follower.prepare()
        self.assertEqual(follower.status().state, journal.STATE_PROBATION)
        follower._maybe_confirm()
        self.assertEqual(
            journal.read_journal(self.layout.journal).state, journal.STATE_PROBATION
        )
        follower._started_monotonic -= trust.PROBATION_DWELL_SECONDS + 1
        follower._maybe_confirm()
        self.assertEqual(
            journal.read_journal(self.layout.journal).state, journal.STATE_CONFIRMED
        )

    # ------------------------------------------------------------------ safety

    def test_an_unmanaged_installation_reports_status_but_offers_no_actions(self):
        flat = self.work / "flat"
        flat.mkdir()
        (flat / trust.EXECUTABLE_NAME).write_bytes(executable_bytes("flat"))
        service = UpdateService({}, self.logger, InstallLayout(flat), media_roots=[])
        status = service.prepare()
        self.assertFalse(status.managed)
        self.assertFalse(status.can_install)
        self.assertFalse(status.can_rollback)

    def test_the_check_never_raises_whatever_the_network_does(self):
        service = self.service(software_update_check_enabled=True)
        for failure in (
            remote.ChannelError("blocked", remote.OUTCOME_UNAVAILABLE),
            OSError("no route to host"),
            ValueError("garbage"),
        ):
            with (
                self.subTest(failure=type(failure).__name__),
                mock.patch.object(remote, "fetch_channel", side_effect=failure),
            ):
                status = service.check_channel(force=True)
                self.assertEqual(status.level, LEVEL_UNKNOWN)
                self.assertFalse(status.checking)

    def test_a_successful_check_is_cached_and_reloaded(self):
        service = self.service(software_update_check_enabled=True)
        document = encode(channel_document("2.0.0", artifact=executable_bytes("2.0.0")))
        channel = manifest.load_verified_channel(
            document, sign_document(self.seed, self.key_id, document)
        )
        with mock.patch.object(remote, "fetch_channel", return_value=channel):
            service.check_channel(force=True)
        reloaded = remote.load_cache(self.layout.remote_cache)
        self.assertEqual(reloaded.version, "2.0.0")
        self.assertTrue(reloaded.successful)

    def test_failed_refresh_retains_the_last_verified_channel_result(self):
        service = self.service(software_update_check_enabled=True)
        service._channel = self.ok_channel("1.0.0")
        with mock.patch.object(
            remote,
            "fetch_channel",
            side_effect=remote.ChannelError("temporarily unavailable"),
        ):
            status = service.check_channel(force=True)
        self.assertEqual(status.latest_version, "1.0.0")
        self.assertTrue(status.channel.successful)
        self.assertIn("retained", status.headline)
        self.assertIn("temporarily unavailable", status.detail)

    def test_a_damaged_cache_is_ignored_rather_than_trusted(self):
        self.layout.ensure_directories()
        self.layout.remote_cache.write_text("{ not json", encoding="utf-8")
        self.assertIsNone(remote.load_cache(self.layout.remote_cache))
        self.layout.remote_cache.write_text('{"schema_version": 9}', encoding="utf-8")
        self.assertIsNone(remote.load_cache(self.layout.remote_cache))

    def test_restart_mechanism_reflects_how_the_process_was_started(self):
        service = self.service()
        with mock.patch.dict("os.environ", {"INVOCATION_ID": "abc"}, clear=False):
            self.assertEqual(service.restart_mechanism(), RESTART_SUPERVISOR)
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(service.restart_mechanism(), RESTART_UNSUPPORTED)


if __name__ == "__main__":
    unittest.main()
