import copy
import json
import unittest
from unittest import mock

from floorterminal.update import manifest, trust, version

from .update_fixtures import (
    channel_document,
    encode,
    executable_bytes,
    make_key,
    package_document,
    sign_document,
)


class ManifestVerificationTests(unittest.TestCase):
    def setUp(self):
        self.seed, self.key_id, self.anchor = make_key()
        patcher = mock.patch.object(trust, "TRUSTED_KEYS", (self.anchor,))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.artifact = executable_bytes("1.1.0")

    def signed(self, document):
        body = encode(document)
        return body, sign_document(self.seed, self.key_id, body)

    def test_accepts_a_correctly_signed_package(self):
        body, signature = self.signed(package_document(artifact=self.artifact))
        package = manifest.load_verified_package(body, signature)
        self.assertEqual(package.release.version, "1.1.0")
        self.assertEqual(package.signing_key_id, self.key_id)
        self.assertEqual(package.release.artifact_size_bytes, len(self.artifact))
        self.assertEqual(
            package.release.highlights()[0], ("NEW", "Signed offline USB software updates")
        )

    def test_rejects_a_single_altered_byte_of_metadata(self):
        document = package_document(artifact=self.artifact)
        body, signature = self.signed(document)
        tampered = body.replace(b'"1.1.0"', b'"9.9.9"', 1)
        self.assertNotEqual(tampered, body)
        with self.assertRaisesRegex(manifest.ManifestError, "signature does not match"):
            manifest.load_verified_package(tampered, signature)

    def test_rejects_a_signature_from_an_untrusted_key(self):
        other_seed, other_id, _ = make_key()
        body = encode(package_document(artifact=self.artifact))
        signature = sign_document(other_seed, other_id, body)
        with self.assertRaisesRegex(manifest.ManifestError, "does not trust"):
            manifest.load_verified_package(body, signature)

    def test_rejects_a_signature_that_claims_a_trusted_key_it_does_not_hold(self):
        """Naming a trusted key id cannot substitute for holding its private key."""
        other_seed, _, _ = make_key()
        body = encode(package_document(artifact=self.artifact))
        signature = sign_document(other_seed, self.key_id, body)
        with self.assertRaisesRegex(manifest.ManifestError, "signature does not match"):
            manifest.load_verified_package(body, signature)

    def test_rejects_unsupported_signature_envelopes(self):
        body = encode(package_document(artifact=self.artifact))
        good = json.loads(sign_document(self.seed, self.key_id, body))
        for mutation in (
            {"algorithm": "hmac-sha256"},
            {"schema_version": 2},
            {"key_id": "zzzz"},
            {"signature": "not base64!"},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(manifest.ManifestError):
                manifest.load_verified_package(body, encode({**good, **mutation}))
        with self.assertRaises(manifest.ManifestError):
            manifest.load_verified_package(body, encode({**good, "extra": 1}))

    def test_rejects_documents_for_another_product_type_or_target(self):
        for mutation in (
            {"product_id": "some-other-console"},
            {"document_type": manifest.CHANNEL_DOCUMENT},
            {"schema_version": 7},
            {"target": "linux/x86_64"},
        ):
            document = {**package_document(artifact=self.artifact), **mutation}
            body, signature = self.signed(document)
            with self.subTest(mutation=mutation), self.assertRaises(manifest.ManifestError):
                manifest.load_verified_package(body, signature)

    def test_rejects_unknown_fields_anywhere_in_the_document(self):
        document = package_document(artifact=self.artifact)
        for path, mutation in (
            ("root", {"unexpected": True}),
            ("release", {"unexpected": True}),
            ("artifact", {"unexpected": True}),
        ):
            candidate = copy.deepcopy(document)
            target = {
                "root": candidate,
                "release": candidate["release"],
                "artifact": candidate["release"]["artifact"],
            }[path]
            target.update(mutation)
            body, signature = self.signed(candidate)
            with self.subTest(path=path), self.assertRaises(manifest.ManifestError):
                manifest.load_verified_package(body, signature)

    def test_rejects_out_of_range_and_malformed_values(self):
        base = package_document(artifact=self.artifact)
        mutations = (
            ("version", "not-a-version"),
            ("released_utc", "14 November 2026"),
            ("release_title", "x" * 400),
            ("release_summary", ""),
            ("notes_url", "https://example.invalid/release"),
            ("minimum_upgradable_version", "1.0"),
        )
        for field, value in mutations:
            candidate = copy.deepcopy(base)
            candidate["release"][field] = value
            body, signature = self.signed(candidate)
            with self.subTest(field=field), self.assertRaises(manifest.ManifestError):
                manifest.load_verified_package(body, signature)

    def test_rejects_an_artifact_named_anything_but_the_application(self):
        candidate = package_document(artifact=self.artifact)
        candidate["release"]["artifact"]["name"] = "../../etc/passwd"
        body, signature = self.signed(candidate)
        with self.assertRaisesRegex(manifest.ManifestError, "must be named"):
            manifest.load_verified_package(body, signature)

    def test_rejects_artifact_sizes_outside_the_safety_bounds(self):
        for size in (0, trust.MIN_ARTIFACT_BYTES - 1, trust.MAX_ARTIFACT_BYTES + 1):
            candidate = package_document(artifact=self.artifact)
            candidate["release"]["artifact"]["size_bytes"] = size
            body, signature = self.signed(candidate)
            with self.subTest(size=size), self.assertRaises(manifest.ManifestError):
                manifest.load_verified_package(body, signature)

    def test_rejects_oversized_and_non_json_metadata(self):
        oversized = b"{" + b" " * (trust.MAX_MANIFEST_BYTES + 10) + b"}"
        signature = sign_document(self.seed, self.key_id, oversized)
        with self.assertRaisesRegex(manifest.ManifestError, "safety limit"):
            manifest.load_verified_package(oversized, signature)
        broken = b"{not json"
        with self.assertRaises(manifest.ManifestError):
            manifest.load_verified_package(
                broken, sign_document(self.seed, self.key_id, broken)
            )

    def test_bounds_the_number_and_length_of_change_entries(self):
        candidate = package_document(artifact=self.artifact)
        candidate["release"]["features"] = ["entry"] * 40
        body, signature = self.signed(candidate)
        with self.assertRaises(manifest.ManifestError):
            manifest.load_verified_package(body, signature)
        candidate["release"]["features"] = ["x" * 400]
        body, signature = self.signed(candidate)
        with self.assertRaises(manifest.ManifestError):
            manifest.load_verified_package(body, signature)

    def test_strips_control_characters_by_rejecting_them(self):
        candidate = package_document(artifact=self.artifact)
        candidate["release"]["release_title"] = "Release\x1b[2Jtitle"
        body, signature = self.signed(candidate)
        with self.assertRaisesRegex(manifest.ManifestError, "control characters"):
            manifest.load_verified_package(body, signature)

    def test_channel_documents_use_the_same_verification_path(self):
        body, signature = self.signed(channel_document(artifact=self.artifact))
        channel = manifest.load_verified_channel(body, signature)
        self.assertEqual(channel.release.version, "1.1.0")
        self.assertEqual(channel.signing_key_id, self.key_id)
        self.assertIn(trust.SUPPORTED_TARGETS[0], channel.targets)
        self.assertTrue(channel.archive_name.endswith(".tar.gz"))
        with self.assertRaises(manifest.ManifestError):
            manifest.load_verified_channel(
                *self.signed(package_document(artifact=self.artifact))
            )

    def test_rejects_release_metadata_that_predates_the_signing_key(self):
        candidate = package_document(artifact=self.artifact)
        candidate["release"]["released_utc"] = "2025-12-31T23:59:59Z"
        body, signature = self.signed(candidate)
        with self.assertRaisesRegex(manifest.ManifestError, "predates"):
            manifest.load_verified_package(body, signature)


class VersionOrderingTests(unittest.TestCase):
    def test_orders_releases_and_candidates_correctly(self):
        ordered = ["1.0.0", "1.0.1", "1.2.0", "2.0.0", "10.0.0"]
        self.assertEqual(max(ordered, key=version.parse), "10.0.0")
        self.assertEqual(
            sorted(ordered, key=version.parse), ["1.0.0", "1.0.1", "1.2.0", "2.0.0", "10.0.0"]
        )
        self.assertTrue(version.is_newer("1.0.1", "1.0.0"))
        self.assertFalse(version.is_newer("1.0.0", "1.0.0"))
        self.assertFalse(version.is_newer("0.9.9", "1.0.0"))
        self.assertTrue(version.is_newer("1.1.0", "1.1.0-rc.2"))
        self.assertTrue(version.is_newer("1.1.0-rc.2", "1.1.0-rc.1"))
        self.assertEqual(version.compare("1.0.0", "1.0.0"), 0)

    def test_rejects_ambiguous_or_hostile_version_text(self):
        for value in ("", "1.0", "v1.0.0", "1.0.0.0", "1.0.0+build", "99999.0.0", None):
            with self.subTest(value=value):
                self.assertIsNone(version.try_parse(value))
                with self.assertRaises(version.VersionError):
                    version.parse(value)


if __name__ == "__main__":
    unittest.main()
