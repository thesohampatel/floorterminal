import importlib.util
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BUILD_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build" / "build.py"
SPEC = importlib.util.spec_from_file_location("history_builder", BUILD_SCRIPT)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class BuildHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.history = self.root / "build_history"
        self.index = self.root / "BUILD_HISTORY.jsonl"
        self.release = self.root / "dist" / "floorterminal"
        self.release.mkdir(parents=True)
        self.project_profile = self.root / "project_profile.json"
        self.config = self.root / "config.json"
        self.project_profile.write_text(
            json.dumps(
                {
                    "product_name": "Test Product",
                    "maintainer_name": "Test Maintainer",
                    "distribution_name": "Community Test Profile",
                    "support_contact": "support@example.invalid",
                    "license_name": "Test License",
                    "license_identifier": "LicenseRef-Test",
                    "license_version": "1.0",
                }
            ),
            encoding="utf-8",
        )
        self.config.write_text("{}", encoding="utf-8")
        self.patches = (
            patch.object(builder, "PROJECT_DIR", self.root),
            patch.object(builder, "BUILD_HISTORY_DIR", self.history),
            patch.object(builder, "BUILD_HISTORY_INDEX", self.index),
            patch.object(builder, "RELEASE_DIR", self.release),
            patch.object(builder, "PROJECT_PROFILE_FILE", self.project_profile),
        )
        for item in self.patches:
            item.start()

    def tearDown(self):
        if not isinstance(sys.stdout, type(sys.__stdout__)):
            sys.stdout = sys.__stdout__
        if not isinstance(sys.stderr, type(sys.__stderr__)):
            sys.stderr = sys.__stderr__
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def latest_record(self):
        return json.loads(self.index.read_text(encoding="utf-8").splitlines()[-1])

    def test_distribution_profile_builds_receive_isolated_release_directories(self):
        project_profile = SimpleNamespace(distribution_name="Community / Demo")
        first = builder.release_directory_for(
            project_profile,
            "build-one",
            output_root=self.root / "dist",
        )
        second = builder.release_directory_for(
            project_profile,
            "build-two",
            output_root=self.root / "dist",
        )
        self.assertEqual(
            first,
            self.root
            / "dist"
            / "releases"
            / "community-demo"
            / "build-one"
            / "floorterminal",
        )
        self.assertNotEqual(first, second)
        self.assertEqual(builder.safe_slug("  À / ???  "), "unnamed-profile")

    def test_failed_build_does_not_claim_stale_release_files(self):
        (self.release / builder.RELEASE_NOTICES).write_text("stale notices")
        (self.release / "SHA256SUMS").write_text("stale manifest")

        recorder = builder.BuildRecorder()
        record_path = recorder.finish(
            "failed", "intentional failure", "linux", "aarch64"
        )
        record = self.latest_record()

        self.assertEqual(record["outcome"], "failed")
        self.assertEqual(record["error"], "intentional failure")
        self.assertIsNone(record["artifact_sha256"])
        self.assertIsNone(record["release_notices_sha256"])
        self.assertIsNone(record["release_manifest_sha256"])
        self.assertFalse((record_path.parent / builder.RELEASE_NOTICES).exists())

    def test_source_fingerprint_includes_code_but_not_docs_or_private_runtime(self):
        source = self.root / "src"
        source.mkdir()
        module = source / "example.py"
        module.write_text("VALUE = 1\n")
        before = builder.source_input_manifest()
        self.assertIn("src/example.py", before["files"])
        self.assertNotIn("project_profile.json", before["files"])
        self.config.write_text('{"changed": true}')
        (self.root / "README.md").write_text("Release notes after compilation")
        self.assertEqual(before, builder.source_input_manifest())
        recorder = builder.BuildRecorder()
        try:
            recorder.verify_source_inputs()
            module.write_text("VALUE = 2\n")
            with self.assertRaises(builder.BuildError):
                recorder.verify_source_inputs()
        finally:
            path = recorder.finish("failed", "intentional input change")
        retained = json.loads((path.parent / "source_manifest.json").read_text())
        self.assertEqual(retained, before)
        self.assertEqual(self.latest_record()["source_inputs_sha256"], before["sha256"])

    def test_successful_build_records_hashes_and_retains_release_notices(self):
        artifact = self.release / "floorterminal"
        artifact.write_bytes(b"compiled artifact")
        notices = self.release / builder.RELEASE_NOTICES
        notices.write_text("release notices", encoding="utf-8")
        manifest = self.release / "SHA256SUMS"
        manifest.write_text("release manifest", encoding="utf-8")

        recorder = builder.BuildRecorder()
        record_path = recorder.finish("success", None, "linux", "aarch64")
        record = self.latest_record()

        self.assertEqual(record["outcome"], "success")
        self.assertEqual(record["artifact_sha256"], builder.sha256_file(artifact))
        self.assertEqual(record["release_notices_sha256"], builder.sha256_file(notices))
        self.assertEqual(
            record["release_manifest_sha256"], builder.sha256_file(manifest)
        )
        self.assertEqual(
            (record_path.parent / builder.RELEASE_NOTICES).read_text(encoding="utf-8"),
            "release notices",
        )

    def test_build_history_is_owner_private_and_rejects_a_symlink_root(self):
        recorder = builder.BuildRecorder()
        record_path = recorder.finish("failed", "permission check", "linux", "aarch64")

        for directory in (
            self.history,
            record_path.parents[3],
            record_path.parents[2],
            record_path.parents[1],
            record_path.parent,
        ):
            with self.subTest(directory=directory):
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        for path in (record_path, record_path.parent / "build.log", self.index):
            with self.subTest(path=path):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

        other_root = self.root / "other-history"
        other_root.mkdir()
        linked = self.root / "linked-history"
        linked.symlink_to(other_root, target_is_directory=True)
        with (
            patch.object(builder, "BUILD_HISTORY_DIR", linked),
            self.assertRaises(builder.BuildError),
        ):
            builder.BuildRecorder()


if __name__ == "__main__":
    unittest.main()
