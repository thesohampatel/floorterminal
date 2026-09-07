"""Offline multi-release, recovery and signed-cache regression scenarios."""

import dataclasses
import itertools
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from floorterminal.update import (
    installer,
    journal,
    manifest,
    media,
    remote,
    trust,
    version,
)
from floorterminal.update.layout import InstallLayout
from floorterminal.update.service import LEVEL_ATTENTION, UpdateService

from .update_fixtures import (
    build_installation,
    channel_document,
    encode,
    executable_bytes,
    make_key,
    package_document,
    sign_document,
    write_update_drive,
)


class MultipleReleaseTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.work, True)
        self.seed, self.key_id, anchor = make_key()
        patcher = mock.patch.object(trust, "TRUSTED_KEYS", (anchor,))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.layout = InstallLayout(build_installation(self.work / "installation"))
        self.media_root = self.work / "media"

    def service(self, installed="1.0.0"):
        service = UpdateService(
            {"software_update_check_enabled": False},
            layout=self.layout,
            media_roots=[str(self.media_root)],
        )
        service.installed_version = installed
        service.prepare()
        return service

    def drive(self, release, label="FLOORTERM", minimum="1.0.0", marker=None):
        payload = executable_bytes(marker or release)
        document = package_document(release, artifact=payload, minimum=minimum)
        mount = self.media_root / label
        write_update_drive(
            mount, self.seed, self.key_id, release, artifact=payload, document=document
        )
        return mount

    def stage(self, release, minimum="1.0.0"):
        mount = self.drive(release, minimum=minimum)
        return media.stage(self.layout, media.read_package(mount))

    def channel(self, release, **overrides):
        payload = encode(
            channel_document(release, artifact=executable_bytes(release), **overrides)
        )
        return manifest.load_verified_channel(
            payload, sign_document(self.seed, self.key_id, payload)
        )

    def test_three_drives_select_numeric_newest_regardless_of_discovery_order(self):
        mounts = [
            self.drive("1.9.0", "FLOORTERM"),
            self.drive("1.10.0", "FLOOR-TERM"),
            self.drive("2.0.0", "FTERM_UPD"),
        ]
        service = self.service()
        for order in itertools.permutations(mounts):
            with (
                self.subTest(order=order),
                mock.patch.object(media, "candidate_mounts", return_value=order),
            ):
                snapshot = service.refresh(scan_media=True)
                self.assertEqual(snapshot.staged.version, "2.0.0")
                self.assertEqual(installer.staged_versions(self.layout), ("2.0.0",))

    def test_an_older_drive_cannot_replace_a_newer_staged_version(self):
        self.stage("2.0.0")
        self.drive("1.1.0")
        snapshot = self.service().refresh(scan_media=True)
        self.assertEqual(snapshot.staged.version, "2.0.0")

    def test_incompatible_latest_falls_back_to_an_intermediate_release(self):
        self.drive("3.0.0", minimum="2.0.0")
        self.drive("2.0.0", "FTERM_UPD")
        snapshot = self.service().refresh(scan_media=True)
        self.assertEqual(snapshot.staged.version, "2.0.0")
        self.assertIn("can only be installed", snapshot.media_error)
        self.assertTrue(snapshot.can_install)
        self.assertEqual(snapshot.level, LEVEL_ATTENTION)

    def test_a_staged_release_is_rechecked_against_the_current_upgrade_floor(self):
        self.stage("3.0.0", minimum="2.0.0")
        service = self.service()
        self.assertIsNone(service.status().staged)
        with self.assertRaisesRegex(installer.ActivationError, "can only be installed"):
            installer.activate(self.layout, "3.0.0")
        self.assertEqual(self.layout.active_version(), "1.0.0")

    def test_stable_terminals_do_not_pick_release_candidates(self):
        self.drive("3.0.0-rc.1")
        self.drive("2.0.0", "FTERM_UPD")
        snapshot = self.service().refresh(scan_media=True)
        self.assertEqual(snapshot.staged.version, "2.0.0")
        self.assertIn("release candidate", snapshot.media_error)

    def test_conflicting_signed_packages_for_one_version_are_not_installable(self):
        self.drive("2.0.0")
        self.drive("2.0.0", "FTERM_UPD", marker="different")
        snapshot = self.service().refresh(scan_media=True)
        self.assertIsNone(snapshot.staged)
        self.assertIn("Conflicting", snapshot.media_error)
        self.assertFalse(snapshot.can_install)

    def test_conflicts_cannot_silently_replace_a_previously_staged_copy(self):
        original = self.stage("2.0.0").read_bytes()
        self.drive("2.0.0", marker="different")
        service = self.service()
        snapshot = service.refresh(scan_media=True)
        self.assertIsNone(snapshot.staged)
        self.assertFalse(service.refresh().can_install)
        self.assertEqual(
            (self.layout.staging_dir / "2.0.0" / trust.EXECUTABLE_NAME).read_bytes(),
            original,
        )

    def test_identical_duplicate_packages_are_deduplicated(self):
        self.drive("2.0.0")
        self.drive("2.0.0", "FTERM_UPD")
        service = self.service()
        first = service.refresh(scan_media=True)
        path = self.layout.staging_dir / "2.0.0" / trust.EXECUTABLE_NAME
        stamp = path.stat().st_mtime_ns
        second = service.refresh(scan_media=True)
        self.assertEqual(first.staged.artifact_sha256, second.staged.artifact_sha256)
        self.assertEqual(path.stat().st_mtime_ns, stamp)
        self.assertEqual(second.candidate_versions, ("2.0.0",))

    def test_a_corrupt_newest_payload_does_not_hide_a_valid_older_package(self):
        broken = self.drive("3.0.0")
        (broken / trust.UPDATE_PACKAGE_DIRNAME / trust.EXECUTABLE_NAME).write_bytes(
            b"broken"
        )
        self.drive("2.0.0", "FTERM_UPD")
        snapshot = self.service().refresh(scan_media=True)
        self.assertEqual(snapshot.staged.version, "2.0.0")
        self.assertIn("signed manifest", snapshot.media_error)

    def test_one_drive_can_hold_multiple_separately_signed_version_directories(self):
        mount = self.media_root / "FLOORTERM"
        package_root = mount / trust.UPDATE_PACKAGE_DIRNAME
        for release in ("1.1.0", "2.0.0", "3.0.0"):
            temp_mount = self.work / release
            write_update_drive(temp_mount, self.seed, self.key_id, release)
            package_root.mkdir(parents=True, exist_ok=True)
            shutil.move(
                str(temp_mount / trust.UPDATE_PACKAGE_DIRNAME), package_root / release
            )
        snapshot = self.service().refresh(scan_media=True)
        self.assertEqual(snapshot.staged.version, "3.0.0")

    def test_version_subdirectory_cannot_relabel_a_signed_package(self):
        mount = self.drive("2.0.0")
        root = mount / trust.UPDATE_PACKAGE_DIRNAME
        temporary = mount / "held"
        root.rename(temporary)
        root.mkdir()
        temporary.rename(root / "3.0.0")
        snapshot = self.service().refresh(scan_media=True)
        self.assertIsNone(snapshot.staged)
        self.assertIn("does not match", snapshot.media_error)

    def test_nested_symlinks_are_rejected(self):
        mount = self.media_root / "FLOORTERM" / trust.UPDATE_PACKAGE_DIRNAME
        mount.mkdir(parents=True)
        other = self.drive("2.0.0", "outside")
        os.symlink(other / trust.UPDATE_PACKAGE_DIRNAME, mount / "2.0.0")
        snapshot = self.service().refresh(scan_media=True)
        self.assertIsNone(snapshot.staged)
        self.assertIn("symbolic link", snapshot.media_error)

    def test_already_installed_or_older_media_never_downgrades(self):
        self.drive("1.0.0")
        snapshot = self.service().refresh(scan_media=True)
        self.assertFalse(snapshot.can_install)
        self.assertIn("already installed", snapshot.media_error)

    def test_authorization_is_bound_to_the_version_that_was_reviewed(self):
        service = self.service()
        self.drive("1.1.0")
        selected = service.refresh(scan_media=True).staged
        self.drive("2.0.0")
        service.refresh(scan_media=True)
        with self.assertRaisesRegex(installer.ActivationError, "changed"):
            service.install_staged(
                authorized_by="Site administrator",
                expected_version=selected.version,
                expected_sha256=selected.artifact_sha256,
            )
        self.assertEqual(self.layout.active_version(), "1.0.0")

    def test_authorization_is_bound_to_the_exact_payload(self):
        self.drive("2.0.0")
        service = self.service()
        service.refresh(scan_media=True)
        with self.assertRaisesRegex(installer.ActivationError, "changed"):
            service.install_staged(expected_version="2.0.0", expected_sha256="f" * 64)
        self.assertEqual(self.layout.active_version(), "1.0.0")

    def test_old_process_cannot_confirm_the_new_slot_before_restart(self):
        self.drive("2.0.0")
        service = self.service()
        service.refresh(scan_media=True)
        service.install_staged()
        service._started_monotonic -= trust.PROBATION_DWELL_SECONDS + 5
        service._maybe_confirm()
        self.assertEqual(
            journal.read_journal(self.layout.journal).state, journal.STATE_PROBATION
        )
        self.assertTrue(service.status().restart_required)
        self.assertFalse(service.status().can_install)

    def test_probation_prevents_stacking_a_second_upgrade(self):
        self.stage("2.0.0")
        installer.activate(self.layout, "2.0.0")
        self.stage("3.0.0")
        with self.assertRaisesRegex(installer.ActivationError, "confirmed"):
            installer.activate(self.layout, "3.0.0")
        self.assertEqual(self.layout.active_version(), "2.0.0")
        follower = self.service("2.0.0")
        self.assertFalse(follower.refresh().can_install)

    def test_multiple_upgrades_retain_active_previous_and_one_extra_slot(self):
        for release in ("1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0"):
            self.stage(release)
            installer.activate(self.layout, release)
            installer.confirm(self.layout)
        self.assertEqual(
            set(self.layout.installed_versions()), {"1.3.0", "1.4.0", "1.5.0"}
        )
        self.assertEqual(installer.rollback_target(self.layout), "1.4.0")
        installer.rollback(self.layout)
        self.assertEqual(self.layout.active_version(), "1.4.0")
        self.assertEqual(installer.rollback_target(self.layout), "1.5.0")

    def test_failed_trial_is_not_offered_as_recovery_after_rollback(self):
        self.stage("2.0.0")
        installer.activate(self.layout, "2.0.0")
        installer.rollback(self.layout)
        self.assertIsNone(installer.rollback_target(self.layout))
        with self.assertRaisesRegex(installer.ActivationError, "accepted rollback"):
            installer.rollback(self.layout, "2.0.0")

    def test_an_untried_newer_slot_is_not_a_rollback_target(self):
        self.stage("2.0.0")
        installer.promote_staged(self.layout, "2.0.0")
        self.assertIsNone(installer.rollback_target(self.layout))
        with self.assertRaisesRegex(installer.ActivationError, "accepted rollback"):
            installer.rollback(self.layout, "2.0.0")

    def test_corrupt_retained_signed_payload_cannot_be_restored(self):
        for release in ("1.1.0", "2.0.0"):
            self.stage(release)
            installer.activate(self.layout, release)
            installer.confirm(self.layout)
        self.layout.slot_executable("1.1.0").write_bytes(executable_bytes("tampered"))
        with self.assertRaisesRegex(installer.ActivationError, "verification failed"):
            installer.rollback(self.layout)
        self.assertEqual(self.layout.active_version(), "2.0.0")

    def test_interrupted_new_staging_preserves_the_previous_candidate(self):
        old = self.stage("1.1.0")
        mount = self.drive("2.0.0")
        with (
            mock.patch.object(media.os, "replace", side_effect=OSError("interrupted")),
            self.assertRaises(media.MediaError),
        ):
            media.stage(self.layout, media.read_package(mount))
        self.assertTrue(old.is_file())
        self.assertFalse((self.layout.staging_dir / "2.0.0").exists())
        self.assertFalse(list(self.layout.staging_dir.glob(".copy-*")))

    def test_minimum_version_cannot_exceed_the_release(self):
        payload = encode(
            package_document("2.0.0", artifact=executable_bytes(), minimum="3.0.0")
        )
        with self.assertRaisesRegex(manifest.ManifestError, "Minimum"):
            manifest.load_verified_package(
                payload, sign_document(self.seed, self.key_id, payload)
            )

    def test_leading_zero_version_aliases_are_rejected(self):
        for value in ("01.0.0", "1.01.0", "1.0.01"):
            with self.subTest(value=value), self.assertRaises(version.VersionError):
                version.parse(value)

    def test_channel_upgrade_floor_is_explained_without_claiming_installability(self):
        service = self.service()
        service._channel = remote.result_from_channel(
            self.channel("3.0.0", minimum="2.0.0"), time.time()
        )
        snapshot = service.refresh()
        self.assertTrue(snapshot.update_available)
        self.assertIn("intermediate", snapshot.headline)
        self.assertIn("2.0.0 first", snapshot.detail)
        self.assertFalse(snapshot.can_install)

    def test_older_channel_cannot_replace_a_newer_verified_answer(self):
        service = self.service()
        service._channel = remote.result_from_channel(
            self.channel("3.0.0"), time.time()
        )
        with mock.patch.object(
            remote, "fetch_channel", return_value=self.channel("2.0.0")
        ):
            snapshot = service.check_channel(force=True)
        self.assertEqual(snapshot.latest_version, "3.0.0")
        self.assertIn("retained", snapshot.headline)

    def test_changed_payload_cannot_reuse_the_same_channel_version(self):
        old = remote.result_from_channel(self.channel("2.0.0"), time.time())
        changed = dataclasses.replace(old, artifact_sha256="b" * 64)
        with self.assertRaisesRegex(remote.ChannelError, "same release version"):
            remote.validate_progression(changed, old)

    def test_stale_newer_channel_is_labelled_as_stale(self):
        service = self.service()
        service._channel = remote.result_from_channel(
            self.channel("2.0.0"), time.time() - trust.CHECK_FRESHNESS_SECONDS - 1
        )
        self.assertIn("out of date", service.refresh().headline)

    def test_cached_display_fields_cannot_substitute_for_signed_metadata(self):
        path = self.layout.remote_cache
        result = remote.result_from_channel(self.channel("2.0.0"), time.time())
        remote.save_cache(path, result)
        data = json.loads(path.read_text())
        data["version"] = "99.0.0"
        data["release_title"] = "Untrusted title"
        path.write_text(json.dumps(data))
        loaded = remote.load_cache(path)
        self.assertEqual(loaded.version, "2.0.0")
        self.assertNotEqual(loaded.release_title, "Untrusted title")

    def test_corrupt_or_unsigned_cache_never_looks_verified(self):
        path = self.layout.remote_cache
        result = remote.result_from_channel(self.channel("2.0.0"), time.time())
        for mutation in (
            {"signature_base64": ""},
            {"document_base64": ""},
            {"checked_at_epoch": True},
            {"checked_at_epoch": float("inf")},
        ):
            remote.save_cache(path, result)
            data = json.loads(path.read_text())
            data.update(mutation)
            path.write_text(json.dumps(data))
            self.assertIsNone(remote.load_cache(path))

    def test_future_cache_clock_is_not_treated_as_fresh(self):
        result = remote.result_from_channel(self.channel("2.0.0"), time.time() + 3600)
        self.assertTrue(result.is_stale(time.time()))

    def test_wrong_processor_payload_cannot_be_staged(self):
        payload = bytearray(executable_bytes())
        payload[18:20] = (62).to_bytes(2, "little")
        mount = self.media_root / "FLOORTERM"
        write_update_drive(
            mount, self.seed, self.key_id, "2.0.0", artifact=bytes(payload)
        )
        with self.assertRaisesRegex(media.MediaError, "ARM64"):
            media.stage(self.layout, media.read_package(mount))
        self.assertFalse((self.layout.staging_dir / "2.0.0").exists())

    def test_multi_release_drive_can_complete_an_intermediate_upgrade_sequence(self):
        self.drive("3.0.0", minimum="2.0.0")
        self.drive("2.0.0", "FTERM_UPD")
        first = self.service()
        self.assertEqual(first.refresh(scan_media=True).staged.version, "2.0.0")
        first.install_staged()
        installer.confirm(self.layout)
        second = self.service("2.0.0")
        self.assertEqual(second.refresh(scan_media=True).staged.version, "3.0.0")
        second.install_staged()
        self.assertEqual(self.layout.active_version(), "3.0.0")

    def test_excess_version_directories_fail_closed(self):
        directory = self.media_root / "FLOORTERM" / trust.UPDATE_PACKAGE_DIRNAME
        directory.mkdir(parents=True)
        for index in range(65):
            (directory / f"1.{index}.0").mkdir()
        snapshot = self.service().refresh(scan_media=True)
        self.assertFalse(snapshot.can_install)
        self.assertIn("at most 64", snapshot.media_error)

    def test_incomplete_copy_workspaces_are_cleaned_at_restart(self):
        self.layout.ensure_directories()
        partial = self.layout.staging_dir / ".copy-interrupted"
        partial.mkdir()
        (partial / trust.EXECUTABLE_NAME).write_bytes(b"partial")
        self.service()
        self.assertFalse(partial.exists())
        self.assertEqual(self.layout.active_version(), "1.0.0")

    def test_simultaneous_checks_do_not_start_a_second_request(self):
        service = self.service()
        with service._check_lock, mock.patch.object(remote, "fetch_channel") as fetch:
            service.check_channel(force=True)
        fetch.assert_not_called()

    def test_archive_substitution_cannot_reuse_the_same_release_version(self):
        current = remote.result_from_channel(self.channel("2.0.0"), time.time())
        with self.assertRaises(remote.ChannelError):
            remote.validate_progression(
                dataclasses.replace(current, archive_sha256="c" * 64), current
            )

    def test_explicit_downgrade_cannot_bypass_the_activation_entry_point(self):
        self.stage("1.1.0")
        installer.activate(self.layout, "1.1.0")
        installer.confirm(self.layout)
        self.stage("1.0.0")
        with self.assertRaisesRegex(installer.ActivationError, "older"):
            installer.activate(self.layout, "1.0.0")
        self.assertEqual(self.layout.active_version(), "1.1.0")
