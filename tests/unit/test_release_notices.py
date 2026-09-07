import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

BUILD_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build" / "build.py"
SPEC = importlib.util.spec_from_file_location("release_builder", BUILD_SCRIPT)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class ReleaseNoticesTests(unittest.TestCase):
    def test_builder_deployment_instructions_cover_prebuilt_pi_installation(self):
        source = BUILD_SCRIPT.read_text()
        for text in (
            "INSTALL ON 64-BIT RASPBERRY PI OS",
            "sha256sum -c SHA256SUMS",
            "must report ELF 64-bit ARM aarch64",
            "The bundle is an application, not a Raspberry Pi OS disk image",
            "initial Settings password is admin@123 (public)",
            "Change Settings password before production use",
            "Local reporting works without",
        ):
            self.assertIn(text, source)

    def test_builder_runs_the_offline_suite_before_compilation(self):
        source = BUILD_SCRIPT.read_text()
        self.assertIn("Running offline release tests", source)
        self.assertIn('"unittest"', source)
        self.assertIn('"discover"', source)

    def test_spdx_sbom_identifies_artifact_and_build_tool(self):
        profile = SimpleNamespace(
            product_name="Factory Operations Console",
            maintainer_name="Project Maintainers",
            license_identifier="MIT",
        )
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory)
            artifact = release / "floorterminal"
            artifact.write_bytes(b"native artifact")
            original = builder.RELEASE_DIR
            builder.RELEASE_DIR = release
            try:
                builder.write_sbom(
                    profile,
                    "6.0.0",
                    "linux",
                    "aarch64",
                    artifact,
                    "5ab2b9ce-f7de-4c30-90c9-d8f0c406aa2b",
                    "2026-08-30T12:34:56Z",
                )
            finally:
                builder.RELEASE_DIR = original
            sbom = json.loads((release / builder.SBOM_FILE).read_text())
            self.assertEqual(sbom["spdxVersion"], "SPDX-2.3")
            application = next(
                package
                for package in sbom["packages"]
                if package["SPDXID"] == "SPDXRef-Package-Application"
            )
            self.assertEqual(
                application["checksums"][0]["checksumValue"],
                builder.artifact_sha256(artifact),
            )

    def test_notices_bind_identity_and_legal_terms_to_one_build(self):
        project_profile = SimpleNamespace(
            product_name="Factory Operations Console",
            maintainer_name="Example Maintainer",
            distribution_name="Community Demo",
            support_contact="support@example.invalid",
            copyright_notice="Copyright 2026 Example Maintainer",
            license_name="MIT License",
            license_version="Standard",
            license_identifier="MIT",
            license_summary="Open-source use and redistribution with notice retention.",
        )
        license_text = "MIT License\nPermission is hereby granted.\n"
        notices = builder.render_release_notices(
            project_profile,
            "9.8.7",
            "linux",
            "aarch64",
            "floorterminal",
            "a" * 64,
            "b" * 64,
            "c" * 64,
            "5ab2b9ce-f7de-4c30-90c9-d8f0c406aa2b",
            "2026-08-15T12:34:56Z",
            license_text,
        )
        for value in (
            project_profile.product_name,
            project_profile.maintainer_name,
            project_profile.distribution_name,
            project_profile.support_contact,
            project_profile.license_identifier,
            "9.8.7",
            "linux / aarch64",
            "5ab2b9ce-f7de-4c30-90c9-d8f0c406aa2b",
            "2026-08-15T12:34:56Z",
            "a" * 64,
            "b" * 64,
            "c" * 64,
            license_text.rstrip(),
            "KEEP THIS FILE WITH THE SOFTWARE",
            "OPERATIONAL, SAFETY, AND HUMAN-DECISION NOTICE",
            "DATA, SECURITY, NETWORK, AND THIRD-PARTY NOTICE",
            "BEGIN LICENSE",
            "END LICENSE",
        ):
            self.assertIn(value, notices)
        self.assertNotIn("API key", notices)
        self.assertRegex(
            notices,
            re.compile(
                r"connector\.json is\s+disabled and credential-free", re.IGNORECASE
            ),
        )


if __name__ == "__main__":
    unittest.main()
