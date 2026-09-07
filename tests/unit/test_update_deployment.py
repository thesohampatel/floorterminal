import json
import re
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

from floorterminal import __version__
from floorterminal.core.config import (
    CONFIG_KEYS,
    DEFAULT_CONFIG,
    validate_config,
)
from floorterminal.update import catalog, manifest, remote, trust

from .update_fixtures import (
    channel_document,
    encode,
    executable_bytes,
    make_key,
    sign_document,
)

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "packaging" / "linux" / "floorterminal-launch"
INSTALLER = ROOT / "packaging" / "linux" / "install.sh"
SERVICE = ROOT / "packaging" / "linux" / "floorterminal.service"
BUILDER = ROOT / "scripts" / "build" / "build.py"
PI_SCRIPT = ROOT / "scripts" / "install" / "prepare_release_on_pi.sh"


class ImmutableUpdatePolicyTests(unittest.TestCase):
    """The update source must not be reachable through configuration."""

    def test_publication_identity_matches_the_canonical_repository(self):
        # Independent expectations catch a consistently wrong owner that would
        # otherwise pass checks comparing only derived URLs with one another.
        project = "https://github.com/thesohampatel/floorterminal"
        self.assertEqual(trust.PROJECT_URL, project)
        self.assertEqual(trust.RELEASES_URL, project + "/releases")
        self.assertEqual(
            trust.UPDATE_GUIDE_URL, project + "/blob/main/docs/update-user-guide.md"
        )
        self.assertEqual(
            trust.UPDATE_CHANNEL_URL,
            "https://raw.githubusercontent.com/thesohampatel/floorterminal/main/update-channel/latest.json",
        )
        self.assertEqual(remote.SIGNATURE_URL, trust.UPDATE_CHANNEL_URL + ".sig")
        self.assertEqual(trust.MAINTAINER_EMAIL, "sohampatel1782@gmail.com")

    def test_fetch_uses_the_correct_paths_and_verifies_the_response(self):
        seed, key_id, anchor = make_key()
        data = channel_document(artifact=executable_bytes())
        data["release"]["notes_url"] = (
            "https://github.com/thesohampatel/floorterminal/releases/tag/v1.1.0"
        )
        body = encode(data)
        signature = sign_document(seed, key_id, body)
        calls = []
        expected = "https://raw.githubusercontent.com/thesohampatel/floorterminal/main/update-channel/latest.json"

        def fetch(url, maximum):
            calls.append((url, maximum))
            return {expected: body, expected + ".sig": signature}[url]

        with mock.patch.object(trust, "TRUSTED_KEYS", (anchor,)):
            result = remote.fetch_channel(fetcher=fetch)
        self.assertEqual(result.release.version, "1.1.0")
        self.assertEqual(result.release.notes_url, data["release"]["notes_url"])
        self.assertEqual(result.signing_key_id, key_id)
        self.assertEqual(
            calls,
            [
                (expected, trust.MAX_CHANNEL_RESPONSE_BYTES),
                (expected + ".sig", trust.MAX_SIGNATURE_BYTES),
            ],
        )

    def test_trusted_signature_does_not_allow_notes_from_another_repository(self):
        seed, key_id, anchor = make_key()
        for notes_url in (
            "https://github.com/another-maintainer/floorterminal/releases/tag/v1.1.0",
            "https://github.com/thesohampatel/floorterminal-untrusted/releases/tag/v1.1.0",
        ):
            document = channel_document(artifact=executable_bytes())
            document["release"]["notes_url"] = notes_url
            body = encode(document)
            signature = sign_document(seed, key_id, body)
            with (
                self.subTest(notes_url=notes_url),
                mock.patch.object(trust, "TRUSTED_KEYS", (anchor,)),
                self.assertRaisesRegex(
                    manifest.ManifestError, "official project repository"
                ),
            ):
                manifest.load_verified_channel(body, signature)

    def test_documented_project_links_use_the_canonical_owner(self):
        pattern = re.compile(
            r"https://(?:github\.com|raw\.githubusercontent\.com)/([^/\s]+)/floorterminal(?:/|\b)"
        )
        for path in [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]:
            for owner in pattern.findall(path.read_text(encoding="utf-8")):
                with self.subTest(
                    document=path.relative_to(ROOT).as_posix(), owner=owner
                ):
                    self.assertEqual(owner, "thesohampatel")

    def test_the_update_endpoint_is_https_on_the_single_declared_host(self):
        parsed = urlparse(trust.UPDATE_CHANNEL_URL)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.hostname, trust.UPDATE_CHANNEL_HOST)
        for url in (trust.PROJECT_URL, trust.RELEASES_URL, trust.UPDATE_GUIDE_URL):
            with self.subTest(url=url):
                self.assertTrue(url.startswith("https://github.com/"))

    def test_no_configuration_key_can_redirect_or_relabel_the_update_source(self):
        forbidden = ("url", "endpoint", "channel", "signing", "key", "label", "mirror")
        update_keys = [key for key in CONFIG_KEYS if "update" in key]
        self.assertEqual(update_keys, ["software_update_check_enabled"])
        for key in update_keys:
            for word in forbidden:
                self.assertNotIn(word, key.replace("software_update_check_enabled", ""))

    def test_the_only_update_setting_is_a_validated_boolean(self):
        self.assertIs(DEFAULT_CONFIG["software_update_check_enabled"], True)
        candidate = {**DEFAULT_CONFIG, "software_update_check_enabled": "yes"}
        with self.assertRaisesRegex(Exception, "must be true or false"):
            validate_config(candidate)
        validate_config({**DEFAULT_CONFIG, "software_update_check_enabled": False})

    def test_safety_bounds_are_present_and_conservative(self):
        self.assertGreaterEqual(trust.PROBATION_START_LIMIT, 2)
        self.assertGreaterEqual(trust.PROBATION_DWELL_SECONDS, 30)
        self.assertGreaterEqual(trust.RETAINED_VERSION_SLOTS, 2)
        self.assertLessEqual(trust.NETWORK_TIMEOUT_SECONDS, 15)
        self.assertLessEqual(trust.MAX_CHANNEL_RESPONSE_BYTES, 1024 * 1024)
        self.assertLessEqual(trust.MAX_MANIFEST_BYTES, 1024 * 1024)
        self.assertGreaterEqual(trust.CHECK_INTERVAL_SECONDS, 60 * 60)
        self.assertGreaterEqual(trust.MEDIA_POLL_SECONDS, 2)

    def test_the_release_catalog_describes_the_running_version(self):
        entry = catalog.installed_entry()
        self.assertIsNotNone(entry, f"no catalog entry for {__version__}")
        self.assertEqual(entry.version, __version__)
        self.assertTrue(entry.features)
        for feature in entry.features:
            with self.subTest(feature=feature):
                self.assertLessEqual(len(feature), 56)


class SupervisedLauncherSourceTests(unittest.TestCase):
    def test_the_launcher_never_evaluates_or_sources_untrusted_input(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        for construct in ("eval ", "eval\t", '. "$STATE', "source ", "$(<"):
            self.assertNotIn(construct, source)
        self.assertIn("set -eu", source)
        self.assertIn("case \"$ATTEMPTS\" in ''|*[!0-9]*)", source)
        self.assertIn('case "$PREVIOUS" in *[!0-9A-Za-z.-]*)', source)

    def test_the_launcher_exports_the_deployment_root_for_the_application(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn('FLOORTERMINAL_HOME="$ROOT"', source)
        self.assertIn("FLOORTERMINAL_SUPERVISED=1", source)
        self.assertIn('exec "$APP"', source)

    def test_the_launcher_switches_versions_with_an_atomic_rename(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn('ln -s "versions/$PREVIOUS/$APP_NAME" "$tmp_link"', source)
        self.assertIn('mv -f "$tmp_link" "$APP"', source)
        self.assertNotIn("cp ", source)
        self.assertNotIn("rm -rf", source)


class InstallerAndServiceTests(unittest.TestCase):
    def test_the_installer_creates_managed_version_slots(self):
        source = INSTALLER.read_text(encoding="utf-8")
        for expected in (
            "$TARGET_DIR/versions/$VERSION",
            "$TARGET_DIR/bin",
            "$TARGET_DIR/update/staging",
            "floorterminal-launch",
            "boot_state",
            "Preserved existing config.json",
            "Preserved existing connector.json",
        ):
            self.assertIn(expected, source)

    def test_the_installer_validates_the_release_version_before_using_it_as_a_path(
        self,
    ):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("^[0-9]+\\.[0-9]+\\.[0-9]+(-rc\\.[0-9]+)?$", source)

    def test_the_installer_switches_the_active_version_atomically(self):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn(
            'mv -f "$TARGET_DIR/.$APP_NAME.installing" "$TARGET_DIR/$APP_NAME"', source
        )

    def test_the_installer_preserves_an_earlier_flat_installation_as_evidence(self):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("replaced-executable-", source)
        self.assertNotIn('rm -f "$TARGET_DIR/$APP_NAME"', source)

    def test_the_service_runs_the_supervised_launcher(self):
        source = SERVICE.read_text(encoding="utf-8")
        self.assertIn("ExecStart=/opt/floorterminal/bin/floorterminal-launch", source)
        self.assertIn("Restart=always", source)
        self.assertIn("ReadWritePaths=/opt/floorterminal", source)
        self.assertIn("ReadWritePaths=-/media", source)
        self.assertIn("NoNewPrivileges=true", source)
        self.assertIn("ProtectSystem=strict", source)

    def test_supervised_restarts_stay_inside_the_start_rate_limit(self):
        source = SERVICE.read_text(encoding="utf-8")
        burst = int(re.search(r"StartLimitBurst=(\d+)", source).group(1))
        self.assertGreater(burst, trust.PROBATION_START_LIMIT)


class ReleasePipelineTests(unittest.TestCase):
    def test_the_builder_ships_the_version_marker_and_launcher(self):
        source = BUILDER.read_text(encoding="utf-8")
        self.assertIn('(RELEASE_DIR / "VERSION").write_text', source)
        self.assertIn('ASSETS_DIR / "floorterminal-launch"', source)
        self.assertIn("MANAGED VERSION SLOTS AND OFFLINE UPDATES", source)
        self.assertIn("chmod +x install.sh floorterminal-launch floorterminal", source)

    def test_the_on_target_verifier_expects_the_exact_release_file_set(self):
        source = PI_SCRIPT.read_text(encoding="utf-8")
        expected = re.search(r"expected=\$'([^']+)'", source).group(1).split("\\n")
        self.assertEqual(expected, sorted(expected))
        for name in (
            "VERSION",
            "floorterminal-launch",
            "floorterminal-icon.png",
            "install.sh",
            "floorterminal",
        ):
            self.assertIn(name, expected)

    def test_release_tooling_refuses_to_sign_with_an_untrusted_key(self):
        source = (ROOT / "scripts" / "release" / "build_update_package.py").read_text()
        self.assertIn("is not listed in TRUSTED_KEYS", source)
        self.assertIn("does not match the trusted public key", source)
        self.assertIn("Self-verification of the generated package failed", source)

    def test_no_private_signing_material_is_tracked_in_the_repository(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("maintainer_keys/*", ignore)
        self.assertIn("*.private.json", ignore)
        tracked = [
            path
            for path in ROOT.rglob("*.private.json")
            if ".git" not in path.parts and "maintainer_keys" not in path.parts
        ]
        self.assertEqual(tracked, [])

    def test_the_update_channel_directory_is_documented_for_publication(self):
        source = (ROOT / "scripts" / "release" / "build_update_package.py").read_text()
        self.assertIn("update-channel", source)
        self.assertIn("latest.json.sig", source)


class ExampleConfigurationTests(unittest.TestCase):
    def test_the_tracked_example_enables_the_optional_check(self):
        config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        self.assertIs(config["software_update_check_enabled"], True)


if __name__ == "__main__":
    unittest.main()
