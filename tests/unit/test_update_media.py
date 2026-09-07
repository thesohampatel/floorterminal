import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from floorterminal.update import media, trust
from floorterminal.update.layout import InstallLayout

from .update_fixtures import (
    build_installation,
    encode,
    executable_bytes,
    make_key,
    package_document,
    sign_document,
    write_update_drive,
)


class RemovableMediaTests(unittest.TestCase):
    def setUp(self):
        self.seed, self.key_id, anchor = make_key()
        patcher = mock.patch.object(trust, "TRUSTED_KEYS", (anchor,))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.work = Path(tempfile.mkdtemp())
        self.addCleanup(
            lambda: __import__("shutil").rmtree(self.work, ignore_errors=True)
        )
        self.mount_root = self.work / "media"
        self.mount = self.mount_root / "kiosk" / trust.UPDATE_VOLUME_LABELS[0]
        self.mount.mkdir(parents=True)
        self.artifact = executable_bytes("1.1.0")
        write_update_drive(self.mount, self.seed, self.key_id, artifact=self.artifact)
        self.layout = InstallLayout(build_installation(self.work / "opt"))

    def drive(self, name):
        target = self.mount_root / "kiosk" / name
        target.mkdir(parents=True, exist_ok=True)
        return write_update_drive(
            target, self.seed, self.key_id, artifact=self.artifact
        )

    def test_only_hardcoded_volume_labels_trigger_automatic_detection(self):
        self.drive("HOLIDAY_PHOTOS")
        found = media.candidate_mounts(roots=[str(self.mount_root)])
        self.assertEqual([path.name for path in found], [trust.UPDATE_VOLUME_LABELS[0]])
        wide = media.candidate_mounts(labelled_only=False, roots=[str(self.mount_root)])
        self.assertIn("HOLIDAY_PHOTOS", [path.name for path in wide])

    def test_every_accepted_label_is_short_enough_for_fat32_and_exfat(self):
        self.assertLessEqual(len(trust.UPDATE_VOLUME_LABELS[0]), 11)
        for label in trust.UPDATE_VOLUME_LABELS:
            with self.subTest(label=label):
                self.assertTrue(label.isupper())
                self.assertLessEqual(len(label), 32)

    def test_reads_and_verifies_a_correct_package(self):
        package = media.read_package(self.mount)
        self.assertEqual(package.version, "1.1.0")
        self.assertEqual(package.package.signing_key_id, self.key_id)
        self.assertEqual(
            media.verify_artifact(package), package.release.artifact_sha256
        )
        self.assertEqual(media.check_installable(package, "1.0.0"), "")

    def test_rejects_an_artifact_that_does_not_match_the_signed_digest(self):
        artifact = self.mount / trust.UPDATE_PACKAGE_DIRNAME / trust.EXECUTABLE_NAME
        artifact.write_bytes(executable_bytes("tampered"))
        package = media.read_package(self.mount)
        with self.assertRaisesRegex(
            media.MediaError, "checksum does not match|is [0-9]+ bytes"
        ):
            media.verify_artifact(package)
        with self.assertRaises(media.MediaError):
            media.stage(self.layout, package, expect_executable=False)
        self.assertEqual(list(self.layout.staging_dir.glob("*")), [])

    def test_refuses_a_missing_manifest_signature_or_artifact(self):
        package_dir = self.mount / trust.UPDATE_PACKAGE_DIRNAME
        for name in (trust.SIGNATURE_NAME, trust.MANIFEST_NAME, trust.EXECUTABLE_NAME):
            with self.subTest(missing=name):
                backup = (package_dir / name).read_bytes()
                (package_dir / name).unlink()
                with self.assertRaises(media.MediaError):
                    media.read_package(self.mount)
                (package_dir / name).write_bytes(backup)

    def test_refuses_to_follow_symbolic_links_on_the_medium(self):
        package_dir = self.mount / trust.UPDATE_PACKAGE_DIRNAME
        secret = self.work / "secret.json"
        secret.write_text("{}", encoding="utf-8")
        (package_dir / trust.MANIFEST_NAME).unlink()
        os.symlink(secret, package_dir / trust.MANIFEST_NAME)
        with self.assertRaisesRegex(media.MediaError, "symbolic link"):
            media.read_package(self.mount)

    def test_refuses_a_package_directory_that_is_a_symbolic_link(self):
        elsewhere = self.mount_root / "kiosk" / "ELSEWHERE"
        write_update_drive(elsewhere, self.seed, self.key_id, artifact=self.artifact)
        linked = self.mount_root / "kiosk" / "LINKED"
        linked.mkdir()
        os.symlink(
            elsewhere / trust.UPDATE_PACKAGE_DIRNAME,
            linked / trust.UPDATE_PACKAGE_DIRNAME,
        )
        with self.assertRaisesRegex(media.MediaError, "symbolic link"):
            media.read_package(linked)

    def test_refuses_metadata_larger_than_the_safety_limit(self):
        path = self.mount / trust.UPDATE_PACKAGE_DIRNAME / trust.MANIFEST_NAME
        path.write_bytes(b"{}" + b" " * (trust.MAX_MANIFEST_BYTES + 100))
        with self.assertRaisesRegex(media.MediaError, "safety limit"):
            media.read_package(self.mount)

    def test_refuses_a_package_older_than_or_equal_to_the_running_version(self):
        package = media.read_package(self.mount)
        self.assertIn("already installed", media.check_installable(package, "1.1.0"))
        older = self.mount_root / "kiosk" / "FLOOR-TERM"
        write_update_drive(
            older, self.seed, self.key_id, "1.0.0", artifact=self.artifact
        )
        self.assertIn(
            "already installed",
            media.check_installable(media.read_package(older), "1.0.0"),
        )

    def test_older_signed_media_cannot_downgrade_the_running_version(self):
        package = media.read_package(self.mount)
        self.assertIn("older", media.check_installable(package, "1.2.0"))

    def test_staging_keeps_the_exact_authenticated_manifest_and_signature(self):
        package = media.read_package(self.mount)
        staged = media.stage(self.layout, package)
        self.assertEqual(
            (staged.parent / trust.MANIFEST_NAME).read_bytes(), package.manifest_bytes
        )
        self.assertEqual(
            (staged.parent / trust.SIGNATURE_NAME).read_bytes(), package.signature_bytes
        )
        self.assertEqual(
            media.verify_local_package(staged.parent, "1.1.0").version, "1.1.0"
        )

    def test_refuses_a_package_whose_minimum_upgrade_floor_is_not_met(self):
        target = self.mount_root / "kiosk" / "FTERM_UPD"
        document = package_document("2.0.0", artifact=self.artifact, minimum="1.5.0")
        write_update_drive(
            target, self.seed, self.key_id, artifact=self.artifact, document=document
        )
        package = media.read_package(target)
        self.assertIn("1.5.0 or newer", media.check_installable(package, "1.0.0"))
        self.assertEqual(media.check_installable(package, "1.5.0"), "")

    def test_staging_copies_verifies_and_records_the_release(self):
        package = media.read_package(self.mount)
        staged = media.stage(self.layout, package, expect_executable=True)
        self.assertTrue(staged.is_file())
        self.assertEqual(staged.read_bytes(), self.artifact)
        self.assertEqual(oct(staged.stat().st_mode)[-3:], "700")
        record = staged.parent / "release.json"
        self.assertTrue(record.is_file())
        self.assertIn("Reliability", record.read_text(encoding="utf-8"))
        self.assertEqual(oct(record.stat().st_mode)[-3:], "600")

    def test_staging_rejects_a_non_executable_payload_for_a_linux_target(self):
        artifact = (
            b"#!/bin/sh\necho not an ELF binary\n" + b"\x00" * trust.MIN_ARTIFACT_BYTES
        )
        target = self.mount_root / "kiosk" / "FT_UPDATE"
        write_update_drive(target, self.seed, self.key_id, artifact=artifact)
        package = media.read_package(target)
        with self.assertRaisesRegex(media.MediaError, "not a Linux executable"):
            media.stage(self.layout, package, expect_executable=True)
        self.assertEqual(list(self.layout.staging_dir.glob("*")), [])

    def test_staging_refuses_when_free_space_is_insufficient(self):
        package = media.read_package(self.mount)
        usage = mock.Mock(free=1024)
        with (
            mock.patch("shutil.disk_usage", return_value=usage),
            self.assertRaisesRegex(media.MediaError, "not enough to stage"),
        ):
            media.stage(self.layout, package, expect_executable=False)

    def test_media_log_mirrors_events_and_never_raises_on_failure(self):
        self.assertTrue(media.mirror_log(self.mount, "update_staged", version="1.1.0"))
        logs = list((self.mount / trust.MEDIA_LOG_DIRNAME).glob("*.jsonl"))
        self.assertEqual(len(logs), 1)
        self.assertIn("update_staged", logs[0].read_text(encoding="utf-8"))
        blocked = self.work / "not-a-directory"
        blocked.write_text("this is a file, not a mount point", encoding="utf-8")
        self.assertFalse(media.mirror_log(blocked, "update_staged"))

    def test_terminal_identity_is_short_and_filesystem_safe(self):
        name = media.terminal_identity()
        self.assertTrue(name)
        self.assertLessEqual(len(name), 32)
        self.assertTrue(all(ch.isalnum() or ch in "-_" for ch in name))

    def test_signature_replay_from_another_package_is_rejected(self):
        """A valid signature for a different manifest cannot authorize this one."""
        other = encode(package_document("2.0.0", artifact=self.artifact))
        signature = sign_document(self.seed, self.key_id, other)
        (self.mount / trust.UPDATE_PACKAGE_DIRNAME / trust.SIGNATURE_NAME).write_bytes(
            signature
        )
        with self.assertRaisesRegex(media.MediaError, "signature does not match"):
            media.read_package(self.mount)


if __name__ == "__main__":
    unittest.main()
