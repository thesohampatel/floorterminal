import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from floorterminal.core.project_profile import (
    ProjectProfileError,
    hash_settings_password,
    load_project_profile,
    verify_settings_password,
)

VALID = {
    "schema_version": 1,
    "settings_password": "Example@Admin",
    "product_name": "Factory Response Console",
    "product_short_name": "Response Console",
    "product_tagline": "Production maintenance terminal",
    "maintainer_name": "Example Maintainer",
    "distribution_name": "Community Test Profile",
    "support_contact": "support@example.invalid",
    "license_name": "MIT License",
    "license_identifier": "MIT",
    "license_version": "Standard",
    "license_summary": "Open-source use and redistribution with notice retention.",
    "copyright_notice": "Copyright 2026 Example Maintainer",
    "legal_notice": "Open-source operational software supplied without warranty.",
}


class ProjectProfileTests(unittest.TestCase):
    def write(self, data):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "project_profile.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return directory, path

    def test_valid_profile_loads(self):
        directory, path = self.write(VALID)
        try:
            profile = load_project_profile(path)
            self.assertEqual(profile.product_name, VALID["product_name"])
            self.assertEqual(profile.distribution_name, VALID["distribution_name"])
            self.assertTrue(
                verify_settings_password(
                    VALID["settings_password"], profile.settings_password_hash
                )
            )
            self.assertNotIn(VALID["settings_password"], profile.settings_password_hash)
        finally:
            directory.cleanup()

    def test_embedded_hash_profile_loads_without_plaintext_password(self):
        embedded = dict(VALID)
        password = embedded.pop("settings_password")
        embedded["settings_password_hash"] = hash_settings_password(
            password, bytes.fromhex("11" * 16)
        )
        directory, path = self.write(embedded)
        try:
            profile = load_project_profile(path)
            self.assertEqual(
                profile.settings_password_hash,
                embedded["settings_password_hash"],
            )
        finally:
            directory.cleanup()

    def test_short_or_duplicate_password_fields_are_rejected(self):
        short = dict(VALID)
        short["settings_password"] = "short"
        directory, path = self.write(short)
        try:
            with self.assertRaises(ProjectProfileError):
                load_project_profile(path)
        finally:
            directory.cleanup()

        duplicate = dict(VALID)
        duplicate["settings_password_hash"] = hash_settings_password(
            "AnotherPassword@1", bytes.fromhex("22" * 16)
        )
        directory, path = self.write(duplicate)
        try:
            with self.assertRaises(ProjectProfileError):
                load_project_profile(path)
        finally:
            directory.cleanup()

    def test_non_mit_license_identity_is_rejected(self):
        invalid = dict(VALID)
        invalid["license_identifier"] = "LicenseRef-Custom"
        directory, path = self.write(invalid)
        try:
            with self.assertRaises(ProjectProfileError):
                load_project_profile(path)
        finally:
            directory.cleanup()

    def test_missing_or_unknown_fields_are_rejected(self):
        invalid = dict(VALID)
        invalid.pop("maintainer_name")
        invalid["unsupported_extra"] = "not allowed"
        directory, path = self.write(invalid)
        try:
            with self.assertRaises(ProjectProfileError):
                load_project_profile(path)
        finally:
            directory.cleanup()

    def test_plain_sha256_embedded_password_is_rejected(self):
        embedded = dict(VALID)
        embedded.pop("settings_password")
        embedded["settings_password_hash"] = "0" * 64
        directory, path = self.write(embedded)
        try:
            with self.assertRaises(ProjectProfileError):
                load_project_profile(path)
        finally:
            directory.cleanup()

    def test_public_placeholder_password_is_rejected(self):
        profile = dict(VALID)
        profile["settings_password"] = "CHANGE_THIS_BEFORE_BUILD"
        directory, path = self.write(profile)
        try:
            with self.assertRaisesRegex(ProjectProfileError, "placeholder"):
                load_project_profile(path)
        finally:
            directory.cleanup()

    def test_environment_placeholder_requires_a_secret(self):
        profile = dict(VALID)
        profile["settings_password"] = "${FLOORTERMINAL_SETTINGS_PASSWORD}"
        directory, path = self.write(profile)
        try:
            with (
                mock.patch.dict(os.environ, {}, clear=True),
                self.assertRaisesRegex(
                    ProjectProfileError, "FLOORTERMINAL_SETTINGS_PASSWORD"
                ),
            ):
                load_project_profile(path)
        finally:
            directory.cleanup()


if __name__ == "__main__":
    unittest.main()
